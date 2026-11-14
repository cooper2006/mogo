"""026 T020/T021 — 批量预取 / 批量写入 helper（FR-7/FR-12）。

用于把「循环内单点查询 / 单条写入」改为批量：

* ``prefetch_many``：一次 ``find({field: {$in: ids}})`` 拉回所有目标文档，
  再按 id 建索引字典，替代循环 ``find_one``（N+1 → 1 次查询）。
* ``prefetch_many_async``：motor collection 版本（异步）。
* ``bulk_upsert`` / ``bulk_insert``：把循环 ``insert_one`` / ``update_one``
  合并为单次 ``bulk_write``（有序批量）。

本模块自包含（stdlib + typing），便于 vendored 副本独立校验。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

# bulk_write 操作类型（有序，保证顺序语义）
BULK_UPSERT = "upsert"      # {"op": "upsert", "filter": ..., "update": ..., "upsert": bool}
BULK_INSERT = "insert"      # {"op": "insert", "doc": ...}
BULK_UPDATE = "update"      # {"op": "update", "filter": ..., "update": ...}
BULK_DELETE = "delete"      # {"op": "delete", "filter": ...}


def index_by(docs: Iterable[Mapping[str, Any]], field: str = "_id") -> Dict[str, Mapping[str, Any]]:
    """把文档列表按 field 建字典（重复保留最后一个）。"""
    out: Dict[str, Mapping[str, Any]] = {}
    for doc in docs or ():
        key = doc.get(field)
        if key is None:
            continue
        out[str(key)] = doc
    return out


def prefetch_many(docs, field: str, ids: Sequence[str]) -> Dict[str, Any]:
    """把单次批量查询结果按 id 建索引。

    ``docs`` 是一次 ``collection.find({field: {"$in": list(ids)}})`` 的结果；
    返回 ``{str(id): doc}``，供循环内 ``by_id.get(str(x))`` 替代 ``find_one``。
    """
    if not ids:
        return {}
    return index_by(docs or [], field)


async def prefetch_many_async(collection, field: str, ids: Sequence[str]) -> Dict[str, Any]:
    """异步版：motor collection 一次 find 批量预取。"""
    if not ids:
        return {}
    id_list = list(ids)
    cursor = collection.find({field: {"$in": id_list}})
    docs = [doc async for doc in cursor]
    return index_by(docs, field)


def build_bulk_write(operations: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """把操作描述转换成 pymongo ``bulk_write`` 请求（有序）。

    每个操作描述形如 ``{"op": "upsert", "filter": ..., "update": ...}``。
    """
    requests: List[Dict[str, Any]] = []
    for op in operations or ():
        kind = op.get("op")
        if kind == BULK_INSERT:
            requests.append({"op": "insert", "doc": op["doc"]})
        elif kind == BULK_UPDATE:
            req: Dict[str, Any] = {"op": "update", "filter": op["filter"], "update": op["update"]}
            if "upsert" in op:
                req["upsert"] = bool(op["upsert"])
            requests.append(req)
        elif kind == BULK_DELETE:
            requests.append({"op": "delete", "filter": op["filter"]})
        else:
            raise ValueError(f"unknown bulk op: {kind!r}")
    return requests


def chunked(items: Sequence[Any], size: int = 500) -> Iterable[List[Any]]:
    """把序列切块（默认 500），避免单次 bulk_write 过大。"""
    for i in range(0, len(items or ()), size):
        yield list(items[i : i + size])


__all__ = [
    "index_by",
    "prefetch_many",
    "prefetch_many_async",
    "build_bulk_write",
    "chunked",
    "BULK_UPSERT",
    "BULK_INSERT",
    "BULK_UPDATE",
    "BULK_DELETE",
]