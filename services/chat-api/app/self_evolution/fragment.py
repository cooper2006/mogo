"""Experience fragment model + stores (011 T002).

A fragment is the structured unit captured from a friction event (FR-2):

* ``scene``          — scene feature tokens (for Jaccard similarity);
* ``actions``        — the action sequence (for edit distance);
* ``result``         — outcome description;
* ``created_at``     — capture time;
* ``source_session`` — the session it came from (002);
* ``feedback``       — optional user correction text.

Two backends:
* ``FragmentStore`` — in-memory index used by the scanning logic and tests;
* ``PersistentFragmentStore`` — MongoDB-backed store (011 persistence fix,
  2026-10-03). Without it every dream pass started a fresh in-memory store, so
  two passes produced byte-identical output and cross-pass state did not exist
  (001 audit report, item 011-①).
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

#: Durable collection for experience fragments (tenant-scoped).
FRAGMENT_COLLECTION = "experience_fragments"


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

    def stable_fingerprint(self) -> str:
        """Deterministic content identity for idempotent re-capture.

        A re-scanned projection row re-derives the *same* logical fragment
        (same tenant + scene + actions + result + session). That content
        fingerprint — not a per-pass counter — is what makes re-capture
        idempotent: two passes over the same history yield the same
        ``fragment_id`` and upsert in place instead of growing unboundedly.
        """
        material = "|".join(
            [
                self.tenant_id,
                ",".join(sorted(self.scene_tokens())),
                ",".join(self.actions),
                self.result,
                self.source_session,
            ]
        )
        return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]

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

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "ExperienceFragment":
        """Rebuild a fragment from its persisted Mongo document."""
        return cls(
            scene=list(document.get("scene") or []),
            actions=list(document.get("actions") or []),
            result=str(document.get("result") or ""),
            friction_kind=str(document.get("friction_kind") or ""),
            created_at=document.get("created_at") or _utcnow(),
            source_session=str(document.get("source_session") or ""),
            feedback=str(document.get("feedback") or ""),
            tenant_id=str(document.get("tenant_id") or "default"),
            fragment_id=str(document.get("fragment_id") or ""),
        )


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


class PersistentFragmentStore:
    """MongoDB-backed fragment store — persists across dream passes (011 ①).

    * ``load_history`` pulls this tenant's previously-captured fragments so a
      new pass sees accumulated state instead of a blank slate.
    * ``add_persisted`` writes a fragment and returns it with a stable
      ``fragment_id`` (assigned only when absent).

    Without a bound ``db`` the store degrades to a no-op (``load_history``
    returns ``[]``, ``add_persisted`` is a plain append to an internal list) so
    the pure-library path stays exercisable without Mongo.
    """

    def __init__(self, db: Any = None, *, limit: int = 2000) -> None:
        self._db = db
        self._limit = int(limit)
        # In-memory fallback mirroring FragmentStore when no DB is bound.
        self._mem: list[ExperienceFragment] = []
        self._counter = 0

    def _alloc_id(self, fragment: ExperienceFragment) -> None:
        # In-memory fragment_id is a content-stable *content* key when one is
        # already set (fingerprint path), otherwise a per-store counter. The
        # counter id keeps the existing draft-derivation contract
        # (``skill-frag-<counter>``); the durable idempotence key is the
        # fingerprint written by :meth:`add_persisted` (011 ①).
        if not fragment.fragment_id:
            self._counter += 1
            fragment.fragment_id = f"frag-{self._counter:06d}"

    async def load_history(self, tenant_id: str) -> list[ExperienceFragment]:
        """Previously-captured fragments for this tenant (oldest first)."""
        if self._db is None:
            return [item for item in self._mem if item.tenant_id == tenant_id]
        cursor = (
            self._db[FRAGMENT_COLLECTION]
            .find({"tenant_id": str(tenant_id)})
            .sort("created_at", 1)
            .limit(self._limit)
        )
        documents = [dict(doc) async for doc in cursor]
        return [ExperienceFragment.from_document(doc) for doc in documents]

    async def add_persisted(self, fragment: ExperienceFragment) -> ExperienceFragment:
        """Assign a stable id (if missing) and persist the fragment.

        Persistence is keyed on the **content fingerprint** (tenant + scene +
        actions + result + session), so a re-scanned, unchanged projection row
        re-captures the *same* logical fragment and upserts in place rather
        than growing unboundedly. The in-memory ``fragment_id`` (a per-store
        counter) is preserved for the existing draft-derivation contract; the
        fingerprint is stored alongside it as the durable idempotence key.

        Handles both the aiomongo production handle (async ``update_one``) and
        the sync fake used in tests (``update_one`` returning ``None``): the
        store-write result is awaited when — and only when — it is a
        coroutine, so the same call site works on both.
        """
        self._alloc_id(fragment)
        if self._db is not None:
            document = fragment.as_document()
            document["fingerprint"] = fragment.stable_fingerprint()
            result = self._db[FRAGMENT_COLLECTION].update_one(
                {"tenant_id": document["tenant_id"], "fingerprint": document["fingerprint"]},
                {"$setOnInsert": document},
                upsert=True,
            )
            if hasattr(result, "__await__"):
                await result
        else:
            self._mem.append(fragment)
        return fragment

    def extend_persisted(self, fragments: Iterable[ExperienceFragment]) -> None:
        for fragment in fragments:
            self.add_persisted(fragment)
