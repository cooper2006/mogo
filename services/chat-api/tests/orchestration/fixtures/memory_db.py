"""In-memory mongo-shaped database for orchestration unit tests (050).

Implements the subset of the motor API that ``RunStore`` / ``RunDriver`` use:
``insert_one`` / ``find_one`` / ``find`` / ``update_one`` (with ``$set`` /
``$inc`` / ``$push`` / ``$unset``, ``upsert``) / ``find_one_and_update`` /
``delete_many``, plus ``$exists`` and ``$or`` query clauses and dotted
``pending_approvals.<node>`` keys.

Kept in ``fixtures/`` so multiple test modules share one faithful fake instead
of each re-implementing subtly different semantics.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _get_path(doc: dict, path: str) -> Any:
    current: Any = doc
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_path(doc: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    current = doc
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _unset_path(doc: dict, path: str) -> None:
    parts = path.split(".")
    current = doc
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _match(doc: dict, scope: dict) -> bool:
    for key, value in scope.items():
        if key == "$or":
            if not any(all(_match(doc, {k: v}) for k, v in clause.items()) for clause in value):
                return False
            continue
        if isinstance(value, dict) and set(value.keys()) == {"$exists"}:
            present = _get_path(doc, key) is not None
            if present != bool(value["$exists"]):
                return False
            continue
        if isinstance(value, dict) and "$in" in value:
            if _get_path(doc, key) not in value["$in"]:
                return False
            continue
        if isinstance(value, dict) and "$lt" in value:
            current = _get_path(doc, key)
            if current is None:
                return False
            try:
                if current >= value["$lt"]:
                    return False
            except TypeError:
                return False  # 类型不同（如 str vs datetime）→ 不匹配
            continue
        if _get_path(doc, key) != value:
            return False
    return True


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def _find(self, scope: dict) -> list[dict]:
        return [d for d in self.docs if _match(d, scope)]

    async def insert_one(self, doc: dict) -> None:
        self.docs.append(dict(doc))

    async def find_one(self, scope: dict):
        return next((d for d in self._find(scope)), None)

    def find(self, scope: dict) -> _Cursor:
        return _Cursor(self._find(scope))

    async def update_one(self, scope: dict, update: dict, upsert: bool = False):
        doc = next((d for d in self._find(scope)), None)
        if doc is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            doc = dict(scope)
            for key, value in (update.get("$setOnInsert") or {}).items():
                _set_path(doc, key, value)
            self.docs.append(doc)
        for key, value in (update.get("$set") or {}).items():
            _set_path(doc, key, value)
        for key, amount in (update.get("$inc") or {}).items():
            _set_path(doc, key, int(_get_path(doc, key) or 0) + amount)
        for key, value in (update.get("$push") or {}).items():
            holder = doc.setdefault(key, [])
            holder.append(value)
        for key in (update.get("$unset") or {}):
            _unset_path(doc, key)
        return SimpleNamespace(matched_count=1)

    async def find_one_and_update(self, scope: dict, update: dict, return_document: bool = True):
        import copy

        doc = next((d for d in self._find(scope)), None)
        if doc is None:
            return None
        snapshot = copy.deepcopy(doc)
        await self.update_one(scope, update)
        return snapshot

    async def delete_many(self, scope: dict):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, scope)]
        return SimpleNamespace(deleted_count=before - len(self.docs))


class FakeDatabase:
    """One collection per name; ``__getitem__`` mirrors a motor database."""

    def __init__(self, *collections: str) -> None:
        for name in collections:
            setattr(self, name, FakeCollection())
        self.orchestration_runs = getattr(self, "orchestration_runs", None) or FakeCollection()
        self.end_users = getattr(self, "end_users", None) or FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        return getattr(self, name, None) or getattr(self, name, FakeCollection())