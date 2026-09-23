"""Periodic scan for repeated patterns (011 FR-3 / FR-5 / clarify OQ-3).

The scanner clusters experience fragments by scene similarity, counts each
cluster's samples, and marks clusters that reach the confidence threshold
(Jaccard >= 0.7 **and** samples >= 5) as MR-eligible. It reuses ``scheduled_tasks``
for the periodic trigger (clarify OQ-5) — this module only does the discovery.

Draft generation and MR creation consume the clusters produced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .fragment import ExperienceFragment
from .similarity import (
    DEFAULT_JACCARD_THRESHOLD,
    DEFAULT_MIN_SAMPLES,
    cluster_by_similarity,
    is_high_confidence,
    jaccard,
)

# Scan cadence values reuse the existing scheduler (clarify OQ-5).
SCHEDULE_FREQUENCIES = ("once", "daily", "weekly")
DEFAULT_SCAN_FREQUENCY = "daily"

# Draft backlog cap per tenant (FR-12).
DEFAULT_DRAFT_BACKLOG_LIMIT = 100


@dataclass
class PatternCluster:
    """A group of similar experience fragments discovered by a scan."""

    fragments: list[ExperienceFragment] = field(default_factory=list)
    similarity: float = 0.0

    @property
    def sample_count(self) -> int:
        return len(self.fragments)

    @property
    def representative(self) -> ExperienceFragment | None:
        return self.fragments[0] if self.fragments else None

    def is_mr_eligible(
        self,
        *,
        threshold: float = DEFAULT_JACCARD_THRESHOLD,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> bool:
        return is_high_confidence(self.similarity, self.sample_count, jaccard_threshold=threshold, min_samples=min_samples)


@dataclass
class ScanConfig:
    """Scanner configuration (FR-8, all configurable)."""

    frequency: str = DEFAULT_SCAN_FREQUENCY
    jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD
    min_samples: int = DEFAULT_MIN_SAMPLES
    draft_backlog_limit: int = DEFAULT_DRAFT_BACKLOG_LIMIT

    def __post_init__(self) -> None:
        if self.frequency not in SCHEDULE_FREQUENCIES:
            raise ValueError(f"unsupported scan frequency: {self.frequency!r}")


@dataclass
class ScanResult:
    """Outcome of one scan."""

    clusters: list[PatternCluster] = field(default_factory=list)

    @property
    def mr_eligible(self) -> list[PatternCluster]:
        return [cluster for cluster in self.clusters if cluster.is_mr_eligible()]

    @property
    def draft_only(self) -> list[PatternCluster]:
        return [cluster for cluster in self.clusters if not cluster.is_mr_eligible()]


def scan_fragments(
    fragments: Iterable[ExperienceFragment],
    *,
    config: ScanConfig | None = None,
) -> ScanResult:
    """Cluster fragments and score each cluster's similarity.

    Cluster similarity is the **average pairwise Jaccard** against the cluster's
    representative, which is what the confidence check consumes (FR-3).
    """
    resolved = config or ScanConfig()
    materialized = list(fragments)
    clusters = cluster_by_similarity(
        materialized, threshold=resolved.jaccard_threshold, scene_getter=lambda item: item.scene
    )

    pattern_clusters: list[PatternCluster] = []
    for cluster in clusters:
        representative = cluster[0]
        base_scene = getattr(representative, "scene", [])
        if len(cluster) == 1:
            similarity = 1.0
        else:
            scores = [
                jaccard(base_scene, getattr(item, "scene", []))
                for item in cluster[1:]
            ]
            similarity = sum(scores) / len(scores) if scores else 0.0
        pattern_clusters.append(
            PatternCluster(fragments=list(cluster), similarity=similarity)
        )
    pattern_clusters.sort(key=lambda item: (item.sample_count, item.similarity), reverse=True)
    return ScanResult(clusters=pattern_clusters)


def should_generate_draft(
    cluster: PatternCluster,
    *,
    config: ScanConfig | None = None,
    existing_drafts: int = 0,
) -> bool:
    """Whether a cluster should produce a draft (FR-3 / FR-12).

    Every discovered pattern produces a draft (high or low confidence) — a draft
    is the intermediate state. Only the **MR** step is gated on confidence. The
    draft backlog cap suppresses draft creation once the limit is reached.
    """
    resolved = config or ScanConfig()
    if existing_drafts >= resolved.draft_backlog_limit:
        return False
    return cluster.sample_count >= 1


def dedupe_drafts(
    clusters: Iterable[PatternCluster],
    *,
    threshold: float = DEFAULT_JACCARD_THRESHOLD,
) -> list[PatternCluster]:
    """Drop lower-confidence clusters that overlap a higher-confidence one (FR-12)."""
    ordered = sorted(clusters, key=lambda item: (item.similarity, item.sample_count), reverse=True)
    kept: list[PatternCluster] = []
    for cluster in ordered:
        scene = getattr(cluster.representative, "scene", []) if cluster.representative else []
        duplicate = False
        for existing in kept:
            existing_scene = (
                getattr(existing.representative, "scene", []) if existing.representative else []
            )
            if jaccard(scene, existing_scene) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(cluster)
    return kept


def scan_summary(result: ScanResult, *, config: ScanConfig | None = None) -> dict[str, Any]:
    """A JSON-friendly summary of a scan (for auditing / observability)."""
    resolved = config or ScanConfig()
    return {
        "frequency": resolved.frequency,
        "clusterCount": len(result.clusters),
        "mrEligibleCount": len(result.mr_eligible),
        "draftOnlyCount": len(result.draft_only),
        "jaccardThreshold": resolved.jaccard_threshold,
        "minSamples": resolved.min_samples,
    }
