"""高基数标签控制（T050）。

user_id / session_id / 完整 path 等高基数值不直接作为 Prometheus label，
而是哈希到固定数量的桶中，确保单指标 label 组合 ≤ 10000。
"""
from __future__ import annotations

import hashlib

# 固定桶数：每个高基数维度映射到 50 个桶（FR-12 基数受控）
_HASH_BUCKETS = 50


def hash_to_bucket(value: str, buckets: int = _HASH_BUCKETS) -> str:
    """将任意字符串哈希到固定数量的桶中。

    Args:
        value: 高基数原始值（user_id, session_id, 完整 path 等）
        buckets: 桶数量（默认 50）

    Returns:
        桶标识（如 "bucket_0" ~ "bucket_49"）
    """
    h = hashlib.md5(value.encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % buckets
    return f"bucket_{idx}"


def sanitize_label(value: str, max_length: int = 64) -> str:
    """清理 label 值：去特殊字符、截断长度。

    Args:
        value: 原始 label 值
        max_length: 最大长度（默认 64）

    Returns:
        清理后的 label 值
    """
    # 去除 Prometheus 不允许的字符
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in value)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def get_path_template(path: str) -> str:
    """将完整 path 转为模板（FR-12 label 白名单）。

    /api/chat/sessions/123/messages → /api/chat/sessions/{id}/messages

    Args:
        path: 完整请求路径

    Returns:
        路径模板
    """
    import re
    return re.sub(r"/\d+", "/{id}", path)
