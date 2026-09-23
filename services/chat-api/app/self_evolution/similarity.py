"""Similarity + confidence (011 FR-3 / FR-5 / clarify OQ-2 / OQ-3).

Two metrics, no vector store (first delivery):

* **Jaccard** over scene feature tokens — set overlap;
* **edit distance** over action sequences — Levenshtein.

A pattern is **high confidence** (and therefore eligible for auto-MR) when
``jaccard >= 0.7`` **and** the sample count is ``>= 5`` (clarify OQ-3).
"""

from __future__ import annotations

from typing import Iterable

DEFAULT_JACCARD_THRESHOLD = 0.7
DEFAULT_MIN_SAMPLES = 5


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """Jaccard similarity of two token sets (0.0 when both are empty).

    Tokens are normalized (trimmed, lowercased) so trivial formatting differences
    do not affect the score.
    """
    left_set = {str(item).strip().lower() for item in left if str(item).strip()}
    right_set = {str(item).strip().lower() for item in right if str(item).strip()}
    if not left_set and not right_set:
        return 0.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def edit_distance(left: Iterable[str], right: Iterable[str]) -> int:
    """Levenshtein distance between two action sequences."""
    a = [str(item) for item in left]
    b = [str(item) for item in right]
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current = [i]
        for j, token_b in enumerate(b, start=1):
            cost = 0 if token_a == token_b else 1
            current.append(
                min(
                    previous[j] + 1,        # deletion
                    current[j - 1] + 1,     # insertion
                    previous[j - 1] + cost, # substitution
                )
            )
        previous = current
    return previous[-1]


def normalized_edit_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    """Edit similarity in ``[0, 1]`` (1 = identical sequences)."""
    a = [str(item) for item in left]
    b = [str(item) for item in right]
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - (edit_distance(a, b) / longest)


def similarity(scene_left: Iterable[str], scene_right: Iterable[str]) -> float:
    """Scene similarity (Jaccard) — the primary pattern-match metric."""
    return jaccard(scene_left, scene_right)


def is_high_confidence(
    scene_similarity: float,
    sample_count: int,
    *,
    jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> bool:
    """Whether a pattern is confident enough for an automatic MR (clarify OQ-3)."""
    return scene_similarity >= jaccard_threshold and int(sample_count) >= int(min_samples)


def cluster_by_similarity(
    fragments: list[object],
    *,
    threshold: float = DEFAULT_JACCARD_THRESHOLD,
    scene_getter=None,
) -> list[list[object]]:
    """Group fragments into clusters whose scenes are pairwise similar.

    A simple greedy clustering: each fragment joins the first cluster it is similar
    enough to, otherwise starts a new one. Good enough for first-delivery pattern
    discovery without a vector store.
    """
    getter = scene_getter or (lambda fragment: getattr(fragment, "scene", []))
    clusters: list[list[object]] = []
    for fragment in fragments:
        scene = getter(fragment)
        placed = False
        for cluster in clusters:
            if jaccard(scene, getter(cluster[0])) >= threshold:
                cluster.append(fragment)
                placed = True
                break
        if not placed:
            clusters.append([fragment])
    return clusters
