"""写入路径的 32-hex 主键注入（阶段 2 终态）。

MongoDB driver 在文档缺少 ``_id`` 时会自动补一个 ``ObjectId``，与终态
「只认 32-hex」冲突。与其改 150+ 个 ``insert_one`` / ``upsert`` 调用点，这里
在 :func:`app.core.db.get_db` 的返回句柄外包一层轻量门面，对**所有写路径**
统一注入 :func:`app.core.ids.new_backend_id`：

* ``insert_one`` / ``insert_many``
* ``replace_one(upsert=True)``（replacement 文档补 ``_id``）
* ``update_one`` / ``update_many`` / ``find_one_and_update``（upsert 时补
  ``$setOnInsert._id``）
* ``find_one_and_replace(upsert=True)``
* ``bulk_write``（pymongo 操作对象与 ``batch_prefetch`` 的 dict 形态都覆盖）

读路径（``find`` / ``aggregate`` / ``count_documents`` / ``create_index`` …）
原样透传。PanWeiDB 兼容门面自己有 ``new_backend_id``，不走这里。

见 ``docs/id-unification-hex32-runbook.md``。
"""

from __future__ import annotations

from typing import Any

from app.core.ids import new_backend_id

__all__ = [
    "Hex32Database",
    "AsyncHex32Collection",
    "SyncHex32Collection",
]


# ── 注入 helper ────────────────────────────────────────────────────────────
def _derived_id_from_filter(flt: Any) -> Any:
    """从 upsert 的 filter 中推导 ``_id``（仅标量可推导）。"""
    if not isinstance(flt, dict):
        return None
    for key, value in flt.items():
        if key == "_id" and value is not None and not isinstance(value, (dict, list)):
            return value
        if key == "$and" and isinstance(value, list):
            for sub in value:
                derived = _derived_id_from_filter(sub)
                if derived is not None:
                    return derived
    return None


def _ensure_insert_id(doc: Any) -> None:
    if isinstance(doc, dict) and "_id" not in doc:
        doc["_id"] = new_backend_id()


def _ensure_replacement(doc: Any, flt: Any) -> None:
    if not isinstance(doc, dict) or "_id" in doc:
        return
    derived = _derived_id_from_filter(flt)
    doc["_id"] = derived if derived is not None else new_backend_id()


def _ensure_upsert_update(update: Any, flt: Any) -> None:
    if not isinstance(update, dict):
        return
    derived = _derived_id_from_filter(flt)
    if not any(str(key).startswith("$") for key in update):
        # 非 operator 文档 = 整体替换语义
        _ensure_replacement(update, flt)
        return
    if isinstance(update.get("$set"), dict) and "_id" in update["$set"]:
        return
    soi = update.get("$setOnInsert")
    if not isinstance(soi, dict):
        update["$setOnInsert"] = soi = {}
    if "_id" not in soi:
        soi["_id"] = derived if derived is not None else new_backend_id()


def _prepare_bulk(requests: Any) -> None:
    """对 bulk_write 请求注入 _id，支持 pymongo 操作对象与 dict 描述。"""
    for op in requests or ():
        if isinstance(op, dict) and "op" in op:
            kind = str(op.get("op") or "")
            if kind == "insert":
                _ensure_insert_id(op.get("doc"))
            elif kind in {"update", "upsert"} and op.get("upsert"):
                _ensure_upsert_update(op.get("update"), op.get("filter"))
            continue
        kind = type(op).__name__
        doc = getattr(op, "_doc", None)
        flt = getattr(op, "_filter", None)
        upsert = bool(getattr(op, "_upsert", False))
        if kind == "InsertOne":
            _ensure_insert_id(doc)
        elif kind == "ReplaceOne" and upsert:
            _ensure_replacement(doc, flt)
        elif kind in {"UpdateOne", "UpdateMany"} and upsert:
            _ensure_upsert_update(doc, flt)


class _CollectionBase:
    """透传读路径与非写入属性；子类只覆盖写方法。"""

    __slots__ = ("_coll",)

    def __init__(self, coll: Any) -> None:
        object.__setattr__(self, "_coll", coll)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_coll"), name)


class AsyncHex32Collection(_CollectionBase):
    """motor（异步）集合门面。"""

    async def insert_one(self, document: Any, *args: Any, **kwargs: Any) -> Any:
        _ensure_insert_id(document)
        return await self._coll.insert_one(document, *args, **kwargs)

    async def insert_many(self, documents: Any, *args: Any, **kwargs: Any) -> Any:
        for doc in documents or ():
            _ensure_insert_id(doc)
        return await self._coll.insert_many(documents, *args, **kwargs)

    async def replace_one(self, flt: Any, replacement: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_replacement(replacement, flt)
        return await self._coll.replace_one(flt, replacement, *args, **kwargs)

    async def update_one(self, flt: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_upsert_update(update, flt)
        return await self._coll.update_one(flt, update, *args, **kwargs)

    async def update_many(self, flt: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_upsert_update(update, flt)
        return await self._coll.update_many(flt, update, *args, **kwargs)

    async def find_one_and_update(self, flt: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_upsert_update(update, flt)
        return await self._coll.find_one_and_update(flt, update, *args, **kwargs)

    async def find_one_and_replace(self, flt: Any, replacement: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_replacement(replacement, flt)
        return await self._coll.find_one_and_replace(flt, replacement, *args, **kwargs)

    async def bulk_write(self, requests: Any, *args: Any, **kwargs: Any) -> Any:
        _prepare_bulk(requests)
        return await self._coll.bulk_write(requests, *args, **kwargs)


class SyncHex32Collection(_CollectionBase):
    """pymongo（同步）集合门面，document-parser 使用。"""

    def insert_one(self, document: Any, *args: Any, **kwargs: Any) -> Any:
        _ensure_insert_id(document)
        return self._coll.insert_one(document, *args, **kwargs)

    def insert_many(self, documents: Any, *args: Any, **kwargs: Any) -> Any:
        for doc in documents or ():
            _ensure_insert_id(doc)
        return self._coll.insert_many(documents, *args, **kwargs)

    def replace_one(self, flt: Any, replacement: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_replacement(replacement, flt)
        return self._coll.replace_one(flt, replacement, *args, **kwargs)

    def update_one(self, flt: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_upsert_update(update, flt)
        return self._coll.update_one(flt, update, *args, **kwargs)

    def update_many(self, flt: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_upsert_update(update, flt)
        return self._coll.update_many(flt, update, *args, **kwargs)

    def find_one_and_update(self, flt: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_upsert_update(update, flt)
        return self._coll.find_one_and_update(flt, update, *args, **kwargs)

    def find_one_and_replace(self, flt: Any, replacement: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("upsert"):
            _ensure_replacement(replacement, flt)
        return self._coll.find_one_and_replace(flt, replacement, *args, **kwargs)

    def bulk_write(self, requests: Any, *args: Any, **kwargs: Any) -> Any:
        _prepare_bulk(requests)
        return self._coll.bulk_write(requests, *args, **kwargs)


class Hex32Database:
    """``db[coll]`` / ``db.coll`` / ``db.get_collection()`` 全部返回注入门面。"""

    __slots__ = ("_db", "_cls")

    def __init__(self, db: Any, collection_cls: type) -> None:
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_cls", collection_cls)

    def __getitem__(self, name: str) -> Any:
        return object.__getattribute__(self, "_cls")(
            object.__getattribute__(self, "_db")[name]
        )

    def __getattr__(self, name: str) -> Any:
        db = object.__getattribute__(self, "_db")
        attr = getattr(db, name)
        if hasattr(attr, "insert_one") and hasattr(attr, "find"):
            return object.__getattribute__(self, "_cls")(attr)
        return attr

    def get_collection(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return object.__getattribute__(self, "_cls")(
            object.__getattribute__(self, "_db").get_collection(name, *args, **kwargs)
        )
