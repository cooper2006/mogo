"""Tests for 017 memory address space (FR-18).

D4: only ``personal`` / ``project`` / ``department`` are legal scope segments;
the retired ``workspace`` / ``org`` segments must be rejected.
"""

from __future__ import annotations

import pytest

from app.memory.address import MemoryAddress, parse_memory_uri


def test_uri_roundtrip() -> None:
    a = MemoryAddress("personal", "u1", "m1", "L1")
    assert parse_memory_uri(a.uri()) == a


def test_uri_default_tier() -> None:
    a = parse_memory_uri("mogo://memory/personal/u1/m1")
    assert a.tier == "L0"


def test_with_tier() -> None:
    a = MemoryAddress("department", "u2", "m3").with_tier("L2")
    assert a.tier == "L2"
    assert a.uri().endswith("/L2")


def test_project_and_department_addresses_are_legal() -> None:
    project = parse_memory_uri("mogo://memory/project/u1/m1/L1")
    assert project.scope == "project"
    assert parse_memory_uri(project.uri()) == project
    department = parse_memory_uri("mogo://memory/department/u2/m2/L2")
    assert department.scope == "department"
    assert parse_memory_uri(department.uri()) == department


@pytest.mark.parametrize("legacy_scope", ["workspace", "org"])
def test_legacy_scope_segments_are_rejected(legacy_scope: str) -> None:
    with pytest.raises(ValueError):
        parse_memory_uri(f"mogo://memory/{legacy_scope}/u1/m1/L0")
    # ``MemoryAddress.uri()`` does not validate, but parsing it back must.
    with pytest.raises(ValueError):
        parse_memory_uri(MemoryAddress(legacy_scope, "u1", "m1").uri())


def test_invalid_scheme() -> None:
    with pytest.raises(ValueError):
        parse_memory_uri("http://memory/personal/u1/m1")


def test_invalid_tier() -> None:
    with pytest.raises(ValueError):
        parse_memory_uri("mogo://memory/personal/u1/m1/L9")


def test_invalid_scope() -> None:
    with pytest.raises(ValueError):
        parse_memory_uri("mogo://memory/galaxy/u1/m1")


def test_url_safe_owner() -> None:
    a = MemoryAddress("personal", "u/1@x", "m1")
    parsed = parse_memory_uri(a.uri())
    assert parsed.owner_id == "u/1@x"
