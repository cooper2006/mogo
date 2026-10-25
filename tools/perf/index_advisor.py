"""026 T018 — 索引策略助手（chat-api MongoDB 索引建议 + 覆盖率统计）。

按访问模式为关键 collection（session / config / permission / token /
document 等）定义复合索引，输出建议；``--apply`` 在真实 Mongo 上建索引；
``--coverage`` 用 ``explain("executionStats")`` 统计索引使用率
（totalDocsExamined ≈ nReturned 视为索引覆盖，覆盖率 > 95% 为目标，FR-8）。

用法（在 chat-api venv 内，连 ``MONGODB_URI``）::

    python tools/perf/index_advisor.py --suggest
    python tools/perf/index_advisor.py --coverage
    python tools/perf/index_advisor.py --apply chat_sessions

本脚本只读/建索引，不改数据。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

# 访问模式 → 建议索引（FR-8：按访问模式建立复合索引与覆盖索引）
# 键：collection；值：{name, keys: [(字段, 方向)], desc 注释}
SUGGESTED_INDEXES: Dict[str, List[Dict[str, Any]]] = {
    "chat_sessions": [
        {
            "name": "idx_sessions_tenant_updated",
            "keys": [("tenant_id", 1), ("updated_at", -1)],
            "desc": "按租户列出会话并按更新时间倒序（会话列表页 / 恢复最近会话）",
        },
        {
            "name": "idx_sessions_enduser_status",
            "keys": [("end_user_id", 1), ("status", 1), ("created_at", -1)],
            "desc": "按终端用户 + 状态查询会话（活跃会话校验）",
        },
    ],
    "chat_messages": [
        {
            "name": "idx_messages_session_seq",
            "keys": [("session_id", 1), ("seq", 1)],
            "desc": "按会话顺序拉取消息（对话历史 / 流式续写）",
        },
        {
            "name": "idx_messages_tenant_role",
            "keys": [("tenant_id", 1), ("role", 1), ("created_at", -1)],
            "desc": "覆盖索引：租户 + 角色过滤时避免回表",
        },
    ],
    "memories": [
        {
            "name": "idx_memories_tenant_updated",
            "keys": [("tenant_id", 1), ("updated_at", -1)],
            "desc": "记忆库列表 / 最近更新优先",
        },
    ],
    "permissions": [
        {
            "name": "idx_permissions_role_resource",
            "keys": [("role", 1), ("resource", 1), ("action", 1)],
            "desc": "按角色判定资源权限（鉴权热路径）",
        },
    ],
    "admin_tokens": [
        {
            "name": "idx_tokens_token_expires",
            "keys": [("token", 1), ("expires_at", 1)],
            "desc": "按 token 查找 + 过期校验（鉴权热路径）",
        },
        {
            "name": "idx_tokens_admin_created",
            "keys": [("admin_id", 1), ("created_at", -1)],
            "desc": "管理端会话列表 / 清理",
        },
    ],
    "document_jobs": [
        {
            "name": "idx_jobs_tenant_status",
            "keys": [("tenant_id", 1), ("status", 1), ("created_at", -1)],
            "desc": "文档解析任务列表 + 状态过滤",
        },
    ],
    "knowledge_graph_nodes": [
        {
            "name": "idx_kgnodes_tenant_type",
            "keys": [("tenant_id", 1), ("type", 1)],
            "desc": "按租户 + 节点类型查询知识图谱",
        },
    ],
}


def suggested_index_specs(collection: str) -> List[Dict[str, Any]]:
    """返回某 collection 的建议索引规格（可直接传给 create_indexes）。"""
    specs = []
    for item in SUGGESTED_INDEXES.get(collection, []):
        specs.append(
            {
                "key": [(k, d) for k, d in item["keys"]],
                "name": item["name"],
            }
        )
    return specs


def existing_index_names(db: Any) -> Dict[str, List[str]]:
    """列出每个 collection 现有索引名（不含 _id_）。"""
    out: Dict[str, List[str]] = {}
    try:
        names = db.list_collection_names()
    except Exception as exc:
        print(f"[index_advisor] list_collection_names failed: {exc}", file=sys.stderr)
        return out
    for name in sorted(names or []):
        try:
            infos = db[name].index_information()
        except Exception:
            infos = {}
        out[name] = sorted(str(k) for k in (infos or {}).keys() if k != "_id_")
    return out


def plan_diffs(existing: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """对比建议索引与现有索引，返回缺失项。"""
    diffs = []
    for collection, specs in SUGGESTED_INDEXES.items():
        present = set(existing.get(collection, []))
        for item in specs:
            if item["name"] not in present:
                diffs.append(
                    {
                        "collection": collection,
                        "name": item["name"],
                        "keys": [(k, d) for k, d in item["keys"]],
                        "desc": item["desc"],
                    }
                )
    return diffs


async def apply_indexes(db: Any, collection: str) -> Dict[str, Any]:
    """为指定 collection 建缺失索引（FR-8）。"""
    specs = suggested_index_specs(collection)
    existing = await db[collection].index_information()
    created = []
    for spec in specs:
        if spec["name"] in existing:
            continue
        await db[collection].create_index(spec["key"], name=spec["name"])
        created.append(spec["name"])
    return {"collection": collection, "created": created, "already": [s["name"] for s in specs if s["name"] in existing]}


async def coverage_report(db: Any, sample_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """对建议索引的典型查询跑 explain，统计索引使用率。

    用 ``$regex`` 探测每个集合第一条文档作为过滤条件模板；索引覆盖判定：
    ``totalDocsExamined <= nReturned``（或 nReturned == 0 时 totalDocsExamined == 0）。
    """
    filters = sample_filters or {}
    out: List[Dict[str, Any]] = []
    for collection, specs in SUGGESTED_INDEXES.items():
        for item in specs:
            # 以建议索引的等值前缀作为查询过滤
            prefix = [(k, d) for k, d in item["keys"] if d == 1]
            query = {}
            for key, _ in prefix[:1]:  # 只取首个等值键做样本
                sample = filters.get(collection, {}).get(key)
                if sample is None:
                    continue
                query[key] = sample
            if not query:
                out.append({"collection": collection, "index": item["name"], "status": "no-sample"})
                continue
            try:
                result = await db[collection].find(query).explain(verbosity="executionStats")
            except Exception as exc:
                out.append({"collection": collection, "index": item["name"], "status": f"error:{exc}"})
                continue
            stats = ((result or {}).get("executionStats") or {})
            n_returned = int(stats.get("nReturned") or 0)
            docs_examined = int(stats.get("totalDocsExamined") or 0)
            out.append(
                {
                    "collection": collection,
                    "index": item["name"],
                    "status": "covered" if docs_examined <= n_returned else "not-covered",
                    "nReturned": n_returned,
                    "totalDocsExamined": docs_examined,
                    "totalKeysExamined": int(stats.get("totalKeysExamined") or 0),
                }
            )
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="026 T018 索引策略助手")
    parser.add_argument("action", choices=["suggest", "apply", "coverage"], default="suggest", nargs="?")
    parser.add_argument("--collection", default=None, help="仅处理指定 collection")
    parser.add_argument("--uri", default=os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/mogo_dev"))
    args = parser.parse_args(argv)

    collections = [args.collection] if args.collection else list(SUGGESTED_INDEXES.keys())

    if args.action == "suggest":
        for collection in collections:
            for item in SUGGESTED_INDEXES.get(collection, []):
                keys = ", ".join(f"{k}:{d}" for k, d in item["keys"])
                print(f"{collection}.{item['name']:35s} ({keys})  # {item['desc']}")
        return 0

    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run() -> int:
        client = AsyncIOMotorClient(args.uri, serverSelectionTimeoutMS=3000)
        db = client[args.uri.split("/")[-1].split("?")[0] or "mogo_dev"]
        if args.action == "apply":
            for collection in collections:
                info = await apply_indexes(db, collection)
                print(f"[{collection}] created={info['created']} already={info['already']}")
        else:  # coverage
            for row in await coverage_report(db):
                print(row)
        client.close()
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())