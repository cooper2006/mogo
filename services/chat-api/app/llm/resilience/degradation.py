"""Model degradation chain (007 FR-2 / clarify OQ-3 / OQ-4).

When the primary model tier fails, the call degrades down a configured chain
(high-performance -> mid -> light) until a tier succeeds or the chain is exhausted.
The chain is **text models only** (image generation keeps its own retry).

Degradation events are attached to the usage log via ``degradation_step`` /
``degradation_reason`` (reusing ``events.degradation_fields``). Exhausting the chain
raises a clear error — never a silent empty result (FR-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .errors import AllProvidersFailedError, NonRetryableLLMError, classify_error
from .events import reason_from_status

# Default text-model degradation tiers, best first (clarify OQ-2/OQ-3).
DEFAULT_DEGRADATION_CHAIN: tuple[str, ...] = ("high", "mid", "light")


class DegradationError(Exception):
    """Raised when the degradation chain is exhausted without success."""

    def __init__(self, chain: list[str], failures: list[dict[str, Any]]) -> None:
        self.chain = list(chain)
        self.failures = failures
        summary = "; ".join(f"{item['step']}:{item['reason']}" for item in failures)
        super().__init__(f"降级链耗尽（{len(chain)} 档均失败）：{summary}")


@dataclass
class DegradationStep:
    """One tier in the degradation chain."""

    tier: str
    model: str = ""
    index: int = 0


@dataclass
class DegradationResult:
    """The outcome of a degraded call."""

    tier: str
    model: str = ""
    step: int = 0
    degraded: bool = False
    log_fields: dict[str, Any] = field(default_factory=dict)


def build_chain(
    tiers: list[str] | None = None,
    *,
    models: dict[str, str] | None = None,
) -> list[DegradationStep]:
    """Build the ordered degradation chain (configurable, not hardcoded, FR-8)."""
    resolved = list(tiers or DEFAULT_DEGRADATION_CHAIN)
    mapping = models or {}
    return [
        DegradationStep(tier=tier, model=str(mapping.get(tier, "")), index=index)
        for index, tier in enumerate(resolved)
    ]


async def run_with_degradation(
    chain: list[DegradationStep],
    caller: Callable[[DegradationStep], Awaitable[Any]],
    *,
    on_event: Optional[Callable[[dict[str, Any]], None]] = None,
) -> tuple[Any, DegradationResult]:
    """Run ``caller`` over the chain, degrading on failure.

    * a **retryable** failure moves to the next tier and emits a degradation event;
    * a **non-retryable** failure (401/403) aborts immediately — degrading would
      just hit the same auth wall;
    * exhausting the chain raises ``DegradationError`` (never a silent result).
    """
    failures: list[dict[str, Any]] = []
    for step in chain:
        try:
            output = await caller(step)
        except NonRetryableLLMError:
            raise
        except BaseException as error:  # noqa: BLE001 - reclassified below
            classified = classify_error(error)
            if isinstance(classified, NonRetryableLLMError):
                raise classified from error
            reason = reason_from_status(getattr(classified, "status_code", None)).value
            failures.append({"step": step.index + 1, "tier": step.tier, "reason": reason})
            if on_event is not None and step.index + 1 < len(chain):
                on_event(
                    {
                        "resilience_event": "degradation",
                        "degradation_step": step.index + 1,
                        "degradation_reason": reason,
                        "from_tier": step.tier,
                        "to_tier": chain[step.index + 1].tier,
                    }
                )
            continue

        result = DegradationResult(
            tier=step.tier,
            model=step.model,
            step=step.index + 1,
            degraded=step.index > 0,
            log_fields={"degradation_step": step.index + 1} if step.index > 0 else {},
        )
        if on_event is not None and step.index > 0 and failures:
            on_event(
                {
                    "resilience_event": "degradation",
                    "degradation_step": step.index + 1,
                    "degradation_reason": failures[-1]["reason"],
                    "to_tier": step.tier,
                    "served": True,
                }
            )
        return output, result

    raise DegradationError([step.tier for step in chain], failures)
