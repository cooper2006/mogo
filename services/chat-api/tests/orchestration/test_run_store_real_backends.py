"""050 P0 回归：``claim_pending`` 必须在真实 motor 与真实 pg_compat 上通过。

背景（2026-11-12 设计复审 P0-1）：``claim_pending`` 曾以
``find_one_and_update(..., return_document=True)`` 执行 ``$unset`` 后再从返回文档
读取 todo。motor 与 027 pg_compat 门面都把 ``True`` 解释为 ReturnDocument.AFTER，
于是 todo 恒为 None：决策抛错，而 ``$unset`` 已落库，运行变成既不可决策、
也不超时、也不可改派的僵尸。

当时 ``tests/orchestration/fixtures/memory_db.py`` 的假集合无论 ``return_document``
取值都返回更新前快照，使 ``test_run_store.py`` 的用例假绿。本文件因此：

* 用真实 MongoDB（``real_mongo_db`` 夹具，独立测试库，teardown 删库）覆盖 mongo 后端；
* 用真实 PostgreSQL/PanWeiDB 连接 + ``app.core.pg_compat.PgDatabase`` 覆盖 panweidb
  后端（独立 schema，teardown DROP SCHEMA）；
* 保留一条纯逻辑用例，锁死假集合自身的 BEFORE/AFTER 语义，防止替身再次退化。

两个后端不可达时各自 skip，不伪造通过。运行示例::

    MONGODB_URI=mongodb://127.0.0.1:27017 \
    MOGO_TEST_PANWEIDB_DSN=postgresql://postgres@127.0.0.1:55432/postgres \
    PYTHONPATH=services/chat-api:sandbox_script \
    .venv-qa/bin/python -m pytest tests/orchestration/test_run_store_real_backends.py -q
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest

from app.orchestration.run_store import RUN_AWAITING, RunStore, RunStoreError, utcnow
from tests.orchestration.fixtures.memory_db import FakeCollection

PG_DSN = os.getenv("MOGO_TEST_PANWEIDB_DSN", "").strip()


def _pg_available() -> bool:
    """配置了 DSN 但服务不可达时 skip 而不是 fail（与 mongo 夹具同口径）。

    本机 ServBay 的 PostgreSQL 会随服务启停波动；「不可达即跳过，不伪造
    通过」是本文件 docstring 的既定承诺，skipif 只挡未配置会漏掉这类波动。
    """
    if not PG_DSN:
        return False
    try:
        import psycopg

        with psycopg.connect(PG_DSN, connect_timeout=3, autocommit=True):
            return True
    except Exception:
        return False


def _document() -> dict:
    return {
        "orchestration": {"id": "real-backend-regression", "version": "1", "mode": "graph"},
        "nodes": [{"id": "approve", "type": "human_approval", "approver": "u-a"}],
        "edges": [],
    }


def _todo() -> dict:
    return {
        "approver": "u-a",
        "deadline": (utcnow() + timedelta(hours=1)).isoformat(),
        "resume_token": "tok-real-backend",
        "prompt": "approve me",
    }


async def _exercise_claim_pending(db) -> None:
    """两个后端共用的验收链：挂起 → 消费 → 待办消失 → 重复消费被拒。"""
    store = RunStore(db)
    run = await store.create_run(document=_document(), tenant_id="t-regression", user_id="u-initiator")
    await store.suspend(run["run_id"], node_id="approve", todo=_todo())

    claimed = await store.claim_pending(run["run_id"], "approve")
    assert claimed["resume_token"] == "tok-real-backend"
    assert claimed["prompt"] == "approve me"

    loaded = await store.get_run(run["run_id"])
    assert loaded is not None
    assert "approve" not in (loaded.get("pending_approvals") or {})
    # store 只消费待办，运行状态由 RunDriver.decide 推进；此处必须仍是 awaiting。
    assert loaded["status"] == RUN_AWAITING

    with pytest.raises(RunStoreError):
        await store.claim_pending(run["run_id"], "approve")


def test_fake_collection_honours_return_document() -> None:
    """假集合必须忠实实现 BEFORE/AFTER，否则会再次掩盖 P0-1。"""

    async def scenario() -> None:
        col = FakeCollection()
        await col.insert_one({"_id": "x", "keep": 1, "drop": "todo"})
        after = await col.find_one_and_update(
            {"_id": "x"}, {"$unset": {"drop": ""}}, return_document=True
        )
        assert after is not None and "drop" not in after
        await col.insert_one({"_id": "y", "keep": 1, "drop": "todo"})
        before = await col.find_one_and_update(
            {"_id": "y"}, {"$unset": {"drop": ""}}, return_document=False
        )
        assert before is not None and before["drop"] == "todo"

    asyncio.run(scenario())


def test_claim_pending_real_motor(real_mongo_db) -> None:
    """真实 motor：AFTER 语义下旧实现会抛错且已删掉待办。"""
    real_mongo_db.run(_exercise_claim_pending(real_mongo_db.db))


@pytest.mark.skipif(
    not _pg_available(),
    reason="MOGO_TEST_PANWEIDB_DSN 未配置或 PostgreSQL 不可达：跳过真实 pg_compat 用例",
)
def test_claim_pending_real_pg_compat() -> None:
    """真实 pg_compat：门面同样把 True 解释为 AFTER。"""
    from psycopg_pool import AsyncConnectionPool

    from app.core.pg_compat import PgDatabase

    schema = f"mogo_test_{uuid.uuid4().hex[:10]}"

    async def scenario() -> None:
        pool = AsyncConnectionPool(PG_DSN, open=False, min_size=1, max_size=2)
        await pool.open(wait=True, timeout=5)
        try:
            await _exercise_claim_pending(PgDatabase(pool, schema))
        finally:
            try:
                async with pool.connection() as conn:
                    await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                    await conn.commit()
            finally:
                await pool.close()

    asyncio.run(scenario())
