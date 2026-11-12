from __future__ import annotations

import random
from datetime import datetime, timezone


# 模型定价表（唯一权威来源）
# 与 admin-api dashboard.py / analytics.py / chat-api resilience/pricing.py 三份历史手抄
# 副本核对一致后收敛于此（见 specs/058 T014/T015）。改价只改这一处。
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.5, 1.5),
    "gpt-5.2-chat": (35.0, 110.0),
    "gpt-5.2": (35.0, 110.0),
    "gpt-5.4": (100.0, 300.0),
    "qwen3-vl-plus": (10.0, 10.0),
}

# 未知模型兜底单价（USD / 1M tokens，input, output），与三份历史副本一致。
DEFAULT_PRICE = (10.0, 30.0)

# TTL 常量
DEFAULT_TTL_SECONDS = 300.0
IDLE_TIMEOUT_SECONDS = 1800.0

# 时间工具
def utc_now() -> datetime:
    """返回 timezone-aware UTC datetime，供所有服务统一使用。"""
    return datetime.now(timezone.utc)


# 归一化配额默认值
points_unlimited_default = True