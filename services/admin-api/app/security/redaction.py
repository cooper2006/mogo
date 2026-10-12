"""FR-20 / FR-21 (QF-659–666) 日志脱敏与响应裁剪.

- :func:`redact_mapping` / :func:`redact` — 递归脱敏 dict/list/标量；键名命中敏感模式即
  mask（默认 ``***REDACTED***``）或整体移除。
- :func:`redact_text` — 对已序列化的字符串做正则脱敏（``key=value``、
  ``"key": "value"``、JWT Bearer、URL query 中的 token 参数）。
- :func:`filter_response` — 按调用者权限裁剪响应字段（FR-21）。
- :func:`assert_no_sensitive` — 供测试与调试断言，确保某段日志不含敏感值。

设计取舍：
1. **键名匹配用正则而不是精确白名单**——真实数据里敏感键写法五花八门
   （``password`` / ``passwd`` / ``pwd`` / ``newPassword`` / ``sso_token``），
   精确白名单必然漏；正则误伤（把非敏感键脱掉）的代价远低于漏脱。
2. **默认 mask 而不是删除**——保留字段结构便于排障；需要隐藏存在性时用
   ``mode="remove"``。
3. **有深度上限**——防止递归脱敏把服务自身拖垮（递归炸弹）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

MASK = "***REDACTED***"
MODE_MASK = "mask"
MODE_REMOVE = "remove"
SUPPORTED_MODES: tuple[str, ...] = (MODE_MASK, MODE_REMOVE)

DEFAULT_MAX_DEPTH = 16

# 命中即视为敏感的键名模式（不区分大小写、下划线/连字符/驼峰等价）
SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    r"password",
    r"passwd",
    r"pwd",
    r"token",
    r"secret",
    r"api[_\-]?key",
    r"apikey",
    r"access[_\-]?key",
    r"secret[_\-]?access[_\-]?key",
    r"authorization",
    r"auth[_\-]?header",
    r"cookie",
    r"credential",
    r"otp",
    r"totp",
    r"mfa[_\-]?secret",
    r"refresh[_\-]?token",
    r"session[_\-]?id",
    r"signature",
    r"private[_\-]?key",
    r"client[_\-]?secret",
)

_SENSITIVE_KEY_RE = re.compile("|".join(SENSITIVE_KEY_PATTERNS), re.IGNORECASE)

# 文本脱敏用的正则
_TEXT_KEY_VALUE_RE = re.compile(
    r"(?P<key>[\"']?(?:" + "|".join(SENSITIVE_KEY_PATTERNS) + r")[\"']?\s*[:=\s]+\s*)"
    r"(?P<quote>[\"']?)(?P<val>[^\"',\s}&]+)(?P=quote)",
    re.IGNORECASE,
)
_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?P<key>[\"']?Authorization[\"']?\s*[:=]\s*)(?P<value>[^;,\n\r}\"]+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)")
_URL_TOKEN_RE = re.compile(
    r"(?i)(?P<base>[\w\-]*token[\w\-]*)=(?P<val>[^&\s'\"]+)"
)


class RedactionError(ValueError):
    """脱敏配置非法。"""


@dataclass(frozen=True)
class RedactionConfig:
    """脱敏配置。"""

    mode: str = MODE_MASK
    mask: str = MASK
    max_depth: int = DEFAULT_MAX_DEPTH
    # 需要额外脱敏的键名（精确匹配，忽略大小写）
    extra_sensitive_keys: tuple[str, ...] = ()
    # 白名单：这些键即使命中模式也不脱敏
    exempt_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in SUPPORTED_MODES:
            raise RedactionError(f"unsupported mode {self.mode!r}; expected one of {SUPPORTED_MODES}")
        if self.max_depth < 1:
            raise RedactionError("max_depth must be >= 1")
        if not self.mask:
            raise RedactionError("mask must be non-empty")
        # 键名归一化（frozen dataclass 需用 object.__setattr__）
        object.__setattr__(self, "exempt_keys", tuple(k.lower() for k in self.exempt_keys))
        object.__setattr__(
            self, "extra_sensitive_keys", tuple(k.lower() for k in self.extra_sensitive_keys)
        )


DEFAULT_CONFIG = RedactionConfig()


def _normalize_key(key: str) -> str:
    return key.lower().replace("-", "_").replace(" ", "_")


def is_sensitive_key(key: object, config: RedactionConfig = DEFAULT_CONFIG) -> bool:
    """判断一个字段名是否敏感。"""
    if not isinstance(key, str) or not key:
        return False
    normalized = _normalize_key(key)
    if normalized in config.exempt_keys:
        return False
    for extra in config.extra_sensitive_keys:
        if normalized == extra or normalized in extra:
            return True
    return bool(_SENSITIVE_KEY_RE.search(normalized))


def redact(
    value: Any,
    *,
    config: RedactionConfig = DEFAULT_CONFIG,
    _depth: int = 0,
) -> Any:
    """递归脱敏任意 JSON 可表达的结构（FR-20）。

    - dict：敏感键 mask/remove，其余键递归处理；
    - list/tuple：逐元素递归（tuple 返回 list，JSON 语义下等价）；
    - 标量：原样返回。

    超过 ``max_depth`` 的深层结构被整体 mask，避免递归炸弹。
    """
    if _depth > config.max_depth:
        return config.mask if config.mode == MODE_MASK else None

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if is_sensitive_key(key_s, config):
                if config.mode == MODE_REMOVE:
                    continue
                result[key] = config.mask
                continue
            result[key] = redact(item, config=config, _depth=_depth + 1)
        return result

    if isinstance(value, list):
        return [redact(item, config=config, _depth=_depth + 1) for item in value]

    if isinstance(value, tuple):
        return [redact(item, config=config, _depth=_depth + 1) for item in value]

    return value


def redact_mapping(
    value: Any,
    *,
    mode: str = MODE_MASK,
    mask: str = MASK,
    max_depth: int = DEFAULT_MAX_DEPTH,
    extra_sensitive_keys: tuple[str, ...] = (),
    exempt_keys: tuple[str, ...] = (),
) -> Any:
    """:func:`redact` 的关键字参数版本（给日志调用点用）。"""
    config = RedactionConfig(
        mode=mode,
        mask=mask,
        max_depth=max_depth,
        extra_sensitive_keys=extra_sensitive_keys,
        exempt_keys=exempt_keys,
    )
    return redact(value, config=config)


def _sub_value(match: "re.Match[str]", mask: str) -> str:
    """统一替换：保留 key 与引号，只替换值。"""
    return f"{match.group('key')}{match.group('quote')}{mask}"


def redact_text(
    text: str,
    *,
    mask: str = MASK,
    extra_sensitive_keys: tuple[str, ...] = (),
) -> str:
    """对字符串做正则脱敏（FR-20，用于已拼接的日志行与错误消息）。

    覆盖四种常见形态：`key=value`、`"key": "value"`、`Bearer <jwt>`、URL query
    中的 token 参数。
    """
    if not isinstance(text, str) or not text:
        return text
    text = _AUTHORIZATION_HEADER_RE.sub(lambda m: f"{m.group('key')}{mask}", text)
    text = _BEARER_RE.sub(lambda m: f"Bearer {mask}", text)
    text = _URL_TOKEN_RE.sub(lambda m: f"{m.group('base')}={mask}", text)
    text = _TEXT_KEY_VALUE_RE.sub(lambda m: _sub_value(m, mask), text)

    extras = [k for k in extra_sensitive_keys if k]
    if extras:
        extra_re = re.compile(
            r"(?P<key>[\"']?(" + "|".join(re.escape(k) for k in extras) + r")[\"']?\s*[:=\s]+\s*)"
            r"(?P<quote>[\"']?)(?P<val>[^\"',\s}]+)(?P=quote)",
            re.IGNORECASE,
        )
        text = extra_re.sub(lambda m: _sub_value(m, mask), text)
    return text


def redact_json(obj: Any, **kwargs: Any) -> str:
    """脱敏后序列化为 JSON 字符串（日志落盘/上报用）。"""
    redacted = redact_mapping(obj, **kwargs)
    return json.dumps(redacted, ensure_ascii=False, default=str, sort_keys=True)


def _field_allowed(field_name: str, allowed: set[str], deny_all: bool) -> bool:
    if deny_all:
        return False
    if not allowed:
        # 未给 allowed 名单时不裁剪（保守起见返回原样），显式行为优于隐式删字段。
        return True
    return field_name in allowed


def filter_response(
    payload: Any,
    allowed_fields: set[str] | frozenset[str] | tuple[str, ...] | None,
    *,
    deny_all: bool = False,
) -> Any:
    """按调用者权限裁剪响应字段（FR-21）。

    Args:
        payload: 响应体（通常是最外层 dict）。
        allowed_fields: 允许保留的字段名集合。``None`` 或空集表示不裁剪
            （除 ``deny_all=True`` 外）。
        deny_all: True 时除 ``allowed_fields`` 命中的字段外全部剔除。

    裁剪是浅层的（只作用于最外层 dict），因为响应裁剪的目标是"调用者不该看的
    兄弟字段"，而非深层嵌套的敏感值——深层敏感值由 :func:`redact_mapping` 负责，
    两者分工不重叠。
    """
    if deny_all and not allowed_fields:
        return {}
    if not isinstance(payload, dict):
        return payload
    if not allowed_fields:
        return payload
    allowed = set(allowed_fields)
    return {key: value for key, value in payload.items() if str(key) in allowed}


def redact_response(
    payload: Any,
    allowed_fields: set[str] | frozenset[str] | tuple[str, ...] | None = None,
    *,
    deny_all: bool = False,
    redaction_config: RedactionConfig = DEFAULT_CONFIG,
) -> Any:
    """FR-20 + FR-21 组合：先裁剪再脱敏。"""
    trimmed = filter_response(payload, allowed_fields, deny_all=deny_all)
    return redact(trimmed, config=redaction_config)


def assert_no_sensitive(
    value: Any,
    *,
    extra_sensitive_keys: tuple[str, ...] = (),
    known_secrets: tuple[str, ...] = (),
) -> None:
    """断言某段数据不含敏感键或已知的敏感值（供测试使用）。

    Raises:
        AssertionError: 发现命中。
    """
    config = RedactionConfig(extra_sensitive_keys=extra_sensitive_keys)
    if isinstance(value, dict):
        for key in value:
            if is_sensitive_key(str(key), config):
                raise AssertionError(f"sensitive key leaked in output: {key!r}")
    if isinstance(value, str):
        for secret in known_secrets:
            if secret and secret in value:
                raise AssertionError(f"known secret value leaked in output: {secret[:6]}...")


def leak_report(value: Any, *, config: RedactionConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    """返回一份"会被脱敏的键"清单，用于安全审计自检（不改动输入）。"""
    hits: list[str] = []

    def _walk(node: Any, path: str, depth: int) -> None:
        if depth > config.max_depth:
            return
        if isinstance(node, dict):
            for key, item in node.items():
                key_path = f"{path}.{key}" if path else str(key)
                if is_sensitive_key(str(key), config):
                    hits.append(key_path)
                _walk(item, key_path, depth + 1)
        elif isinstance(node, (list, tuple)):
            for idx, item in enumerate(node):
                _walk(item, f"{path}[{idx}]", depth + 1)

    _walk(value, "", 0)
    return {"sensitive_keys": hits, "count": len(hits)}


__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_MAX_DEPTH",
    "MASK",
    "MODE_MASK",
    "MODE_REMOVE",
    "RedactionConfig",
    "RedactionError",
    "SENSITIVE_KEY_PATTERNS",
    "SUPPORTED_MODES",
    "assert_no_sensitive",
    "filter_response",
    "is_sensitive_key",
    "leak_report",
    "redact",
    "redact_json",
    "redact_mapping",
    "redact_response",
    "redact_text",
]
