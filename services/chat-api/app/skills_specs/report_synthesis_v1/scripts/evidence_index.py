"""Evidence index for the synthesis node (every claim traceable by id)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass
class EvidenceIndex:
    """Collects evidence records and assigns stable ids."""

    records: dict[str, dict] = field(default_factory=dict)

    def add(self, *, source: str, claim: str, url: str = "", node_id: str = "") -> str:
        digest = hashlib.sha256(f"{source}|{claim}|{url}".encode("utf-8")).hexdigest()[:12]
        evidence_id = f"ev-{digest}"
        self.records.setdefault(
            evidence_id,
            {"id": evidence_id, "source": source, "claim": claim, "url": url, "node_id": node_id},
        )
        return evidence_id

    def as_json(self) -> list[dict]:
        return [self.records[key] for key in sorted(self.records)]

    def __len__(self) -> int:
        return len(self.records)


def collect_from_node_outputs(outputs: Mapping[str, Mapping]) -> EvidenceIndex:
    """Build an index from each sub-agent's declared evidence list."""
    index = EvidenceIndex()
    for node_id, output in outputs.items():
        for item in (output or {}).get("evidence") or []:
            index.add(
                source=str(item.get("source") or node_id),
                claim=str(item.get("claim") or ""),
                url=str(item.get("url") or ""),
                node_id=node_id,
            )
    return index


def unresolved_claims(index: EvidenceIndex, claims: Iterable[str]) -> list[str]:
    """Return claims that have no matching evidence entry."""
    known = {record["claim"] for record in index.records.values()}
    return [claim for claim in claims if claim not in known]
