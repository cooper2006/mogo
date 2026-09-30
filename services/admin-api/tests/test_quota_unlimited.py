"""Tests for decision 12 (Phase 6 / T033–T035): quota defaults to unlimited.

``unlimited`` short-circuits both metering paths so a brand-new tenant can be
created with zero quota configuration and still be usable. Uses an in-memory
fake of ``get_db``; no MongoDB required.
"""

from __future__ import annotations

import asyncio

from app.core import quota_policy


def _matches(doc: dict, flt: dict | None) -> bool:
    if not flt:
        return True
    for key, value in flt.items():
        if doc.get(key) != value:
            return False
    return True


class _MemCol:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def find_one(self, flt, *args, **kwargs):
        for doc in self.docs:
            if _matches(doc, flt):
                return dict(doc)
        return None

    async def update_one(self, flt, update, upsert=False):
        for doc in self.docs:
            if _matches(doc, flt):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            new_doc = dict(flt)
            new_doc.update(update.get("$setOnInsert", {}))
            new_doc.update(update.get("$set", {}))
            self.docs.append(new_doc)

    def aggregate(self, pipeline):
        # Only the ``sum_usage`` shape is exercised: match then sum a field.
        # The production call is ``await col.aggregate([...]).to_list(1)``, so
        # ``aggregate`` must be a *plain* function returning an object whose
        # ``to_list`` is awaitable -- exactly like Motor's cursor.
        match = next((stage["$match"] for stage in pipeline if "$match" in stage), {})
        group = next((stage["$group"] for stage in pipeline if "$group" in stage), {})
        field = str((group.get("tokens") or {}).get("$ifNull", ["", 0])[0]).lstrip("$")
        total = 0
        for doc in self.docs:
            if not _matches(doc, match):
                continue
            created = doc.get("created_at")
            window = match.get("created_at")
            if window and created is not None:
                if "$gte" in window and created < window["$gte"]:
                    continue
                if "$lt" in window and created >= window["$lt"]:
                    continue
            total += int(doc.get(field) or 0)

        class _Cursor:
            async def to_list(self, length=None):
                return [{"_id": None, "tokens": total}] if total else []

        return _Cursor()


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def _patch(monkeypatch, mem: _Mem) -> None:
    monkeypatch.setattr(quota_policy, "get_db", lambda: mem)


# ---------------------------------------------------------------------------
# ensure_org_quota_policy
# ---------------------------------------------------------------------------


def test_new_org_policy_defaults_to_unlimited(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)

    policy = asyncio.run(quota_policy.ensure_org_quota_policy("acme-1a2b3c4d5e6f7a8b9c0d1e2f"))

    # decision 12: a tenant created with no quota config is not capped.
    assert policy["unlimited"] is True
    assert policy["total_tokens"] == 0
    assert policy["status"] == "active"


def test_existing_org_policy_is_not_overwritten(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["org_quota_policies"].docs.append({"main_id": main_id, "total_tokens": 500, "unlimited": False})

    policy = asyncio.run(quota_policy.ensure_org_quota_policy(main_id))

    assert policy["unlimited"] is False
    assert policy["total_tokens"] == 500


# ---------------------------------------------------------------------------
# get_quota_summary — enterprise path
# ---------------------------------------------------------------------------


def _enterprise_user() -> dict:
    return {"_id": "u1", "space_type": "enterprise", "org_name": "Acme"}


def test_enterprise_summary_is_unlimited_by_default(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["organizations"].docs.append({"main_id": main_id, "org_name": "Acme"})
    # No quota config at all — the zero-config tenant must still work.

    summary = asyncio.run(quota_policy.get_quota_summary(main_id, _enterprise_user()))

    assert summary["unlimited"] is True
    assert summary["remainingPoints"] == -1
    assert summary["totalPoints"] == -1


def test_legacy_enterprise_row_without_flag_is_limited(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["organizations"].docs.append({"main_id": main_id, "org_name": "Acme"})
    mem["org_quota_policies"].docs.append({"main_id": main_id, "total_tokens": 100, "status": "active"})

    summary = asyncio.run(quota_policy.get_quota_summary(main_id, _enterprise_user()))

    # Backward compatible: a row without ``unlimited`` keeps enforcing its cap.
    assert summary["unlimited"] is False
    assert summary["orgRemainingPoints"] == 100


def test_explicitly_limited_enterprise_reports_remaining(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["organizations"].docs.append({"main_id": main_id, "org_name": "Acme"})
    mem["org_quota_policies"].docs.append({"main_id": main_id, "total_tokens": 100, "unlimited": False, "status": "active"})
    mem["user_quota_policies"].docs.append(
        {"main_id": main_id, "scope_type": "user", "scope_id": "u1", "quota_tokens": 40, "status": "active"}
    )

    summary = asyncio.run(quota_policy.get_quota_summary(main_id, _enterprise_user()))

    assert summary["unlimited"] is False
    assert summary["orgRemainingPoints"] == 100


# ---------------------------------------------------------------------------
# get_quota_summary — personal path
# ---------------------------------------------------------------------------


def test_personal_summary_defaults_to_unlimited(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["organizations"].docs.append({"main_id": main_id, "org_name": "个人空间"})

    summary = asyncio.run(quota_policy.get_quota_summary(main_id, {"_id": "u1", "space_type": "personal"}))

    assert summary["spaceType"] == "personal"
    assert summary["unlimited"] is True
    assert summary["remainingPoints"] == -1


def test_personal_summary_respects_explicit_limit(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["organizations"].docs.append(
        {"main_id": main_id, "org_name": "个人空间", "total_points": 200, "used_points": 50, "points_unlimited": False}
    )

    summary = asyncio.run(quota_policy.get_quota_summary(main_id, {"_id": "u1", "space_type": "personal"}))

    assert summary["unlimited"] is False
    assert summary["remainingPoints"] == 150


# ---------------------------------------------------------------------------
# assert_quota_available — T035 short-circuit
# ---------------------------------------------------------------------------


def test_unlimited_personal_user_is_not_blocked_when_used_exceeds_total(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    # Used well past a zero total: without the flag this would raise.
    mem["organizations"].docs.append(
        {"main_id": main_id, "org_name": "个人空间", "total_points": 0, "used_points": 9999, "points_unlimited": True}
    )

    summary = asyncio.run(quota_policy.assert_quota_available(main_id, {"_id": "u1", "space_type": "personal"}))

    assert summary["unlimited"] is True


def test_limited_personal_user_is_blocked_when_exhausted(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    main_id = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"
    mem["organizations"].docs.append(
        {"main_id": main_id, "org_name": "个人空间", "total_points": 100, "used_points": 100, "points_unlimited": False}
    )

    try:
        asyncio.run(quota_policy.assert_quota_available(main_id, {"_id": "u1", "space_type": "personal"}))
    except quota_policy.QuotaExceededError as exc:
        assert "已用尽" in str(exc)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("expected QuotaExceededError for an exhausted limited space")
