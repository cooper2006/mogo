"""Improvement MR (011 T011-T013 / US3) — high-confidence auto-MR vs draft.

Candidate signals that pass the confidence gate (Jaccard ≥ 0.7 AND sample ≥ 5)
auto-generate an **improvement MR** (Skill definition + tests + description)
targeted at the 004 draft directory, awaiting human review before publish.
Lower-confidence candidates stay as **drafts** only (middle state, no MR).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# 011 T011 confidence gate (Jaccard ≥ 0.7 AND samples ≥ 5)
DEFAULT_JACCARD_THRESHOLD = 0.7
DEFAULT_MIN_SAMPLES = 5
# 011 T012 target: the 004 skill draft directory.
DRAFT_DIR = "specs/004-skillhub-lifecycle/drafts"
# Improvement-MR label (011 US3).
IMPROVEMENT_MR = "improvement-mr"


@dataclass
class ImprovementCandidate:
    key: str
    jaccard: float
    samples: int
    payload: dict[str, Any] = field(default_factory=dict)

    def is_high_confidence(self) -> bool:
        """011 T012: high-confidence = Jaccard ≥ 0.7 AND samples ≥ 5."""
        return self.jaccard >= DEFAULT_JACCARD_THRESHOLD and self.samples >= DEFAULT_MIN_SAMPLES


@dataclass
class Draft:
    """A middle-state candidate (all modes pass through draft first, T012)."""
    key: str
    status: str = "draft"

    def as_document(self) -> dict[str, Any]:
        return {"key": self.key, "status": self.status, "target_dir": DRAFT_DIR}


@dataclass
class ImprovementMR:
    """A high-confidence improvement MR (Skill def + tests + description, T011)."""
    key: str
    jaccard: float
    samples: int
    target_dir: str = DRAFT_DIR

    @property
    def label(self) -> str:
        return IMPROVEMENT_MR

    def as_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "jaccard": self.jaccard,
            "samples": self.samples,
            "target_dir": self.target_dir,
            "requires_human_review": True,
        }


def build_candidate(item: dict[str, Any]) -> ImprovementCandidate:
    return ImprovementCandidate(
        key=str(item.get("key") or ""),
        jaccard=float(item.get("jaccard") or 0.0),
        samples=int(item.get("samples") or 0),
        payload=dict(item),
    )


def plan_improvements(
    candidates: list[ImprovementCandidate],
) -> tuple[list[ImprovementMR], list[Draft]]:
    """011 T012 draft vs MR boundary.

    High-confidence candidates -> ImprovementMR; lower-confidence -> Draft.
    Every candidate passes through the draft middle-state first (T012:
    草稿 = 全部模式中间态).
    """
    mrs: list[ImprovementMR] = []
    drafts: list[Draft] = []
    for candidate in candidates:
        if not str(candidate.key or "").strip():
            continue
        # Draft is the universal middle state; an MR is generated on top of it
        # when the candidate is high-confidence.
        if candidate.is_high_confidence():
            mrs.append(
                ImprovementMR(
                    key=candidate.key,
                    jaccard=candidate.jaccard,
                    samples=candidate.samples,
                )
            )
            drafts.append(Draft(key=candidate.key, status="draft->mr"))
        else:
            drafts.append(Draft(key=candidate.key, status="draft"))
    return mrs, drafts


def generate_improvement_mr(
    candidate: ImprovementCandidate,
    *,
    target_dir: str = DRAFT_DIR,
) -> Optional[ImprovementMR]:
    """011 T011: high-confidence auto-MR. Returns None when not high-confidence."""
    if not candidate.is_high_confidence():
        return None
    return ImprovementMR(
        key=candidate.key,
        jaccard=candidate.jaccard,
        samples=candidate.samples,
        target_dir=target_dir,
    )
