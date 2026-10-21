"""FR-23 (QF-678/679) 防篡改审计事件.

001 gatekeeper 已有 ``gate_events`` 落点，但它只做"落库"，不提供篡改检测，
且与业务库同集合混放。本模块在 **独立集合 ``audit_events``** 上实现：

1. **哈希链**：每条事件携带 ``prev_hash`` 与自身 ``event_hash``，
   ``event_hash = SHA256(prev_hash || canonical_json(其余字段))``。
   任意修改、插入或删除中间事件都会破坏链条。
2. **顺序号**：``seq`` 唯一递增，配合唯一索引检测并发写冲突。
3. **最小化**：审计文档只记必要字段，敏感值经 :mod:`app.security.redaction`
   脱敏后才落库（审计库本身可能比业务库权限更低，因此不存明文敏感值）。

⚠️ **诚实边界**：这是**篡改可检测（tamper-evident）**，不是**篡改不可行**
（tamper-proof）。有集合写权限的一方仍然能改写历史——但改写后
:func:`AuditEventRepository.verify_chain` 会报错，这正是审计的意义。

并发语义：``record`` 采用「读游标 → 计算哈希 → 插入 → CAS 更新游标」，
以 ``seq`` 唯一索引兜底。冲突时 :func:`AuditEventRepository.record` 抛出
:class:`AuditChainConflict`，调用方重试即可（游标已前进，重试会拿到新 prev_hash）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from . import redaction as _redaction
from .redaction import RedactionConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

AUDIT_EVENTS_COLLECTION = "audit_events"
# 022 FR-17（T044）：审计日志保留期下限（合规取证基线，≥180 天）。
# 低于该值的配置会被提升到此下限并打告警 —— 保留期不能由运维随意缩短。
MIN_AUDIT_RETENTION_DAYS = 180


def normalize_retention_days(days: int) -> int:
    """把配置的保留天数规整到合规下限。

    ``-1``（或任何负数）表示禁用 TTL 自动清理；其余值不低于
    :data:`MIN_AUDIT_RETENTION_DAYS`。
    """
    value = int(days)
    if value < 0:
        return value
    return max(value, MIN_AUDIT_RETENTION_DAYS)
CHAIN_CURSOR_ID = "__chain_cursor__"
MAX_RECORD_RETRIES = 5

SCHEMA_VERSION = 1

EVENT_ID_PREFIX = "evt"


class AuditEventError(ValueError):
    """审计事件构造/校验错误。"""


class AuditChainConflict(AuditEventError):
    """并发写入导致的哈希链冲突（游标被其他写入者推进）。调用方应重试。"""


class AuditChainBroken(AuditEventError):
    """校验发现哈希链断裂。"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(obj: Any) -> bytes:
    """稳定序列化：键排序、无空白、UTF-8。哈希链对序列化格式敏感，必须固定。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def chain_hash(prev_hash: str | None, body: Mapping[str, Any]) -> str:
    """计算事件哈希：``SHA256(prev_hash || canonical_json(body))``。"""
    digest = hashlib.sha256()
    digest.update((prev_hash or "").encode("utf-8"))
    digest.update(b"\x1f")  # 分隔符，避免 prev_hash 与 body 的边界歧义
    digest.update(_canonical_json(body))
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 事件构造
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEvent:
    """一条审计事件。"""

    tenant_id: str | None
    actor_type: str
    actor_id: str
    action: str
    decision: str
    occurred_at: datetime
    event_id: str = field(default_factory=lambda: f"{EVENT_ID_PREFIX}-{uuid.uuid4().hex}")
    target_type: str | None = None
    target_id: str | None = None
    source_service: str = ""
    client_ip: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    prev_hash: str | None = None
    event_hash: str | None = None
    seq: int | None = None

    def __post_init__(self) -> None:
        if not self.action:
            raise AuditEventError("action is required")
        if not self.decision:
            raise AuditEventError("decision is required")
        if not self.actor_type:
            raise AuditEventError("actor_type is required")

    def body(self) -> dict[str, Any]:
        """参与哈希计算的规范化字段集合（不含 prev_hash / event_hash）。"""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "tenant_id": self.tenant_id,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "action": self.action,
            "decision": self.decision,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "source_service": self.source_service,
            "client_ip": self.client_ip,
            "detail": dict(self.detail or {}),
        }

    def with_hash(self, prev_hash: str | None, seq: int) -> "AuditEvent":
        """返回带有链信息的副本。"""
        body = self.body()
        event_hash = chain_hash(prev_hash, body)
        return AuditEvent(
            tenant_id=self.tenant_id,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            action=self.action,
            decision=self.decision,
            occurred_at=self.occurred_at,
            event_id=self.event_id,
            target_type=self.target_type,
            target_id=self.target_id,
            source_service=self.source_service,
            client_ip=self.client_ip,
            detail=dict(self.detail or {}),
            schema_version=self.schema_version,
            prev_hash=prev_hash,
            event_hash=event_hash,
            seq=seq,
        )

    def document(self) -> dict[str, Any]:
        """可落库的文档。"""
        return {
            "_id": self.event_id,
            **self.body(),
            "prev_hash": self.prev_hash,
            "event_hash": self.event_hash,
            "seq": self.seq,
        }

    def verify(self) -> None:
        """自检：event_hash 是否与 prev_hash + body 一致。"""
        if not self.event_hash or self.seq is None:
            raise AuditChainBroken("event is missing event_hash or seq")
        expected = chain_hash(self.prev_hash, self.body())
        if expected != self.event_hash:
            raise AuditChainBroken(f"event {self.event_id} hash mismatch")


def build_event(
    *,
    action: str,
    decision: str,
    actor_type: str = "user",
    actor_id: str = "",
    tenant_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    source_service: str = "",
    client_ip: str | None = None,
    detail: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
    redaction_config: RedactionConfig = DEFAULT_CONFIG,
) -> AuditEvent:
    """构造审计事件，**detail 自动脱敏**（FR-23 与 FR-20 联动）。"""
    cleaned = _redaction.redact(dict(detail or {}), config=redaction_config)
    return AuditEvent(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        decision=decision,
        occurred_at=occurred_at or utcnow(),
        target_type=target_type,
        target_id=target_id,
        source_service=source_service,
        client_ip=client_ip,
        detail=cleaned,
    )


# ---------------------------------------------------------------------------
# 校验报告
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainVerification:
    """哈希链校验结果。"""

    ok: bool
    checked: int = 0
    first_broken_seq: int | None = None
    first_broken_event_id: str | None = None
    reason: str = ""

    @property
    def summary(self) -> str:
        if self.ok:
            return f"chain ok ({self.checked} events)"
        return f"chain BROKEN at seq={self.first_broken_seq} ({self.reason})"


def verify_chain(events: Iterable[AuditEvent]) -> ChainVerification:
    """校验一个按 seq 升序排列的事件序列。"""
    prev_hash: str | None = None
    checked = 0
    expected_seq: int | None = None
    for event in events:
        checked += 1
        seq = event.seq
        if seq is None or event.event_hash is None:
            return ChainVerification(False, checked, None, event.event_id, "missing hash/seq")
        if expected_seq is not None and seq != expected_seq:
            return ChainVerification(
                False, checked, seq, event.event_id, f"seq gap: expected {expected_seq}, got {seq}"
            )
        if event.prev_hash != prev_hash:
            return ChainVerification(
                False, checked, seq, event.event_id, f"prev_hash mismatch: expected {prev_hash!r}"
            )
        expected = chain_hash(prev_hash, event.body())
        if expected != event.event_hash:
            return ChainVerification(False, checked, seq, event.event_id, "event_hash mismatch")
        prev_hash = event.event_hash
        expected_seq = seq + 1
    return ChainVerification(True, checked)


def _from_document(doc: Mapping[str, Any]) -> AuditEvent:
    return AuditEvent(
        tenant_id=doc.get("tenant_id"),
        actor_type=str(doc.get("actor_type") or ""),
        actor_id=str(doc.get("actor_id") or ""),
        action=str(doc.get("action") or ""),
        decision=str(doc.get("decision") or ""),
        occurred_at=_parse_dt(doc.get("occurred_at")) or utcnow(),
        event_id=str(doc.get("_id") or doc.get("event_id") or ""),
        target_type=doc.get("target_type"),
        target_id=doc.get("target_id"),
        source_service=str(doc.get("source_service") or ""),
        client_ip=doc.get("client_ip"),
        detail=dict(doc.get("detail") or {}),
        schema_version=int(doc.get("schema_version") or SCHEMA_VERSION),
        prev_hash=doc.get("prev_hash"),
        event_hash=doc.get("event_hash"),
        seq=None if doc.get("seq") is None else int(doc["seq"]),
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------


class AuditEventRepository:
    """``audit_events`` 集合的读写 + 哈希链维护。

    ``db`` 为 motor 风格的 async database 对象（``db[collection]`` 可用）。
    传入自定义对象即可用 fake 做单元测试。
    """

    def __init__(
        self,
        db: Any,
        *,
        collection: str = AUDIT_EVENTS_COLLECTION,
        cursor_id: str = CHAIN_CURSOR_ID,
        source_service: str = "",
        redaction_config: RedactionConfig = DEFAULT_CONFIG,
        retention_days: int = MIN_AUDIT_RETENTION_DAYS,
    ) -> None:
        self._db = db
        self._collection_name = collection
        self._cursor_id = cursor_id
        self._source_service = source_service
        self._redaction_config = redaction_config
        # 022 FR-17（T044）：规整到合规下限；-1 表示禁用 TTL 自动清理。
        configured = int(retention_days)
        self._retention_days = normalize_retention_days(configured)
        if self._retention_days != configured and configured >= 0:
            logger.warning(
                "audit_retention_days=%s 低于合规下限 %s 天，已提升到 %s 天",
                configured, MIN_AUDIT_RETENTION_DAYS, self._retention_days,
            )

    def _coll(self) -> Any:
        return self._db[self._collection_name]

    async def ensure_indexes(self) -> None:
        coll = self._coll()
        await coll.create_index([("seq", 1)], unique=True, sparse=True, name="audit_events_seq_unique")
        await coll.create_index([("tenant_id", 1), ("occurred_at", -1)], name="audit_events_tenant_time")
        await coll.create_index([("tenant_id", 1), ("action", 1)], name="audit_events_tenant_action")
        await coll.create_index([("actor_id", 1), ("occurred_at", -1)], name="audit_events_actor_time")
        # 022 FR-17（T044）：TTL 索引是保留期的自动执行机制（MongoDB 后台
        # 定期删除过期文档），与显式 :meth:`purge_expired` 互为双保险。
        # 索引建立在 occurred_at 上 —— 事件写入时必填，天然单调递增。
        if self._retention_days > 0:
            await coll.create_index(
                [("occurred_at", 1)],
                expireAfterSeconds=self._retention_days * 86400,
                name="audit_events_retention_ttl",
            )

    async def latest_cursor(self) -> dict[str, Any]:
        doc = await self._coll().find_one({"_id": self._cursor_id})
        if not doc:
            return {"seq": 0, "latest_hash": None}
        return {"seq": int(doc.get("seq") or 0), "latest_hash": doc.get("latest_hash")}

    async def record(
        self,
        event: AuditEvent | None = None,
        *,
        retries: int = MAX_RECORD_RETRIES,
        **fields: Any,
    ) -> AuditEvent:
        """落库一条审计事件，返回带哈希与 seq 的事件。

        并发写入会触发 :class:`AuditChainConflict`，调用方重试即可。
        """
        if event is None:
            event = build_event(
                source_service=self._source_service,
                redaction_config=self._redaction_config,
                **fields,
            )

        last_exc: Exception | None = None
        for _ in range(max(1, retries)):
            cursor = await self.latest_cursor()
            prev_hash = cursor["latest_hash"]
            seq = int(cursor["seq"]) + 1
            stamped = event.with_hash(prev_hash, seq)
            try:
                await self._coll().insert_one(stamped.document())
            except Exception as exc:  # noqa: BLE001 - 仅识别唯一索引冲突
                if not _is_duplicate_key(exc):
                    raise
                last_exc = exc
                continue
            await self._advance_cursor(seq, stamped.event_hash)
            return stamped
        raise AuditChainConflict(
            f"audit chain cursor conflict after {retries} retries"
        ) from last_exc

    async def _advance_cursor(self, seq: int, latest_hash: str) -> None:
        await self._coll().update_one(
            {"_id": self._cursor_id},
            {
                "$set": {
                    "seq": seq,
                    "latest_hash": latest_hash,
                    "updated_at": utcnow(),
                }
            },
            upsert=True,
        )

    async def list_events(
        self,
        *,
        tenant_id: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        include_cursor: bool = False,
    ) -> list[AuditEvent]:
        query: dict[str, Any] = {}
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        if action is not None:
            query["action"] = action
        if since is not None:
            query["occurred_at"] = {"$gte": since}
        if not include_cursor:
            query["_id"] = {"$ne": self._cursor_id}
        cursor = self._coll().find(query)
        return [_from_document(doc) async for doc in cursor.sort([("seq", 1)]).limit(int(limit))]

    async def verify_chain(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 1000,
    ) -> ChainVerification:
        """校验哈希链完整性（篡改检测）。"""
        cursor = self._coll().find(
            {k: v for k, v in ({"tenant_id": tenant_id} if tenant_id is not None else {}).items()}
        )
        events = [
            _from_document(doc)
            async for doc in cursor
            if doc.get("_id") != self._cursor_id and doc.get("seq") is not None
        ]
        events.sort(key=lambda e: (e.seq is None, e.seq or 0))
        events = events[: int(limit)]
        if not events:
            return ChainVerification(True, 0)
        return verify_chain(events)

    async def count(self, *, tenant_id: str | None = None) -> int:
        query: dict[str, Any] = {"_id": {"$ne": self._cursor_id}}
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        return int(await self._coll().count_documents(query))

    @property
    def retention_days(self) -> int:
        """规整后的保留天数（≥ :data:`MIN_AUDIT_RETENTION_DAYS`，或 -1 表示禁用）。"""
        return self._retention_days

    async def purge_expired(
        self,
        *,
        retention_days: int | None = None,
        now: datetime | None = None,
    ) -> int:
        """删除超过保留期的审计事件，返回删除条数（022 FR-17 / T044）。

        TTL 索引会异步做同样的事；这个方法用于：
        1. 需要立即生效的场景（例如合规窗口收窄后的首次清理）；
        2. TTL 索引不可用时的兜底；
        3. 测试。

        ``retention_days`` 显式覆盖时用覆盖值（同样规整到下限）；
        ``now`` 可注入以冻结时钟做单元测试。

        注意：游标文档（``_id == self._cursor_id``）不参与保留期判定，
        否则哈希链的续写基准会被清掉。
        """
        if self._retention_days < 0:
            return 0
        days = normalize_retention_days(self._retention_days if retention_days is None else retention_days)
        if days < 0:
            return 0
        reference = now or utcnow()
        cutoff = reference - timedelta(days=days)
        result = await self._coll().delete_many(
            {"_id": {"$ne": self._cursor_id}, "occurred_at": {"$lt": cutoff}}
        )
        return int(getattr(result, "deleted_count", 0) or 0)


def _is_duplicate_key(exc: Exception) -> bool:
    return "DuplicateKeyError" in type(exc).__name__


class InMemoryAuditDb:
    """极简 fake：实现 motor 风格的最小接口，供单元测试使用。"""

    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, Any]]] = {}

    def __getitem__(self, name: str) -> "_FakeCollection":
        return _FakeCollection(self._collections.setdefault(name, []))


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def insert_one(self, doc: dict[str, Any]) -> None:
        # 模拟 seq 唯一索引：冲突抛 DuplicateKeyError（与 pymongo 同名）
        if doc.get("seq") is not None:
            for existing in self._docs:
                if existing.get("seq") == doc["seq"] and existing.get("_id") != doc.get("_id"):
                    raise DuplicateKeyError()
        self._docs.append(dict(doc))

    async def insert_many(self, docs: Any, ordered: bool = False, continue_on_error: bool = False) -> None:
        for doc in docs:
            await self.insert_one(doc)

    async def delete_one(self, query: dict[str, Any]) -> None:
        for i, doc in enumerate(self._docs):
            if _match(doc, query):
                del self._docs[i]
                return

    async def delete_many(self, query: dict[str, Any]) -> None:
        self._docs[:] = [doc for doc in self._docs if not _match(doc, query)]

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._docs:
            if _match(doc, query):
                return dict(doc)
        return None

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        for i, doc in enumerate(self._docs):
            if _match(doc, query):
                self._docs[i] = {**doc, **update.get("$set", {})}
                return
        if upsert:
            self._docs.append({**query, **update.get("$set", {})})

    async def count_documents(self, query: dict[str, Any]) -> int:
        return sum(1 for doc in self._docs if _match(doc, query))

    async def create_index(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def find(self, query: dict[str, Any]) -> "_FakeCursor":
        return _FakeCursor([dict(doc) for doc in self._docs if _match(doc, query)])


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)
        self._sort_spec: list[tuple[str, int]] = []
        self._limit: int | None = None
        self._idx = 0

    def sort(self, spec: Any, **_kwargs: Any) -> "_FakeCursor":
        self._sort_spec = list(spec) if isinstance(spec, list) else []
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._limit = int(n)
        return self

    def _materialize(self) -> list[dict[str, Any]]:
        docs = [dict(d) for d in self._docs]
        if self._sort_spec:
            for field, direction in reversed(self._sort_spec):
                docs.sort(
                    key=lambda d, f=field: (d.get(f) is None, d.get(f) if d.get(f) is not None else 0),
                    reverse=direction < 0,
                )
        if self._limit is not None:
            docs = docs[: self._limit]
        return docs

    def __aiter__(self) -> "_FakeCursor":
        self._docs = self._materialize()
        self._idx = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._idx]
        self._idx += 1
        return doc


class DuplicateKeyError(Exception):
    """fake 集合里的唯一索引冲突（与 pymongo 同名，供 :func:`_is_duplicate_key` 识别）。"""


def _match(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if isinstance(expected, dict):
            if "$ne" in expected and doc.get(key) == expected["$ne"]:
                return False
            if "$gt" in expected and not (doc.get(key) is not None and doc[key] > expected["$gt"]):
                return False
            if "$gte" in expected and not (doc.get(key) is not None and doc[key] >= expected["$gte"]):
                return False
            if "$lt" in expected and not (doc.get(key) is not None and doc[key] < expected["$lt"]):
                return False
            continue
        if doc.get(key) != expected:
            return False
    return True


__all__ = [
    "AUDIT_EVENTS_COLLECTION",
    "AuditChainBroken",
    "AuditChainConflict",
    "AuditEvent",
    "AuditEventError",
    "AuditEventRepository",
    "CHAIN_CURSOR_ID",
    "ChainVerification",
    "InMemoryAuditDb",
    "SCHEMA_VERSION",
    "build_event",
    "chain_hash",
    "verify_chain",
    "utcnow",
]
