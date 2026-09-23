"""Experience fragment model + in-memory store (011 T002).

A fragment is the structured unit captured from a friction event (FR-2):

* ``scene``          — scene feature tokens (for Jaccard similarity);
* ``actions``        — the action sequence (for edit distance);
* ``result``         — outcome description;
* ``created_at``     — capture time;
* ``source_session`` — the session it came from (002);
* ``feedback``       — optional user correction text.

The store here is an in-memory index used by the scanning logic and tests; the
durable collection is wired at the integration layer.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class ExperienceFragment:
    """A structured experience fragment captured from friction."""

    scene: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    result: str = ""
    friction_kind: str = ""
    created_at: datetime.datetime = field(default_factory=_utcnow)
    source_session: str = ""
    feedback: str = ""
    tenant_id: str = "default"
    fragment_id: str = ""

    def scene_tokens(self) -> set[str]:
        return {str(token).strip().lower() for token in self.scene if str(token).strip()}

    def as_document(self) -> dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "tenant_id": self.tenant_id,
            "scene": list(self.scene),
            "actions": list(self.actions),
            "result": self.result,
            "friction_kind": self.friction_kind,
            "created_at": self.created_at,
            "source_session": self.source_session,
            "feedback": self.feedback,
        }


class FragmentStore:
    """In-memory fragment store, scoped by tenant (for scanning + tests)."""

    def __init__(self) -> None:
        self._items: list[ExperienceFragment] = []
        self._counter = 0

    def add(self, fragment: ExperienceFragment) -> ExperienceFragment:
        self._counter += 1
        if not fragment.fragment_id:
            fragment.fragment_id = f"frag-{self._counter:06d}"
        self._items.append(fragment)
        return fragment

    def extend(self, fragments: Iterable[ExperienceFragment]) -> None:
        for fragment in fragments:
            self.add(fragment)

    def all(self, tenant_id: str | None = None) -> list[ExperienceFragment]:
        if tenant_id is None:
            return list(self._items)
        return [item for item in self._items if item.tenant_id == tenant_id]

    def __len__(self) -> int:
        return len(self._items)

    def by_id(self, fragment_id: str) -> Optional[ExperienceFragment]:
        for item in self._items:
            if item.fragment_id == fragment_id:
                return item
        return None
