"""Cross-service fail-closed enforcement utilities.

Provides:
- DEFAULT_DENY / DEFAULT_ALLOW: 统一的「未知 → 拒绝」语义
- enforce_fail_closed(): 值 indeterminate (None) 时强制返回 False (deny)
- FAIL_OPEN_EXEMPT_COMMENT: 用于静态扫描的豁免注释标记

该模块是所有治理层共用的缺省 deny 常量与兜底逻辑的单一事实来源。
"""

# 统一的「未知 → 拒绝」语义
DEFAULT_DENY = True  # 原名 DENY_BY_DEFAULT，消除 double-negative 认知负担
DEFAULT_ALLOW = False

# 豁免标记（供静态扫描识别）
FAIL_OPEN_EXEMPT_COMMENT = "fail-open-exempt:"


def enforce_fail_closed(value: bool, context: str = "", exempt_comment: str = "") -> bool:
    """确保一个决策在 indeterminate（未定义）时默认拒绝。

    自遵循憲法 III（Security and Data Protection）：
    - 當 value 为 None（例如规则缺失、配置未知、异常回退）时，
      返回 False（deny），并记录 warning 以便审计。
    - 如果设置了 exempt_comment 且包含 FAIL_OPEN_EXEMPT_COMMENT，
      则返回原始布尔值（放行由显式豁免标记），
      否则一律按 deny 处理。
    - 任何其他情況下，value 被转换为 bool 后返回。

    Args:
        value: computed decision (True=allow, False=deny)
        context: human-readable description of where this was decided
        exempt_comment: if set, marks this invocation as intentionally allow-by-default

    Returns:
        The decision, coerced to deny if value is indeterminate (None).
    """
    if value is None:
        import logging

        logging.getLogger(__name__).warning(
            "fail-closed coercion: indeterminate decision at %s → deny", context
        )
        return False

    if exempt_comment and FAIL_OPEN_EXEMPT_COMMENT in exempt_comment:
        return bool(value)

    return bool(value)