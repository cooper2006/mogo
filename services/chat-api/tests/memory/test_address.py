"""Tests for 017 memory address space (FR-18)."""

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
    a = MemoryAddress("org", "u2", "m3").with_tier("L2")
    assert a.tier == "L2"
    assert a.uri().endswith("/L2")


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
