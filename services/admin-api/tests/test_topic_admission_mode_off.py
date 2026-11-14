"""059 T008 — topic_admission ``mode=off`` → 拒绝（fail-closed）。

``preview`` 在 ``mode == "off"`` 时直接判定 ``allowed=False``；
其余模式下命中词表才放行，验证闸门逻辑本身也正确工作。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.topic_admission.service import preview


def _entry(keyword: str, synonyms=None) -> SimpleNamespace:
    return SimpleNamespace(keyword=keyword, synonyms=synonyms or [])


def _rule(entries, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id="r1", enabled=enabled, terms=entries)


def test_mode_off_denies() -> None:
    payload = SimpleNamespace(mode="off", rules=[_rule([_entry("违规")])])
    result = preview("违规内容", payload)
    assert result["allowed"] is False
    assert result["mode"] == "off"


def test_denylist_matching_term_denied() -> None:
    payload = SimpleNamespace(mode="denylist", rules=[_rule([_entry("违规")])])
    assert preview("这是违规文本", payload)["allowed"] is False


def test_denylist_nonmatching_allowed() -> None:
    payload = SimpleNamespace(mode="denylist", rules=[_rule([_entry("违规")])])
    assert preview("正常文本", payload)["allowed"] is True
