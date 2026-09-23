"""Skill draft generation (011 FR-3 / FR-4 / FR-13 / clarify OQ-3).

A discovered pattern becomes a **Skill draft** — an intermediate state that enters
004's draft lifecycle; it is never published directly. A draft only qualifies when
it carries an executable test sample and passes a preview run (generation-side
quality gate, FR-13), so low-quality output never pollutes the 004 market.

MR creation is gated separately on confidence (see ``mr.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .fragment import ExperienceFragment
from .scanner import PatternCluster

DRAFT_STATUS = "draft"           # enters 004 as a draft, never published directly

# Generation-side quality gate: a draft needs an executable test sample (FR-13).
DEFAULT_MIN_TEST_SAMPLES = 1


class DraftError(ValueError):
    """Raised for an invalid draft request."""


@dataclass
class TestSample:
    """An executable input/output sample attached to a draft."""

    input: dict[str, Any] = field(default_factory=dict)
    expected: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"input": dict(self.input), "expected": self.expected}


@dataclass
class SkillDraft:
    """A generated Skill draft (intermediate state, not published)."""

    skill_id: str
    name: str = ""
    description: str = ""
    actions: list[str] = field(default_factory=list)
    scene: list[str] = field(default_factory=list)
    test_samples: list[TestSample] = field(default_factory=list)
    status: str = DRAFT_STATUS
    source_fragment_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    preview_passed: bool = False
    generated_by: str = "dream_cycle"

    def __post_init__(self) -> None:
        if not str(self.skill_id or "").strip():
            raise DraftError("skill_id must not be empty")

    @property
    def is_draft(self) -> bool:
        """A draft is never published directly (FR-3)."""
        return self.status == DRAFT_STATUS

    def as_dict(self) -> dict[str, Any]:
        return {
            "skillId": self.skill_id,
            "name": self.name,
            "description": self.description,
            "scene": list(self.scene),
            "actions": list(self.actions),
            "status": self.status,
            "testSamples": [sample.as_dict() for sample in self.test_samples],
            "sourceFragmentIds": list(self.source_fragment_ids),
            "confidence": self.confidence,
            "previewPassed": self.preview_passed,
            "generatedBy": self.generated_by,
        }


def build_test_samples(fragments: list[ExperienceFragment]) -> list[TestSample]:
    """Derive test samples from the cluster's fragments.

    Each fragment's scene/actions/result becomes one input/expected pair — enough
    for a preview run to exercise the draft.
    """
    samples: list[TestSample] = []
    for fragment in fragments:
        samples.append(
            TestSample(
                input={"scene": list(fragment.scene), "actions": list(fragment.actions)},
                expected=fragment.result,
            )
        )
    return samples


def quality_gate(draft: SkillDraft, *, min_samples: int = DEFAULT_MIN_TEST_SAMPLES) -> tuple[bool, str]:
    """Generation-side quality gate (FR-13).

    A draft qualifies only when it has at least ``min_samples`` executable test
    samples. Returns ``(ok, reason)``.
    """
    if len(draft.test_samples) < max(1, int(min_samples)):
        return False, f"缺少可执行测试样例（{len(draft.test_samples)}/{min_samples}）"
    return True, ""


def generate_draft(
    cluster: PatternCluster,
    *,
    preview_runner: Callable[[SkillDraft], bool] | None = None,
    min_samples: int = DEFAULT_MIN_TEST_SAMPLES,
    skill_id: str = "",
) -> SkillDraft | None:
    """Generate a Skill draft from a pattern cluster (FR-3 / FR-13).

    Returns ``None`` when the generation-side gate fails — no draft is produced,
    so a pattern that cannot be tested never reaches the market.
    """
    fragments = list(cluster.fragments)
    representative = cluster.representative
    if representative is None:
        return None

    draft = SkillDraft(
        skill_id=skill_id or f"skill-{representative.fragment_id or 'auto'}",
        name=_derive_name(representative),
        description=representative.result or "由 Dream Cycle 从重复模式生成",
        actions=list(representative.actions),
        scene=list(representative.scene),
        test_samples=build_test_samples(fragments),
        source_fragment_ids=[item.fragment_id for item in fragments if item.fragment_id],
        confidence=cluster.similarity,
    )

    ok, _reason = quality_gate(draft, min_samples=min_samples)
    if not ok:
        return None

    if preview_runner is not None:
        draft.preview_passed = bool(preview_runner(draft))
        if not draft.preview_passed:
            # Preview must run clean; otherwise the draft is rejected (FR-13).
            return None
    return draft


def _derive_name(fragment: ExperienceFragment) -> str:
    scene = " ".join(str(item) for item in fragment.scene[:3]).strip()
    return f"{scene or '重复模式'} 自动化"[:80]
