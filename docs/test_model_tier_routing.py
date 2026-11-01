"""040 model-tier-routing: 档位路由单测。

覆盖 SC-001（评估函数边界）、SC-002（同请求不同档位）、SC-003（安全回退）。
"""

from __future__ import annotations

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 模拟 settings
mock_settings = MagicMock()
mock_settings.OPENAI_MODEL = "gpt-4"
mock_settings.OPENAI_MODEL_GENERAL = ""
mock_settings.OPENAI_MODEL_CHAT = ""
mock_settings.OPENAI_MODEL_CODING = ""
mock_settings.USE_QWEN = False

from app.llm.complexity import (
    evaluate_tier,
    TaskComplexityFeatures,
    DEFAULT_TIERING_THRESHOLDS,
    TIER_LIGHT,
    TIER_MID,
    TIER_HIGH,
)
from app.llm.model_router import ModelRouter, ModelSelection


class TestEvaluateTier:
    """SC-001: 评估函数边界单测"""
    
    def test_empty_input_returns_light(self):
        """空输入 -> light"""
        features = TaskComplexityFeatures()
        decision = evaluate_tier(features)
        assert decision.tier == TIER_LIGHT
        assert decision.score == 0
    
    def test_short_prompt_returns_light(self):
        """短 prompt (< 4000 chars) -> light"""
        features = TaskComplexityFeatures(prompt_chars=100, tool_count=0, multi_turn=0)
        decision = evaluate_tier(features)
        assert decision.tier == TIER_LIGHT
    
    def test_long_prompt_returns_mid(self):
        """长 prompt (>= 4000 chars) -> mid"""
        features = TaskComplexityFeatures(prompt_chars=5000, tool_count=0, multi_turn=0)
        decision = evaluate_tier(features)
        assert decision.tier == TIER_MID
        assert "prompt_chars" in decision.hits
    
    def test_many_tools_returns_mid(self):
        """多工具 (>= 8) -> mid"""
        features = TaskComplexityFeatures(prompt_chars=0, tool_count=10, multi_turn=0)
        decision = evaluate_tier(features)
        assert decision.tier == TIER_MID
        assert "tool_count" in decision.hits
    
    def test_multi_turn_returns_mid(self):
        """多轮 (>= 4) -> mid"""
        features = TaskComplexityFeatures(prompt_chars=0, tool_count=0, multi_turn=5)
        decision = evaluate_tier(features)
        assert decision.tier == TIER_MID
        assert "multi_turn" in decision.hits
    
    def test_coding_stage_returns_mid(self):
        """coding stage -> mid"""
        features = TaskComplexityFeatures(stage="coding")
        decision = evaluate_tier(features)
        assert decision.tier == TIER_MID
        assert "stage" in decision.hits
    
    def test_high_score_returns_high(self):
        """多特征命中 -> high"""
        features = TaskComplexityFeatures(
            prompt_chars=5000,
            tool_count=10,
            multi_turn=5,
            stage="coding"
        )
        decision = evaluate_tier(features)
        assert decision.tier == TIER_HIGH
        assert decision.score >= 2
    
    def test_declared_complexity_priority(self):
        """显式声明优先于评分"""
        features = TaskComplexityFeatures(
            declared_complexity="high",
            prompt_chars=100
        )
        decision = evaluate_tier(features)
        assert decision.tier == TIER_HIGH
        assert decision.declared == "high"
    
    def test_features_absent_returns_mid(self):
        """未提供特征 -> mid + features_absent 告警"""
        features = TaskComplexityFeatures()  # 所有字段 None
        decision = evaluate_tier(features)
        assert decision.tier == TIER_MID
        assert decision.error == "features_absent"
    
    def test_invalid_declared_ignored(self):
        """非法声明值静默忽略"""
        features = TaskComplexityFeatures(
            declared_complexity="INVALID",
            prompt_chars=100
        )
        decision = evaluate_tier(features)
        assert decision.declared == ""
        # 继续走评分逻辑
        assert decision.tier == TIER_LIGHT
    
    def test_custom_thresholds(self):
        """自定义阈值覆盖"""
        features = TaskComplexityFeatures(prompt_chars=100, tool_count=0, multi_turn=0)
        thresholds = {"prompt_chars_high": 50}  # 降低阈值
        decision = evaluate_tier(features, thresholds)
        assert decision.tier == TIER_MID


class TestModelRouter:
    """SC-002: 同请求不同特征落入不同档位"""
    
    @pytest.fixture
    def router(self, tmp_path):
        """创建带配置文件的 router"""
        config = tmp_path / "model_routing.yaml"
        config.write_text("""
enabled: true
tiers:
  light: "000000000000000000000001"
  mid: "000000000000000000000002"
  high: "000000000000000000000003"
tiering:
  thresholds: {}
models:
  general: gpt-4
  chat: gpt-4
  coding: gpt-4
fallback_model: gpt-4
""")
        return ModelRouter(config_path=config)
    
    def test_short_request_routing(self, router):
        """短请求 -> light"""
        selection = router.resolve(
            prompt_chars=100,
            tool_count=0,
            multi_turn=0
        )
        assert selection.tier == TIER_LIGHT
        assert selection.source == f"tier:{TIER_LIGHT}"
    
    def test_coding_request_routing(self, router):
        """编码请求 -> high"""
        selection = router.resolve(
            prompt_chars=5000,
            tool_count=10,
            multi_turn=5,
            stage="coding"
        )
        assert selection.tier == TIER_HIGH
        assert selection.source == f"tier:{TIER_HIGH}"
    
    def test_mixed_request_routing(self, router):
        """中等请求 -> mid"""
        selection = router.resolve(
            prompt_chars=2000,
            tool_count=3,
            multi_turn=2
        )
        assert selection.tier == TIER_MID
    
    def test_explicit_model_skips_tiering(self, router):
        """显式模型跳过档位评估"""
        selection = router.resolve(
            explicit_model="gpt-5",
            prompt_chars=5000
        )
        assert selection.tier == ""
        assert selection.source == "explicit"
    
    def test_missing_tiers_fallback(self, tmp_path):
        """缺失 tiers 配置安全回退"""
        config = tmp_path / "model_routing.yaml"
        config.write_text("""
enabled: true
models:
  general: gpt-4
fallback_model: gpt-4
""")
        router = ModelRouter(config_path=config)
        selection = router.resolve(prompt_chars=5000)
        # 应回退到 config_fallback 而非 tier
        assert selection.tier == ""
    
    def test_tier_config_id_validation(self, router):
        """model_config_id 必须是 24 位 hex"""
        # 配置中已保证，此处验证 resolve 返回正确的 model_config_id
        selection = router.resolve(prompt_chars=100)
        assert selection.model_config_id == "000000000000000000000001"
        assert len(selection.model_config_id) == 24


class TestSafetyFallback:
    """SC-003: 安全回退验证"""
    
    def test_invalid_config_returns_default(self, tmp_path):
        """无效配置返回默认档位"""
        config = tmp_path / "model_routing.yaml"
        config.write_text("invalid yaml: [")
        router = ModelRouter(config_path=config)
        selection = router.resolve(prompt_chars=100)
        assert selection.model == "gpt-4"
        assert selection.source != "tier:*"
    
    def test_missing_config_returns_default(self, tmp_path):
        """缺失配置文件返回默认"""
        config = tmp_path / "nonexistent.yaml"
        router = ModelRouter(config_path=config)
        selection = router.resolve(prompt_chars=100)
        assert selection.model == "gpt-4"
    
    def test_disabled_routing_returns_default(self, tmp_path):
        """禁用路由返回默认"""
        config = tmp_path / "model_routing.yaml"
        config.write_text("""
enabled: false
fallback_model: gpt-4
""")
        router = ModelRouter(config_path=config)
        selection = router.resolve(prompt_chars=5000)
        assert selection.source == "disabled_fallback"
        assert selection.tier == ""
