"""040-model-tier-routing：档位评估、路由解析与异步入口契约。

覆盖 tasks.md 的 T011/T012/T013/T014 与 T015：
- 复杂度评估纯函数（阈值、声明优先、特征缺失默认 mid）
- ModelRouter 的 tier 级（命中、回落 mid、租户覆盖、非法形态、静态映射跳过）
- 异步入口 ``aget_llm_client`` 走 031 模型实例解析
- 计量字段 ``tier`` / ``tier_declared`` 写回
"""

from __future__ import annotations

import asyncio

import pytest

from app.llm import factory as factory_module
from app.llm.complexity import (
    TaskComplexityFeatures,
    evaluate_tier,
    merge_thresholds,
    normalize_declared,
)
from app.llm.model_router import ModelRouter, ModelSelection, is_model_config_id


MID_ID = "0123456789abcdef01234567"
HIGH_ID = "76543210fedcba9876543210"


def _write_router(tmp_path, *, tiers: str, tenants: str = "  {}", static: str = "") -> ModelRouter:
    body = f"""
enabled: true
by_node: {{}}
by_stage: {{}}
by_intent: {static or "{}"}
models:
  general: ""
  chat: ""
  coding: ""
tiering:
  thresholds:
    prompt_chars_high: 4000
    tool_count_high: 8
    multi_turn_high: 4
    high_stages:
      - coding
    high_intents:
      - coding
tiers:
{tiers}
tenants:
{tenants}
"""
    path = tmp_path / "model_routing.yaml"
    path.write_text(body, encoding="utf-8")
    return ModelRouter(config_path=path)


HIGH_TIER_YAML = f'  light: ""\n  mid: "{MID_ID}"\n  high: "{HIGH_ID}"'


# ---- 复杂度评估 ---------------------------------------------------------


def test_evaluate_tier_single_hit_is_mid_and_two_hits_is_high():
    assert evaluate_tier(TaskComplexityFeatures(prompt_chars=5000)).tier == "mid"
    assert evaluate_tier(TaskComplexityFeatures(prompt_chars=5000, tool_count=10)).tier == "high"


def test_evaluate_tier_zero_score_is_light():
    decision = evaluate_tier(TaskComplexityFeatures(prompt_chars=10, tool_count=1, multi_turn=0))
    assert decision.tier == "light"
    assert decision.score == 0


def test_evaluate_tier_features_absent_defaults_to_mid():
    decision = evaluate_tier(TaskComplexityFeatures())
    assert decision.tier == "mid"
    assert decision.error == "features_absent"


def test_evaluate_tier_declared_wins_over_score():
    decision = evaluate_tier(
        TaskComplexityFeatures(prompt_chars=10, declared_complexity="high")
    )
    assert decision.tier == "high"
    assert decision.declared == "high"


def test_evaluate_tier_stage_and_intent_hits():
    both = TaskComplexityFeatures(
        prompt_chars=0, tool_count=0, multi_turn=0, stage="coding", intent="coding"
    )
    assert evaluate_tier(both).tier == "high"
    only_stage = TaskComplexityFeatures(
        prompt_chars=0, tool_count=0, multi_turn=0, stage="coding"
    )
    assert evaluate_tier(only_stage).tier == "mid"


def test_merge_thresholds_partial_override_keeps_defaults():
    merged = merge_thresholds({"prompt_chars_high": 100})
    assert merged["prompt_chars_high"] == 100
    assert merged["tool_count_high"] == 8


def test_normalize_declared_rejects_unknown_values():
    assert normalize_declared("high") == "high"
    assert normalize_declared(" HIGH ") == ""
    assert normalize_declared("") == ""
    assert normalize_declared(None) == ""


def test_is_model_config_id_shape():
    assert is_model_config_id(MID_ID)
    assert not is_model_config_id("gpt-5.2")
    assert not is_model_config_id("")


# ---- ModelRouter 的 tier 级 ---------------------------------------------


def test_router_tier_hit_returns_model_config_id(tmp_path):
    router = _write_router(tmp_path, tiers=HIGH_TIER_YAML)
    selection = router.resolve(
        intent="chat", output_spec={"tenant_id": "t1"}, prompt_chars=10, tool_count=1
    )
    assert selection.source == "tier:mid"
    assert selection.model == ""
    assert selection.model_config_id == MID_ID
    assert is_model_config_id(selection.model_config_id)


def test_router_high_tier_hits_high_instance(tmp_path):
    router = _write_router(tmp_path, tiers=HIGH_TIER_YAML)
    selection = router.resolve(
        intent="chat",
        output_spec={"tenant_id": "t1"},
        prompt_chars=5000,
        tool_count=10,
    )
    assert selection.source == "tier:high"
    assert selection.model_config_id == HIGH_ID
    assert selection.tier == "high"


def test_router_declared_complexity_short_circuits_scoring(tmp_path):
    router = _write_router(tmp_path, tiers=HIGH_TIER_YAML)
    selection = router.resolve(
        intent="chat",
        output_spec={"tenant_id": "t1", "complexity": "high"},
        prompt_chars=1,
    )
    assert selection.source == "tier:high"
    assert selection.tier_declared == "high"


def test_router_falls_back_to_mid_when_tier_not_configured(tmp_path):
    tiers = f'  light: ""\n  mid: "{MID_ID}"\n  high: ""'
    router = _write_router(tmp_path, tiers=tiers)
    selection = router.resolve(
        intent="chat",
        output_spec={"tenant_id": "t1"},
        prompt_chars=5000,
        tool_count=10,
    )
    assert selection.source == "tier:mid"
    assert selection.model_config_id == MID_ID


def test_router_tenant_override_wins(tmp_path):
    tenants = f'  t1:\n    tiers:\n      mid: "{HIGH_ID}"'
    router = _write_router(tmp_path, tiers=HIGH_TIER_YAML, tenants=tenants)
    selection = router.resolve(
        intent="chat", output_spec={"tenant_id": "t1"}, prompt_chars=10, tool_count=1
    )
    # 0 分 → light 未配置 → 回落 mid，而 mid 被租户覆盖成 HIGH_ID
    assert selection.source == "tier:mid"
    assert selection.model_config_id == HIGH_ID


def test_router_invalid_config_id_shape_is_ignored(tmp_path):
    tiers = '  light: ""\n  mid: "gpt-5.2"\n  high: ""'
    router = _write_router(tmp_path, tiers=tiers)
    selection = router.resolve(
        intent="chat", output_spec={"tenant_id": "t1"}, prompt_chars=10, tool_count=1
    )
    assert selection.model_config_id == ""
    assert selection.source in {"env:chat", "config_fallback"}


def test_router_static_mapping_skips_tiering(tmp_path):
    router = _write_router(
        tmp_path, tiers=HIGH_TIER_YAML, static='\n  chat: "static-model"'
    )
    selection = router.resolve(intent="chat", output_spec={"tenant_id": "t1"}, prompt_chars=5000)
    assert selection.source == "by_intent"
    assert selection.model == "static-model"
    assert selection.tier_skipped_reason == "static_mapping_hit"


# ---- 计量与工厂 ---------------------------------------------------------


def test_record_tier_writes_output_spec():
    output_spec: dict = {}
    selection = ModelSelection(
        model="", source="tier:high", model_config_id=HIGH_ID, tier="high", tier_declared="light"
    )
    factory_module._record_tier(output_spec, selection)
    assert output_spec["model_tier"] == "high"
    assert output_spec["model_tier_declared"] == "light"


def test_record_tier_skips_declared_when_equal():
    output_spec: dict = {}
    selection = ModelSelection(model="", source="tier:mid", tier="mid", tier_declared="mid")
    factory_module._record_tier(output_spec, selection)
    assert output_spec["model_tier"] == "mid"
    assert "model_tier_declared" not in output_spec


def test_token_usage_record_carries_tier_defaults():
    from app.token_usage.models import TokenUsageRecord

    record = TokenUsageRecord(request_id="llm_test", tenant_id="t1", user_id="u1")
    assert record.tier == ""
    assert record.tier_declared == ""


def test_async_factory_uses_model_config_id(monkeypatch):
    import app.llm.configured_models as configured_models

    calls: dict = {}

    class _FakeRouter:
        def resolve(self, **kwargs):
            return ModelSelection(
                model="", source="tier:high", model_config_id=HIGH_ID, tier="high"
            )

    class _FakeClient:
        pass

    async def _fake_by_model_id(model_id, **kwargs):
        calls["model_id"] = model_id
        calls["tenant_id"] = kwargs.get("tenant_id")
        calls["output_spec"] = kwargs.get("output_spec")
        return _FakeClient()

    monkeypatch.setattr(factory_module, "get_model_router", lambda: _FakeRouter())
    monkeypatch.setattr(configured_models, "get_llm_client_by_model_id", _fake_by_model_id)

    output_spec = {"tenant_id": "t1"}
    client = asyncio.run(
        factory_module.aget_llm_client(intent="chat", output_spec=output_spec)
    )
    assert isinstance(client, _FakeClient)
    assert calls["model_id"] == HIGH_ID
    assert calls["tenant_id"] == "t1"
    # factory 合并后写回的是内部 output_spec，原字典不被修改；档位随合并副本下传。
    assert calls["output_spec"]["model_tier"] == "high"
