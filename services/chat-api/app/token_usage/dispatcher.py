from __future__ import annotations

import asyncio
import logging
from typing import Optional

from prometheus_client import Counter

from app.core.config import get_settings
from app.core.db import get_db
from app.token_usage.models import TokenUsageRecord
from app.token_usage.push import TokenUsagePushService


# ── Prometheus 指标 ──────────────────────────────────────────────────────
# registry=None：本模块在 import 期即构造 Counter，而服务专属 CollectorRegistry
# 要到 main.py 的 init_metrics() 才建立；早期版本误用 get_settings().prometheus_registry
# （Settings 并无该属性）会让整个 chat-api 导入即崩。改为先不注册，再由
# register_token_usage_metrics() 在 init_metrics 之后挂到服务 registry，指标才会
# 出现在 /metrics。
metric_queue_full = Counter(
    "mogo_token_usage_queue_full_total",
    "Token usage queue full total count",
    registry=None,
)
metric_persist_failed = Counter(
    "mogo_token_usage_persist_failed_total",
    "Token usage persist failed total count",
    registry=None,
)
metric_dlq_total = Counter(
    "mogo_token_usage_dlq_total",
    "Token usage dead-letter queue total count",
    registry=None,
)


def register_token_usage_metrics(registry) -> None:
    """把用量指标挂到服务专属 CollectorRegistry（须在 init_metrics 之后调用）。

    幂等：重复注册同一同名指标时 prometheus_client 会抛 Duplicated timeseries，
    这里吞掉该异常，保证重复调用/热重载不炸。
    """
    for metric in (metric_queue_full, metric_persist_failed, metric_dlq_total):
        try:
            registry.register(metric)
        except ValueError:
            # 已注册（同名 timeseries）→ 幂等跳过
            pass


logger = logging.getLogger(__name__)

# DLQ 集合名称
DLQ_COLLECTION = "token_usage_dlq"


class TokenUsageDispatcher:
    def __init__(self, *, queue_size: int = 512) -> None:
        self._queue_size = max(int(queue_size or 512), 16)
        self._queue: asyncio.Queue[TokenUsageRecord] | None = None
        self._worker: asyncio.Task | None = None
        self._running = False
        self._push_service = TokenUsagePushService()

    async def start(self) -> None:
        if self._running:
            return
        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._running = True
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except BaseException:
                pass
            self._worker = None
        self._queue = None

    async def _try_dlq_append(self, record: TokenUsageRecord, reason: str) -> None:
        """将记录写入 dead-letter queue 并记录指标。"""
        db = get_db()
        try:
            await db[DLQ_COLLECTION].insert_one(
                {
                    "request_id": record.request_id,
                    "tenant_id": record.tenant_id,
                    "model_name": record.model_name,
                    "stage": record.stage,
                    "total_tokens": record.total_tokens,
                    "rejected_at": asyncio.get_event_loop().time(),
                    "reason": reason,
                    "trace_id": record.trace_id,
                    "user_id": record.user_id,
                    "processed": False,
                }
            )
            metric_dlq_total.inc()
        except Exception as exc:
            logger.error(
                f"Failed to write record to DLQ: {record.request_id}, error: {exc}"
            )

    async def submit(self, record: TokenUsageRecord) -> bool:
        queue = self._queue
        if not self._running or queue is None:
            return False
        try:
            queue.put_nowait(record)
            return True
        except asyncio.QueueFull:
            metric_queue_full.inc()
            await self._try_dlq_append(record, reason="queue_full")
            return False

    async def _run(self) -> None:
        while True:
            record = await self._queue.get()  # type: ignore[union-attr]
            try:
                repo = TokenUsageRepository(get_db())
                await repo.insert(record)

                # 异步累计扣减组织点数
                try:
                    from app.core.billing import deduct_points_after_request
                    await deduct_points_after_request(record.tenant_id or record.tenant_id, record.total_tokens)
                except Exception as b_err:
                    logger.error(f"Failed to process billing for record {record.request_id}: {b_err}")

                if get_settings().DEBUG:
                    logger.debug(
                        "token usage persisted",
                        extra={
                            "event": "token_usage.persisted",
                            "llm_request_id": record.request_id,
                            "stage": record.stage,
                            "trace_id": record.trace_id,
                            "user_id": record.user_id,
                            "total_tokens": record.total_tokens,
                        },
                    )
                push_result = await self._push_service.push(record)
                if push_result.enabled:
                    status = "success" if push_result.pushed else "failed"
                    await repo.mark_push_result(record.request_id, status=status, error=push_result.error)
            except Exception as exc:
                metric_persist_failed.inc()
                await self._try_dlq_append(record, reason=f"persist_error:{type(exc).__name__}")
                # NOTE: do NOT call task_done() here — will be called on successful replay
                continue
            finally:
                self._queue.task_done()  # type: ignore[union-attr]


async def token_usage_reconciliation_loop():
    """定时对账任务：每小时从 DLQ 重放记录到 token_usage_logs。"""
    from app.token_usage.repository import TokenUsageRepository

    while True:
        await asyncio.sleep(3600)  # 每小时对账
        asyncio.create_task(_reconcile_token_usage())


async def _reconcile_token_usage():
    """从 DLQ 重放记录到 token_usage_logs。"""
    from app.core.db import get_db
    from app.token_usage.repository import TokenUsageRepository

    db = get_db()
    dlq_records = await db[DLQ_COLLECTION].find({"processed": False}).to_list(length=100)
    if not dlq_records:
        return

    repo = TokenUsageRepository(get_db())
    for record in dlq_records:
        try:
            # DLQ 存的是扁平子集，重建为 TokenUsageRecord 再落 token_usage_logs
            # （repo.insert 内部调用 record.model_dump()，不能直接传 dict）。
            record_model = TokenUsageRecord(
                request_id=str(record.get("request_id") or ""),
                tenant_id=str(record.get("tenant_id") or "default"),
                user_id=str(record.get("user_id") or ""),
                session_id=str(record.get("session_id") or ""),
                trace_id=str(record.get("trace_id") or ""),
                stage=str(record.get("stage") or ""),
                model_name=str(record.get("model_name") or ""),
                total_tokens=int(record.get("total_tokens") or 0),
            )
            await repo.insert(record_model)
            # 标记已处理
            await db[DLQ_COLLECTION].update_one(
                {"request_id": record["request_id"]}, {"$set": {"processed": True}}
            )
        except Exception as exc:
            logger.error(f"DLQ replay failed for {record.get('request_id')}: {exc}")
            # 保留在 DLQ 以便后续重试