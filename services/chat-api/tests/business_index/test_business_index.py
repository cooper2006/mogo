"""Tests for the business semantic index core (feature 014): entities / sources."""

from __future__ import annotations

import pytest

from app.business_index.entities import (
    ALIGNMENT_KEYS,
    ENTITY_TYPES,
    BizEntity,
    EntityError,
    align_pair,
)
from app.business_index.sources import (
    DEFAULT_PULL_INTERVAL,
    SourceSpec,
    SourceStatus,
    build_unavailable_notice,
    is_source_unavailable,
    mask_pii_fields,
)


# --- entity model ------------------------------------------------------------

def test_entity_types_are_the_four() -> None:
    assert ENTITY_TYPES == ("customer", "order", "supplier", "account")


def test_alignment_keys_defined_per_type() -> None:
    assert ALIGNMENT_KEYS["customer"] == "customer_code"
    assert ALIGNMENT_KEYS["order"] == "order_no"


def test_entity_requires_known_type_and_source() -> None:
    with pytest.raises(EntityError):
        BizEntity(entity_type="alien", source_system="crm", record_id="1")
    with pytest.raises(EntityError):
        BizEntity(entity_type="customer", source_system="", record_id="1")
    with pytest.raises(EntityError):
        BizEntity(entity_type="customer", source_system="crm", record_id="")


def test_source_attribution_is_three_levels() -> None:
    entity = BizEntity(entity_type="customer", source_system="crm", record_id="c-1")
    assert entity.source_attribution() == {
        "sourceSystem": "crm",
        "entityType": "customer",
        "recordId": "c-1",
    }


def test_align_key_reads_business_key() -> None:
    entity = BizEntity(
        entity_type="customer",
        source_system="crm",
        record_id="c-1",
        fields={"customer_code": "C-100"},
    )
    assert entity.align_key() == "C-100"


def test_align_key_missing_returns_none() -> None:
    entity = BizEntity(entity_type="customer", source_system="crm", record_id="c-1")
    assert entity.align_key() is None


def test_align_pair_matching_keys() -> None:
    left = BizEntity("customer", "crm", "1", {"customer_code": "C-1"})
    right = BizEntity("customer", "finance", "f1", {"customer_code": "C-1"})
    assert align_pair(left, right) is True
    assert left.aligned and right.aligned


def test_align_pair_mismatch_marks_unaligned_not_refused() -> None:
    left = BizEntity("customer", "crm", "1", {"customer_code": "C-1"})
    right = BizEntity("customer", "finance", "f1", {"customer_code": "C-2"})
    assert align_pair(left, right) is False
    assert left.aligned is False and right.aligned is False


def test_align_pair_different_types_unaligned() -> None:
    left = BizEntity("customer", "crm", "1", {"customer_code": "C-1"})
    right = BizEntity("order", "crm", "2", {"order_no": "C-1"})
    assert align_pair(left, right) is False


# --- sources -----------------------------------------------------------------

def test_source_spec_must_be_read_only() -> None:
    with pytest.raises(ValueError):
        SourceSpec(name="crm", read_only=False)


def test_source_spec_rejects_bad_interval() -> None:
    with pytest.raises(ValueError):
        SourceSpec(name="crm", interval="hourly")


def test_source_spec_defaults_to_daily_readonly() -> None:
    spec = SourceSpec(name="crm")
    assert spec.interval == DEFAULT_PULL_INTERVAL
    assert spec.read_only is True


def test_source_status_unavailable_detection() -> None:
    assert is_source_unavailable(SourceStatus.UNAVAILABLE.value) is True
    assert is_source_unavailable(SourceStatus.AVAILABLE.value) is False


def test_unavailable_notice_labels_source() -> None:
    notice = build_unavailable_notice("crm")
    assert notice["status"] == "unavailable"
    assert "crm" in notice["message"]


# --- PII masking -------------------------------------------------------------

def test_mask_pii_fields_masks_sensitive() -> None:
    masked = mask_pii_fields({"name": "Acme", "phone": "13800000000"})
    assert masked["name"] == "Acme"
    assert masked["phone"] == "***"


def test_mask_pii_hash_is_deterministic_and_not_plaintext() -> None:
    first = mask_pii_fields({"id_card": "110101199001011234"}, strategy="hash")
    second = mask_pii_fields({"id_card": "110101199001011234"}, strategy="hash")
    assert first["id_card"] == second["id_card"]
    assert "1101" not in first["id_card"]


def test_mask_pii_remove_drops_field() -> None:
    masked = mask_pii_fields({"email": "a@b.com", "name": "x"}, strategy="remove")
    assert "email" not in masked
    assert masked["name"] == "x"


# --- alignment (T010) --------------------------------------------------------

def test_align_groups_same_key_across_systems() -> None:
    from app.business_index.alignment import align_entities

    entities = [
        BizEntity("customer", "crm", "1", {"customer_code": "C-1"}),
        BizEntity("customer", "finance", "f1", {"customer_code": "C-1"}),
    ]
    report = align_entities(entities)
    assert len(report.groups) == 1
    assert report.groups[0].is_cross_system is True
    assert report.groups[0].systems == ["crm", "finance"]


def test_align_reports_missing_key_as_unaligned() -> None:
    from app.business_index.alignment import align_entities

    report = align_entities([BizEntity("customer", "crm", "1", {})])
    assert len(report.unaligned) == 1
    assert report.unaligned[0].aligned is False


def test_align_separates_different_keys() -> None:
    from app.business_index.alignment import align_entities

    report = align_entities(
        [
            BizEntity("customer", "crm", "1", {"customer_code": "C-1"}),
            BizEntity("customer", "crm", "2", {"customer_code": "C-2"}),
        ]
    )
    assert len(report.groups) == 2


def test_missing_systems_reported() -> None:
    from app.business_index.alignment import align_entities, missing_systems

    report = align_entities([BizEntity("customer", "crm", "1", {"customer_code": "C-1"})])
    missing = missing_systems(report.groups[0], expected_systems=["crm", "finance"])
    assert missing == ["finance"]


def test_join_cross_system_labels_missing_systems() -> None:
    from app.business_index.alignment import align_entities, join_cross_system

    report = align_entities([BizEntity("customer", "crm", "1", {"customer_code": "C-1"})])
    joined = join_cross_system(report, expected_systems=["crm", "finance"])
    assert joined[0]["systems"] == ["crm"]
    assert joined[0]["missingSystems"] == ["finance"]
    assert joined[0]["crossSystem"] is False
