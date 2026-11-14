"""AgentCard model, generation and parsing (012 FR-1 / FR-5 / FR-9).

An AgentCard carries the A2A-standard fields: agent name, description, endpoint
URL, protocol version, authentication method, and a ``skills[]`` capability list.
Cards are keyed by agent id and addressed as ``/a2a/{tenant}/{agent_id}`` (FR-8).

Only capabilities explicitly marked ``a2a_exposed`` produce an AgentCard (FR-12 /
018 relation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# A2A protocol version aligned with the standard's latest stable release (clarify OQ-1).
A2A_PROTOCOL_VERSION = "1.0"

# Authentication methods an AgentCard may advertise (FR-9).
AUTH_METHODS = ("api_key", "oauth2", "org_trust")

DEFAULT_INPUT_MODES = ("text/plain",)
DEFAULT_OUTPUT_MODES = ("text/plain",)


class AgentCardError(ValueError):
    """Raised for an invalid AgentCard definition."""


@dataclass
class AgentSkill:
    """One capability entry in an AgentCard's ``skills[]``."""

    id: str
    name: str = ""
    description: str = ""
    input_modes: tuple[str, ...] = DEFAULT_INPUT_MODES
    output_modes: tuple[str, ...] = DEFAULT_OUTPUT_MODES

    def __post_init__(self) -> None:
        if not str(self.id or "").strip():
            raise AgentCardError("skill id must not be empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "description": self.description,
            "inputModes": list(self.input_modes),
            "outputModes": list(self.output_modes),
        }


@dataclass
class AgentCard:
    """An A2A AgentCard."""

    agent_id: str
    name: str
    description: str = ""
    endpoint: str = ""
    protocol_version: str = A2A_PROTOCOL_VERSION
    auth_method: str = "api_key"
    skills: list[AgentSkill] = field(default_factory=list)
    tenant_id: str = "default"

    def __post_init__(self) -> None:
        if not str(self.agent_id or "").strip():
            raise AgentCardError("agent_id must not be empty")
        if not str(self.name or "").strip():
            raise AgentCardError("agent name must not be empty")
        if self.auth_method not in AUTH_METHODS:
            raise AgentCardError(f"unknown auth method: {self.auth_method!r}")

    def url(self) -> str:
        """The canonical A2A endpoint URL for this agent (``/a2a/{tenant}/{agent}``)."""
        if self.endpoint:
            return self.endpoint
        return f"/a2a/{self.tenant_id}/{self.agent_id}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url(),
            "version": self.protocol_version,
            "protocolVersion": self.protocol_version,
            "authentication": {"schemes": [self.auth_method]},
            "skills": [skill.as_dict() for skill in self.skills],
        }


def build_agent_card(
    *,
    agent_id: str,
    name: str,
    description: str = "",
    tenant_id: str = "default",
    auth_method: str = "api_key",
    endpoint: str = "",
    capabilities: Iterable[dict[str, Any]] = (),
    a2a_exposed: bool = False,
) -> AgentCard | None:
    """Build an AgentCard from registered capabilities.

    Returns ``None`` when the agent is **not** explicitly exposed over A2A — the
    default is no card (FR-12).
    """
    if not a2a_exposed:
        return None
    skills = [
        AgentSkill(
            id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            description=str(item.get("description") or ""),
            input_modes=tuple(item.get("inputModes") or DEFAULT_INPUT_MODES),
            output_modes=tuple(item.get("outputModes") or DEFAULT_OUTPUT_MODES),
        )
        for item in capabilities
        if str(item.get("id") or "").strip()
    ]
    return AgentCard(
        agent_id=agent_id,
        name=name,
        description=description,
        endpoint=endpoint,
        auth_method=auth_method,
        skills=skills,
        tenant_id=tenant_id,
    )


def parse_agent_card(document: dict[str, Any]) -> AgentCard:
    """Parse an external AgentCard document (Dify-first field mapping, clarify OQ-4)."""
    if not isinstance(document, dict):
        raise AgentCardError("AgentCard must be an object")
    name = str(document.get("name") or "").strip()
    if not name:
        raise AgentCardError("AgentCard requires a name")
    raw_skills = document.get("skills") or []
    skills = [
        AgentSkill(
            id=str(item.get("id") or item.get("name") or ""),
            name=str(item.get("name") or ""),
            description=str(item.get("description") or ""),
        )
        for item in raw_skills
        if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
    ]
    authentication = document.get("authentication") or {}
    schemes = authentication.get("schemes") if isinstance(authentication, dict) else None
    auth_method = str((schemes or ["api_key"])[0])
    if auth_method not in AUTH_METHODS:
        auth_method = "api_key"  # tolerate external schemes we do not model yet
    return AgentCard(
        agent_id=str(document.get("id") or name),
        name=name,
        description=str(document.get("description") or ""),
        endpoint=str(document.get("url") or ""),
        protocol_version=str(document.get("protocolVersion") or document.get("version") or A2A_PROTOCOL_VERSION),
        auth_method=auth_method,
        skills=skills,
    )
