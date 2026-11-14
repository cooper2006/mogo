"""Capability contract schema (018 FR-3 / FR-9 / clarify OQ-1).

A contract is a declarative JSON object with four sections:

* ``input``  — accepted parameters;
* ``output`` — produced fields;
* ``errors`` — declared failure modes;
* ``sla``    — latency / availability expectations.

Anything missing is normalized to an empty object so downstream code never has to
guard for absent sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CONTRACT_SECTIONS: tuple[str, ...] = ("input", "output", "errors", "sla")


class ContractError(ValueError):
    """Raised for an invalid capability contract."""


@dataclass
class AssetContract:
    """A declarative capability contract (four sections)."""

    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Any] = field(default_factory=dict)
    sla: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": dict(self.input),
            "output": dict(self.output),
            "errors": dict(self.errors),
            "sla": dict(self.sla),
        }

    def is_complete(self) -> bool:
        """Whether every section is present (an empty-but-declared section counts)."""
        return all(section in self.as_dict() for section in CONTRACT_SECTIONS)


def normalize_contract(document: Any) -> AssetContract:
    """Normalize a raw contract document into an ``AssetContract``.

    * a non-object document is invalid (fail loudly — the caller must not register
      a malformed asset);
    * unknown top-level keys are ignored;
    * missing sections are filled with empty objects.
    """
    if document is None:
        return AssetContract()
    if not isinstance(document, dict):
        raise ContractError("contract must be an object")

    sections: dict[str, dict[str, Any]] = {}
    for section in CONTRACT_SECTIONS:
        value = document.get(section)
        if value is None:
            sections[section] = {}
        elif isinstance(value, dict):
            sections[section] = dict(value)
        else:
            raise ContractError(f"contract section {section!r} must be an object")
    return AssetContract(**sections)


def contract_diff(old: AssetContract, new: AssetContract) -> dict[str, Any]:
    """Field-level diff between two contracts (used by the change audit, FR-7)."""
    diff: dict[str, Any] = {}
    old_dict, new_dict = old.as_dict(), new.as_dict()
    for section in CONTRACT_SECTIONS:
        if old_dict[section] != new_dict[section]:
            diff[section] = {"before": old_dict[section], "after": new_dict[section]}
    return diff
