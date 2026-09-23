"""Business-semantic entity index + semantic search (014 T007 / US1).

Indexes business entities (customers / orders / products / docs / tickets)
from **pointers only** (never writes to the business DB — 014 Non-Goal).
Semantic search **reuses the 005 retrieval client** and returns results with
a source/citation anchor so consumers can trace back to the originating
entity (US1 acceptance 2: 检索带来源).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from app.knowledge.retrieval.retrieval_client import KnowledgeRetrievalClient

ENTITY_TYPES = ("customer", "order", "product", "document", "ticket")


@dataclass
class EntityRecord:
    """A business entity index entry — pointers + lightweight fields only."""
    entity_id: str
    entity_type: str
    tenant_id: str
    title: str = ""
    source_ref: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(f"unknown entity type: {self.entity_type!r}")

    def as_document(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "tenant_id": self.tenant_id,
            "title": self.title,
            "source_ref": self.source_ref,
            "fields": dict(self.fields),
        }


@dataclass
class SemanticHit:
    """One semantic-search hit with a citation anchor (014 US1)."""
    entity_id: str
    entity_type: str
    title: str
    score: float
    source_ref: str
    chunk: str = ""

    def with_anchor(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "title": self.title,
            "score": self.score,
            "source_ref": self.source_ref,
            "chunk": self.chunk,
            "citation": f"{self.entity_type}:{self.entity_id}#{self.source_ref}",
        }


class BusinessSemanticIndex:
    """In-memory / Mongo-backed business-entity index (014 T007)."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self._db = db
        self._rows: list[dict[str, Any]] = []

    # --- index ---------------------------------------------------------------

    def index_entity(self, record: EntityRecord) -> dict[str, Any]:
        document = record.as_document()
        if self._db is not None:
            self._db["business_entity_index"].replace_one(
                {"entity_id": record.entity_id, "tenant_id": record.tenant_id},
                document,
                upsert=True,
            )
        else:
            self._rows = [
                row for row in self._rows
                if not (row.get("entity_id") == record.entity_id and row.get("tenant_id") == record.tenant_id)
            ]
            self._rows.append(document)
        return document

    def index_entities(self, records: Iterable[EntityRecord]) -> int:
        count = 0
        for record in records:
            self.index_entity(record)
            count += 1
        return count

    def known_entities(self, tenant_id: str) -> list[dict[str, Any]]:
        if self._db is not None:
            rows = self._db["business_entity_index"].find({"tenant_id": tenant_id}).to_list(length=100000)
            return [row for row in rows if row]
        return [row for row in self._rows if row.get("tenant_id") == tenant_id]

    # --- semantic search (014 T007: reuse 005 retrieval client) ---------------

    async def semantic_search(
        self,
        query: str,
        *,
        tenant_id: str,
        user_id: str = "",
        top_n: int = 8,
        client: KnowledgeRetrievalClient | None = None,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[SemanticHit]:
        """Search entities semantically via the 005 retrieval client.

        Hits are annotated with a source/citation anchor (US1 acceptance 2).
        Empty query or no client returns an honest empty list (never fabricates).
        """
        if not query or not query.strip():
            return []
        client = client or KnowledgeRetrievalClient()
        try:
            result = await client.search(
                query=query,
                main_id=tenant_id,
                user_id=user_id,
                knowledge_base_ids=knowledge_base_ids,
                top_n=top_n,
            )
        except Exception:  # noqa: BLE001 — retrieval is best-effort for indexing
            return []
        hits: list[SemanticHit] = []
        for item in result.items:
            title = " / ".join(item.titlePath) if item.titlePath else ""
            metadata = item.metadata or {}
            entity_type = str(metadata.get("entity_type") or "document")
            entity_id = str(metadata.get("entity_id") or item.documentId or "")
            hits.append(
                SemanticHit(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    title=title or entity_id,
                    score=float(item.rerankScore if item.rerankScore is not None else item.score or 0),
                    source_ref=str(item.chunkId or ""),
                    chunk=str(item.text or "")[:200],
                )
            )
        return hits[:top_n]


__all__ = [
    "ENTITY_TYPES",
    "BusinessSemanticIndex",
    "EntityRecord",
    "SemanticHit",
]
