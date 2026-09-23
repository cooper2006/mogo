from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TokenUsageRecord(BaseModel):
    request_id: str
    user_request_id: str = ""
    main_id: str = "default"
    user_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    stage: str = ""
    intent: str = ""
    node_id: str = ""
    status: str = "completed"
    model_name: str = ""
    model_id: str = ""
    prompt: str = ""
    request_title_zh: str = ""
    request_title_en: str = ""
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    response_payload: Dict[str, Any] = Field(default_factory=dict)
    start_time: int = 0
    end_time: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    push_status: str = "pending"
    push_error: str = ""
    # 007 US4 (T018/T019): estimated cost of the call (USD, token count x 008 MODEL_PRICES unit price).
    cost_estimate_usd: float = 0.0
    # 007 FR-7: resilience events (failover_from / failover_to / degradation_step)
    # carried on the same record; None means no resilience event occurred.
    resilience_events: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TokenUsagePushResult(BaseModel):
    enabled: bool = False
    pushed: bool = False
    error: str = ""
