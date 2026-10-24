from __future__ import annotations
from app.infrastructure.observability.config import log_print

import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

import yaml

from app.core.config import get_settings
from app.infrastructure.observability.execution_trace import ensure_trace_id, log_trace
from app.llm.complexity import DEFAULT_TIER, TaskComplexityFeatures, evaluate_tier


#: 031 模型实例 ID 的形态（MongoDB ObjectId 字符串），见 spec R-2。
_MODEL_CONFIG_ID_RE = re.compile(r"^[0-9a-f]{24}$")


def is_model_config_id(value: Any) -> bool:
    """形态校验：是否为 031 模型实例 ID（**不是** model_name）。"""

    return bool(_MODEL_CONFIG_ID_RE.match(str(value or "")))


@dataclass(frozen=True)
class ModelSelection:
    model: str
    source: str
    #: 040：命中档位时的 031 模型实例 ID；非档位路径为空串（禁止当 model_name 用）。
    model_config_id: str = ""
    #: 040：实际服务档位（light/mid/high）；未分层路径为空串，不伪造。
    tier: str = ""
    #: 040：调用方显式声明的档位；仅在与 tier 不一致且非空时由 factory 落盘。
    tier_declared: str = ""
    #: 040：静态映射命中而未评估档位时的原因标记（R-14）。
    tier_skipped_reason: str = ""


class ModelRouter:
    """Resolve model name by task/stage/node with config-driven priority."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        base = Path(__file__).resolve().parents[1]
        self._config_path = Path(config_path) if config_path else (base / "config" / "model_routing.yaml")
        self._lock = Lock()
        self._loaded_mtime: float = -1.0
        self._cfg: Dict[str, Any] = {}

    def resolve(
        self,
        *,
        explicit_model: str | None = None,
        intent: str | None = None,
        stage: str | None = None,
        node_id: str | None = None,
        output_spec: Dict[str, Any] | None = None,
        prompt_chars: int | None = None,
        tool_count: int | None = None,
        multi_turn: int | None = None,
        skip_tiering: bool = False,
    ) -> ModelSelection:
        settings = get_settings()
        default_model = str(settings.OPENAI_MODEL or "gpt-5.2")
        env_general = str(settings.OPENAI_MODEL_GENERAL or "").strip()
        env_chat = str(settings.OPENAI_MODEL_CHAT or "").strip()
        env_coding = str(settings.OPENAI_MODEL_CODING or "").strip()

        # Qwen provider currently uses a single configured runtime model.
        if settings.USE_QWEN:
            return ModelSelection(model=str(settings.QWEN_MODEL or default_model), source="provider_default:qwen")

        if explicit_model:
            return ModelSelection(model=str(explicit_model), source="explicit")

        cfg = self._load_config()
        if not bool(cfg.get("enabled", True)):
            return ModelSelection(model=default_model, source="disabled_fallback")

        task_override = self._extract_task_override(output_spec or {})
        if task_override:
            return ModelSelection(
                model=task_override,
                source="task_override",
                tier_skipped_reason="static_mapping_hit",
            )

        by_node = cfg.get("by_node") if isinstance(cfg.get("by_node"), dict) else {}
        if node_id and str(node_id) in by_node:
            return ModelSelection(
                model=str(by_node[str(node_id)]),
                source="by_node",
                tier_skipped_reason="static_mapping_hit",
            )

        by_stage = cfg.get("by_stage") if isinstance(cfg.get("by_stage"), dict) else {}
        if stage and str(stage) in by_stage:
            return ModelSelection(
                model=str(by_stage[str(stage)]),
                source="by_stage",
                tier_skipped_reason="static_mapping_hit",
            )

        by_intent = cfg.get("by_intent") if isinstance(cfg.get("by_intent"), dict) else {}
        if intent and str(intent) in by_intent:
            return ModelSelection(
                model=str(by_intent[str(intent)]),
                source="by_intent",
                tier_skipped_reason="static_mapping_hit",
            )

        if not skip_tiering:
            tiered = self._resolve_tier(
                cfg=cfg,
                intent=intent,
                stage=stage,
                output_spec=output_spec or {},
                prompt_chars=prompt_chars,
                tool_count=tool_count,
                multi_turn=multi_turn,
            )
            if tiered is not None:
                return tiered

        models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
        model_overrides = {
            "general": env_general,
            "chat": env_chat,
            "coding": env_coding,
        }
        inferred = self._infer_model_key(intent=intent, stage=stage)
        if inferred:
            override_model = model_overrides.get(inferred) or ""
            if override_model:
                return ModelSelection(model=override_model, source=f"env:{inferred}")
            if str(models.get(inferred) or ""):
                return ModelSelection(model=str(models[inferred]), source=f"models.{inferred}")

        fallback = str(cfg.get("fallback_model") or default_model)
        return ModelSelection(model=fallback, source="config_fallback")

    # ---- 040：档位级 ------------------------------------------------------

    def _resolve_tier(
        self,
        *,
        cfg: Dict[str, Any],
        intent: str | None,
        stage: str | None,
        output_spec: Dict[str, Any],
        prompt_chars: int | None,
        tool_count: int | None,
        multi_turn: int | None,
    ) -> Optional[ModelSelection]:
        """评估档位并解析到 031 模型实例 ID；无法分层时返回 ``None`` 交给静态链。"""

        tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
        if not tiers:
            self._warn_tier_routing("tiers_missing", tier="", output_spec=output_spec)
            return None

        thresholds = (
            (cfg.get("tiering") or {}).get("thresholds")
            if isinstance(cfg.get("tiering"), dict)
            else None
        )

        declared_raw = output_spec.get("complexity")
        features = TaskComplexityFeatures(
            prompt_chars=prompt_chars,
            tool_count=tool_count,
            multi_turn=multi_turn,
            stage=str(stage or ""),
            intent=str(intent or ""),
            declared_complexity=declared_raw if isinstance(declared_raw, str) else "",
        )
        decision = evaluate_tier(features, thresholds if isinstance(thresholds, dict) else None)

        if isinstance(declared_raw, str) and declared_raw.strip() and not decision.declared:
            # R-7：非法声明值静默忽略（不进档位），但留观测点。
            self._trace(output_spec, "declared_complexity_ignored", declared=declared_raw)

        if decision.error == "features_absent":
            self._warn_tier_routing("features_absent", tier=decision.tier, output_spec=output_spec)
        elif decision.error:
            self._warn_tier_routing(
                "evaluator_error",
                tier=decision.tier,
                output_spec=output_spec,
                extra={"error": decision.error},
            )

        tenant_id = str(
            output_spec.get("tenant_id") or output_spec.get("tenantId") or "default"
        ).strip() or "default"

        resolved_tier = decision.tier
        config_id = self._tier_config_id(
            cfg=cfg, tiers=tiers, tenant_id=tenant_id, tier=resolved_tier
        )
        fallback_from = ""
        if not config_id and resolved_tier != DEFAULT_TIER:
            fallback_from = resolved_tier
            resolved_tier = DEFAULT_TIER
            config_id = self._tier_config_id(
                cfg=cfg, tiers=tiers, tenant_id=tenant_id, tier=resolved_tier
            )

        if not config_id:
            self._warn_tier_routing("tier_absent", tier=resolved_tier, output_spec=output_spec)
            return None

        if fallback_from:
            self._warn_tier_routing(
                "tier_absent",
                tier=resolved_tier,
                output_spec=output_spec,
                extra={"tier_fallback_from": fallback_from},
            )

        return ModelSelection(
            model="",
            source=f"tier:{resolved_tier}",
            model_config_id=config_id,
            tier=resolved_tier,
            tier_declared=decision.declared,
        )

    def _tier_config_id(
        self,
        *,
        cfg: Dict[str, Any],
        tiers: Dict[str, Any],
        tenant_id: str,
        tier: str,
    ) -> str:
        """租户覆盖优先，其次全局；只接受 24 位 hex 形态（R-2/R-3）。"""

        tenants = cfg.get("tenants") if isinstance(cfg.get("tenants"), dict) else {}
        tenant_cfg = tenants.get(tenant_id) if isinstance(tenants.get(tenant_id), dict) else {}
        tenant_tiers = (
            tenant_cfg.get("tiers") if isinstance(tenant_cfg.get("tiers"), dict) else {}
        )

        for candidate in (tenant_tiers.get(tier), tiers.get(tier)):
            value = str(candidate or "").strip()
            if value and is_model_config_id(value):
                return value
        return ""

    def _warn_tier_routing(
        self,
        code: str,
        *,
        tier: str,
        output_spec: Dict[str, Any],
        extra: Dict[str, Any] | None = None,
    ) -> None:
        """档位回退告警（R-5 的 code 闭集）；不写 token_usage_logs。"""

        log_print(
            f"[llm.tier_routing] {code} tier={tier} source=config",
            flush=True,
        )
        payload: Dict[str, Any] = {"code": code, "tier": tier, "source": "config"}
        if extra:
            payload.update({str(k): v for k, v in extra.items()})
        self._trace(output_spec, "tier_routing_fallback", **payload)

    def _trace(self, output_spec: Dict[str, Any], event: str, **payload: Any) -> None:
        try:
            log_trace(
                trace_id=ensure_trace_id(output_spec or {}),
                scope="llm.model_router",
                event=event,
                **payload,
            )
        except Exception as exc:  # pragma: no cover - 观测失败不影响路由
            log_print(
                f"[llm.model_router._trace] suppressed {type(exc).__name__}: {exc}",
                flush=True,
            )

    # ---- 既有静态映射 ----------------------------------------------------

    def _extract_task_override(self, output_spec: Dict[str, Any]) -> str:
        direct = str(output_spec.get("model_override") or "").strip()
        if direct:
            return direct

        task_cfg = output_spec.get("task_config") if isinstance(output_spec.get("task_config"), dict) else {}
        override = str(task_cfg.get("model_override") or "").strip()
        if override:
            return override

        agent_cfg = output_spec.get("agent_config") if isinstance(output_spec.get("agent_config"), dict) else {}
        override = str(agent_cfg.get("model_override") or "").strip()
        if override:
            return override

        return ""

    def _infer_model_key(self, *, intent: str | None, stage: str | None) -> str:
        stage_s = str(stage or "").lower()
        intent_s = str(intent or "").lower()
        if "coding" in stage_s or intent_s == "coding":
            return "coding"
        if stage_s in {"browser_planning", "research_query_refine"}:
            return "chat"
        if intent_s in {"chat", "browser_automation"}:
            return "chat"
        return "general"

    def _load_config(self) -> Dict[str, Any]:
        try:
            mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            return {}

        with self._lock:
            if self._cfg and mtime == self._loaded_mtime:
                return self._cfg
            try:
                data = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
                if not isinstance(data, dict):
                    data = {}
            except Exception as exc:
                log_print(f"[llm.model_router._load_config] suppressed {type(exc).__name__}: {exc}", flush=True)
                data = {}
            self._cfg = data
            self._loaded_mtime = mtime
            return self._cfg


_global_model_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    global _global_model_router
    if _global_model_router is None:
        _global_model_router = ModelRouter()
    return _global_model_router
