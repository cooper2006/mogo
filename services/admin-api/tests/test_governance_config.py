"""Unit tests for declarative gate config (feature 001, T002)."""

import pytest

from app.governance.config import (
    CANONICAL_LAYER_ORDER,
    GateConfig,
    GateConfigError,
    config_from_document,
    default_config,
)


def test_default_config_is_thick_with_all_six_layers() -> None:
    config = default_config()
    assert config.layers_in_order() == list(CANONICAL_LAYER_ORDER)
    assert config.audit_enabled is True
    assert config.mode == "thick"


def test_layers_in_order_preserves_canonical_order() -> None:
    config = GateConfig(enabled_layers=["audit", "rbac", "identity"])
    assert config.layers_in_order() == ["identity", "rbac", "audit"]


def test_disabling_required_layer_is_rejected() -> None:
    config = GateConfig(enabled_layers=["identity", "approval", "quota", "audit"])
    with pytest.raises(GateConfigError):
        config.validate()


def test_disabling_audit_is_rejected() -> None:
    config = GateConfig(audit_enabled=False)
    with pytest.raises(GateConfigError):
        config.validate()


def test_thin_mode_may_drop_approval_and_quota() -> None:
    # approval + quota are the only droppable layers (thin mode).
    config = GateConfig(enabled_layers=["identity", "rbac", "redaction", "audit"], mode="thin")
    config.validate()  # must not raise


def test_config_from_document_round_trips() -> None:
    config = config_from_document(
        {
            "enabled_layers": ["identity", "rbac", "redaction", "audit"],
            "audit_enabled": True,
            "mode": "thin",
        }
    )
    assert config.mode == "thin"
    assert "approval" not in config.layers_in_order()


def test_config_from_empty_document_is_thick() -> None:
    assert config_from_document(None).layers_in_order() == list(CANONICAL_LAYER_ORDER)


def test_tenant_override_applies() -> None:
    base = GateConfig(
        tenant_overrides={"t1": {"enabled_layers": ["identity", "rbac", "redaction", "audit"], "mode": "thin"}}
    )
    override = base.for_tenant("t1")
    assert override.mode == "thin"
    # other tenants keep the base (thick) chain
    assert base.for_tenant("t2").layers_in_order() == list(CANONICAL_LAYER_ORDER)
