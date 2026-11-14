"""阶段 2：写入路径 32-hex 主键注入门面的单测（用 fake collection，不连库）。"""

from __future__ import annotations

import re

from bson import ObjectId
from pymongo import InsertOne, ReplaceOne, UpdateOne

from app.core.hex32_db import (
    Hex32Database,
    SyncHex32Collection,
    _ensure_insert_id,
    _ensure_replacement,
    _ensure_upsert_update,
    _prepare_bulk,
)

HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class FakeCollection:
    def __init__(self, name: str = "coll") -> None:
        self.name = name
        self.calls: list[tuple] = []

    def insert_one(self, doc, *args, **kwargs):
        self.calls.append(("insert_one", doc))
        return doc

    def insert_many(self, docs, *args, **kwargs):
        self.calls.append(("insert_many", docs))
        return docs

    def replace_one(self, flt, replacement, *args, **kwargs):
        self.calls.append(("replace_one", flt, replacement, kwargs))
        return None

    def update_one(self, flt, update, *args, **kwargs):
        self.calls.append(("update_one", flt, update, kwargs))
        return None

    def update_many(self, flt, update, *args, **kwargs):
        self.calls.append(("update_many", flt, update, kwargs))
        return None

    def find_one_and_update(self, flt, update, *args, **kwargs):
        self.calls.append(("find_one_and_update", flt, update, kwargs))
        return None

    def find_one_and_replace(self, flt, replacement, *args, **kwargs):
        self.calls.append(("find_one_and_replace", flt, replacement, kwargs))
        return None

    def bulk_write(self, requests, *args, **kwargs):
        self.calls.append(("bulk_write", requests))
        return None

    def find(self, *args, **kwargs):
        return []


class FakeDatabase:
    def __init__(self) -> None:
        self.coll = FakeCollection()

    def __getitem__(self, name):
        return self.coll

    def __getattr__(self, name):
        return self.coll

    def get_collection(self, name, *args, **kwargs):
        return self.coll


def test_insert_one_injects_hex32():
    doc = {"name": "x"}
    _ensure_insert_id(doc)
    assert HEX32_RE.match(doc["_id"])


def test_insert_one_preserves_explicit_id():
    doc = {"_id": "singleton", "name": "x"}
    _ensure_insert_id(doc)
    assert doc["_id"] == "singleton"


def test_insert_many_injects_each():
    coll = SyncHex32Collection(FakeCollection())
    docs = [{"a": 1}, {"b": 2}]
    coll.insert_many(docs)
    assert all(HEX32_RE.match(d["_id"]) for d in docs)
    assert docs[0]["_id"] != docs[1]["_id"]


def test_upsert_update_injects_set_on_insert():
    update = {"$set": {"status": "ok"}}
    _ensure_upsert_update(update, {"event_id": "e-1"})
    assert HEX32_RE.match(update["$setOnInsert"]["_id"])


def test_upsert_update_uses_filter_id_when_present():
    update = {"$setOnInsert": {"status": "ok"}}
    _ensure_upsert_update(update, {"_id": "singleton"})
    assert update["$setOnInsert"]["_id"] == "singleton"


def test_upsert_update_does_not_override_existing_set_on_insert_id():
    update = {"$setOnInsert": {"_id": HEX32_SAMPLE}}
    _ensure_upsert_update(update, {"event_id": "e-1"})
    assert update["$setOnInsert"]["_id"] == HEX32_SAMPLE


def test_replace_upsert_uses_filter_id():
    doc = {"status": "ok"}
    _ensure_replacement(doc, {"_id": "singleton"})
    assert doc["_id"] == "singleton"


def test_replace_upsert_generates_id_without_filter_id():
    doc = {"status": "ok"}
    _ensure_replacement(doc, {"memory_id": "m1", "tenant_id": "default"})
    assert HEX32_RE.match(doc["_id"])


def test_update_one_wrapper_only_injects_on_upsert():
    coll = SyncHex32Collection(FakeCollection())
    plain = {"$set": {"a": 1}}
    coll.update_one({"_id": "x"}, plain, upsert=False)
    assert "$setOnInsert" not in plain
    upsert = {"$set": {"a": 1}}
    coll.update_one({"event_id": "e-1"}, upsert, upsert=True)
    assert HEX32_RE.match(upsert["$setOnInsert"]["_id"])


def test_prepare_bulk_pymongo_operations():
    insert = InsertOne({"event_id": "e-1"})
    update = UpdateOne({"event_id": "e-1"}, {"$setOnInsert": {"payload": 1}}, upsert=True)
    replace = ReplaceOne({"memory_id": "m1"}, {"status": "ok"}, upsert=True)
    _prepare_bulk([insert, update, replace])
    assert HEX32_RE.match(insert._doc["_id"])
    assert HEX32_RE.match(update._doc["$setOnInsert"]["_id"])
    assert HEX32_RE.match(replace._doc["_id"])


def test_prepare_bulk_dict_operations():
    ops = [
        {"op": "insert", "doc": {"a": 1}},
        {"op": "update", "filter": {"event_id": "e-2"}, "update": {"$set": {"a": 1}}, "upsert": True},
    ]
    _prepare_bulk(ops)
    assert HEX32_RE.match(ops[0]["doc"]["_id"])
    assert HEX32_RE.match(ops[1]["update"]["$setOnInsert"]["_id"])


def test_database_wrapper_wraps_all_access_paths():
    db = Hex32Database(FakeDatabase(), SyncHex32Collection)
    assert isinstance(db["coll"], SyncHex32Collection)
    assert isinstance(db.coll, SyncHex32Collection)
    assert isinstance(db.get_collection("coll"), SyncHex32Collection)
    # 读路径透传
    assert db.coll.name == "coll"


def test_no_objectid_is_ever_generated():
    """注入的 _id 必须是 str 32-hex，不能是驱动默认的 ObjectId。"""
    coll = SyncHex32Collection(FakeCollection())
    doc = {"a": 1}
    coll.insert_one(doc)
    assert isinstance(doc["_id"], str)
    assert not isinstance(doc["_id"], ObjectId)
    assert HEX32_RE.match(doc["_id"])


HEX32_SAMPLE = "3522820df01b484fa94a9706a5adea25"
