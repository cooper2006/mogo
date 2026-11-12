"""059 T009 — ontology 权限 fail-closed：enforce=False → 默认 deny / 空可见集。

* ``resolve_visible_ontologies`` 无主体/无授权 → 空集合（fail-closed）；
* 已禁用（enabled=0）的授权行被排除；
* ``OntologyPermissionService.get_config()`` 在 ``enforce=False`` 时
  ``effectiveDefault == "deny"``，开启时跟随 ``defaultMode``。
"""

from __future__ import annotations

import pytest

from app.ontology_permission.service import (
    OntologyPermissionService,
    resolve_visible_ontologies,
)


class _FakeRepo:
    def __init__(self, cfg) -> None:
        self._cfg = cfg

    async def get_sys_config(self, key):
        return self._cfg


def test_resolve_visible_empty_for_no_grants() -> None:
    assert resolve_visible_ontologies([], []) == frozenset()


def test_resolve_visible_excludes_disabled() -> None:
    subjects = {("user", "u1")}
    rows = [
        {
            "subject_type": "user",
            "subject_id": "u1",
            "ontology_uri": "onto:a",
            "access_mode": "read",
            "priority": 100,
            "enabled": 0,
        }
    ]
    assert resolve_visible_ontologies(subjects, rows) == frozenset()


@pytest.mark.asyncio
async def test_enforce_false_effective_default_deny() -> None:
    svc = OntologyPermissionService(
        repository=_FakeRepo({"enforce": False, "defaultMode": "allow"})
    )
    cfg = await svc.get_config()
    assert cfg["enforce"] is False
    assert cfg["effectiveDefault"] == "deny"


@pytest.mark.asyncio
async def test_enforce_true_effective_default_follows_mode() -> None:
    svc = OntologyPermissionService(
        repository=_FakeRepo({"enforce": True, "defaultMode": "allow"})
    )
    cfg = await svc.get_config()
    assert cfg["enforce"] is True
    assert cfg["effectiveDefault"] == "allow"
