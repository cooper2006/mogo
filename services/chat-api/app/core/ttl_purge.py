"""PanWeiDB TTL 清理循环（MongoDB → PanWeiDB 迁移）。

openGauss 无原生 TTL 索引，Mongo 的 ``expireAfterSeconds`` 语义改由本循环在
应用层定期执行：对兼容层登记的所有 TTL 声明（见
``app.core.pg_compat._TTL_REGISTRY``）执行 ``DELETE ... WHERE 过期``。

仅 ``MOGO_DATA_BACKEND=panweidb`` 时启动；mongo 模式为 no-op（mongo 自带 TTL）。
启动后**先等待一个间隔再首次清理**，避免启动瞬间即删除。
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.core import pg
from app.core.config import settings
from app.core.pg_compat import purge_expired_ttl

logger = logging.getLogger(__name__)

#: 清理间隔（秒）。默认 1 小时；可用 ``MOGO_TTL_PURGE_INTERVAL_SECONDS`` 覆盖。
DEFAULT_INTERVAL_SECONDS = 3600


def _interval_seconds() -> int:
    try:
        value = int(os.getenv("MOGO_TTL_PURGE_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    return value if value > 0 else DEFAULT_INTERVAL_SECONDS


class TtlPurgeLoop:
    """后台定期清理过期文档（best-effort，失败不中断循环）。"""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not pg.is_panweidb_backend() or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="ttl-purge")

    async def _loop(self) -> None:
        interval = _interval_seconds()
        while True:
            await asyncio.sleep(interval)
            try:
                pool = pg.get_async_pool()
                if pool is None:
                    continue
                deleted = await purge_expired_ttl(pool, settings.effective_panweidb_schema)
                if deleted:
                    logger.info("TTL 清理删除 %d 条过期文档", deleted)
            except Exception:  # pragma: no cover - 清理失败绝不应中断循环
                logger.warning("TTL 清理循环异常", exc_info=True)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # pragma: no cover - 关闭失败不应阻断进程退出
                logger.warning("停止 TTL 清理循环失败", exc_info=True)


ttl_purge_loop = TtlPurgeLoop()
