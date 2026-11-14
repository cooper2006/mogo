"""browser.navigate — land on a target URL / view."""
from __future__ import annotations

from typing import Any, Dict

from .schema import BrowserActionSpec, ContractResult


def _validate(data: Dict[str, Any]) -> ContractResult:
    """Synchronous schema check only.

    The authoritative outbound-allowlist landing verdict for ``final_url`` is
    ``verify_landing_url`` below, which is async because it must read the
    allowlist and write the audit event; ``_validate`` intentionally stays a
    cheap, side-effect-free shape check that the desktop agent runs inline.
    """
    if not isinstance(data, dict):
        return ContractResult(ok=False, reason="browser_done.data must be an object", missing=["final_url"])
    final_url = str(data.get("final_url") or "").strip()
    if not final_url:
        return ContractResult(
            ok=False,
            reason="final_url missing — a navigate task must report the URL it actually landed on",
            missing=["final_url"],
        )
    if final_url.lower() == "about:blank":
        return ContractResult(
            ok=False,
            reason="final_url is about:blank — navigation didn't complete",
            missing=["final_url"],
        )
    return ContractResult(ok=True)


async def verify_landing_url(
    final_url: str,
    *,
    tenant_id: str,
    user_id: str,
    action_id: str,
    tool_or_capability: str = "browser.navigate",
):
    """038: outbound-allowlist verdict on the URL navigation actually landed on.

    A navigate may start on an allowlisted URL and be redirected anywhere; the
    real risk is the *landing* URL, so it is re-judged here (fail-closed) and
    the result is audited. A non-allowed landing is a redirect escape.
    """
    from ....tools.egress_guard import egress_guard

    decision = await egress_guard.check(url=final_url, tenant_id=tenant_id)
    await egress_guard.audit(
        decision,
        tenant_id=tenant_id,
        user_id=user_id,
        action_id=action_id,
        tool_or_capability=tool_or_capability,
    )
    return decision


SPEC = BrowserActionSpec(
    capability_id="browser.navigate",
    name_zh="切换页面",
    name_en="Navigate",
    description_zh="打开指定页面 / 跳转到指定视图（不改数据、不提交）",
    description_en="Open a target page or switch views (no data change, no submit)",
    produces=("final_url",),
    data_schema_hint_zh=(
        '{"final_url": "<落地后实际 URL>", "page_title": "<页面标题, 可选>", '
        '"landed_ok": true}'
    ),
    data_schema_hint_en=(
        '{"final_url": "<actual URL after landing>", '
        '"page_title": "<optional>", "landed_ok": true}'
    ),
    validate=_validate,
)
