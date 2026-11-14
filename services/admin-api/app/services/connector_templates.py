"""连接器模板种子（041-connector-market FR-001/FR-005/FR-006）。

模板是仓库内 YAML 文件（`app/connector_templates/*.yaml`），一个文件一个模板、
自带 `version`。目录按 mtime 热加载，改 YAML 不需要重启服务。

种子纪律（FR-006）：模板里只允许**占位凭证**（`<...>` 形式）。加载时若发现某个
参数看起来像真实凭据（长随机串、无占位标记），该模板整体跳过并告警——宁可少一个
模板，也不能把密钥提交进仓库。

从模板创建工具（FR-004）必须落**既有** `external_tools` 存储与注入路径，因此本模块
只负责把模板渲染成 `external_tools.config` + 创建入参，不自己造存储。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import logging

import yaml


logger = logging.getLogger(__name__)


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "connector_templates"

# 模板必填字段（缺一个就跳过该文件）。
REQUIRED_FIELDS = (
    "id",
    "version",
    "category",
    "name",
    "description",
    "auth_type",
    "config_template",
    "params",
)
VALID_AUTH_TYPES = ("none", "bearer", "api_key")
VALID_PARAM_LOCATIONS = ("path", "query", "body", "headers")
VALID_PARAM_TYPES = ("string", "number", "integer", "boolean")

# chat-api 的 inputSchema 用首字母大写的 location 词。
_LOCATION_LABELS = {
    "path": "Path",
    "query": "Query",
    "body": "Body",
    "headers": "Header",
}

# 看起来像占位符的取值；都不匹配就有理由怀疑是真实凭据。
_PLACEHOLDER_HINTS = (
    "<",
    ">",
    "your",
    "example",
    "placeholder",
    "changeme",
    "xxx",
    "xxx",
    "token-here",
    "${",
)
_DEFAULT_TIMEOUT_SECONDS = 30

_lock = threading.Lock()
_cache: dict[str, Any] = {"stamp": None, "templates": {}, "issues": []}


def _looks_like_placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if any(hint in lowered for hint in _PLACEHOLDER_HINTS):
        return True
    # 纯字母数字但很长、含大小写与数字混排 → 更像真实 token。
    if len(text) >= 24 and re.fullmatch(r"[A-Za-z0-9_\-]+", text):
        return False
    return True


def _validate_template(raw: dict[str, Any], *, source: str) -> list[str]:
    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in raw or raw.get(field) in (None, "", [], {}):
            problems.append(f"缺少字段 {field}")
    if problems:
        return problems

    if not isinstance(raw.get("name"), dict) or not isinstance(raw.get("description"), dict):
        problems.append("name/description 必须是 {zh, en} 双语文档")
    if str(raw.get("auth_type")) not in VALID_AUTH_TYPES:
        problems.append(f"auth_type 只支持 {'/'.join(VALID_AUTH_TYPES)}")
    config = raw.get("config_template")
    if not isinstance(config, dict) or not str(config.get("url") or "").strip():
        problems.append("config_template.url 必填")
    else:
        allowed = {"url", "method", "headers"}
        unknown = set(config) - allowed
        if unknown:
            problems.append(f"config_template 不支持字段 {sorted(unknown)}")

    params = raw.get("params")
    if not isinstance(params, list) or not params:
        problems.append("params 至少一项")
        return problems

    seen: set[str] = set()
    for index, spec in enumerate(params):
        if not isinstance(spec, dict):
            problems.append(f"params[{index}] 必须是对象")
            continue
        key = str(spec.get("key") or "").strip()
        if not key:
            problems.append(f"params[{index}] 缺少 key")
            continue
        if key in seen:
            problems.append(f"params 大量重复 key {key}")
        seen.add(key)
        if str(spec.get("in") or "query") not in VALID_PARAM_LOCATIONS:
            problems.append(f"params[{index}].in 只支持 {'/'.join(VALID_PARAM_LOCATIONS)}")
        if str(spec.get("type") or "string") not in VALID_PARAM_TYPES:
            problems.append(f"params[{index}].type 只支持 {'/'.join(VALID_PARAM_TYPES)}")
        if not isinstance(spec.get("label"), dict):
            problems.append(f"params[{index}].label 必须是 {{zh, en}}")
        # FR-006：种子只存占位凭证。
        if spec.get("secret") and spec.get("example") is not None:
            if not _looks_like_placeholder(spec.get("example")):
                problems.append(f"params[{index}] 的 example 疑似真实凭据（{source}）")
    return problems


def _load_one(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 单个坏文件不能拖垮整目录
        return None, [f"{path.name}: YAML 解析失败（{exc}）"]
    if not isinstance(raw, dict):
        return None, [f"{path.name}: 顶层必须是对象"]
    problems = _validate_template(raw, source=path.name)
    if problems:
        return None, [f"{path.name}: {problem}" for problem in problems]
    template = dict(raw)
    template["id"] = str(raw["id"]).strip()
    template["version"] = int(raw.get("version") or 1)
    template["category"] = str(raw.get("category") or "").strip()
    template["source_file"] = path.name
    return template, []


def _stamp() -> tuple[tuple[str, float], ...]:
    return tuple(
        sorted((path.name, path.stat().st_mtime) for path in TEMPLATES_DIR.glob("*.yaml"))
    )


def load_templates(*, force: bool = False) -> dict[str, dict[str, Any]]:
    """Return `{template_id: template}`, reloading when the directory changed."""

    with _lock:
        stamp = _stamp()
        if not force and _cache["stamp"] == stamp and _cache["templates"]:
            return dict(_cache["templates"])

        templates: dict[str, dict[str, Any]] = {}
        issues: list[str] = []
        for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
            template, problems = _load_one(path)
            issues.extend(problems)
            if template is None:
                continue
            if template["id"] in templates:
                issues.append(f"{path.name}: 模板 id {template['id']} 重复，已跳过")
                continue
            templates[template["id"]] = template
        if issues:
            for issue in issues:
                logger.warning("connector template skipped: %s", issue)
        _cache.update({"stamp": stamp, "templates": templates, "issues": issues})
        return dict(templates)


def load_issues() -> list[str]:
    """Last load's skipped-template reasons (for diagnostics endpoints)."""

    load_templates()
    return list(_cache["issues"])


def get_template(template_id: str) -> dict[str, Any] | None:
    return load_templates().get(str(template_id or "").strip())


def _matches_keyword(template: dict[str, Any], keyword: str) -> bool:
    needle = keyword.strip().lower()
    if not needle:
        return True
    haystack = [
        template.get("id", ""),
        template.get("category", ""),
        str((template.get("name") or {}).get("zh", "")),
        str((template.get("name") or {}).get("en", "")),
        str((template.get("description") or {}).get("zh", "")),
        str((template.get("description") or {}).get("en", "")),
    ]
    return any(needle in str(item).lower() for item in haystack)


def list_templates(*, category: str = "", keyword: str = "") -> list[dict[str, Any]]:
    wanted = str(category or "").strip()
    rows = [
        template
        for template in load_templates().values()
        if (not wanted or template.get("category") == wanted) and _matches_keyword(template, keyword)
    ]
    rows.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("id") or "")))
    return rows


def credential_managed(template: dict[str, Any]) -> bool:
    """Whether the credential can live in an encrypted `config.authToken`.

    chat-api only injects credentials as request headers (`bearer` → Authorization,
    `api_key` → the configured header). Templates whose secret is carried inside the
    URL (DingTalk webhook token, Slack path secret, ClickHouse token) cannot be
    managed that way, so they degrade honestly instead of leaking into `config.url`.
    """

    auth_type = str(template.get("auth_type") or "none")
    if auth_type not in ("bearer", "api_key"):
        return False
    for spec in template.get("params") or []:
        if not spec.get("secret"):
            continue
        if str(spec.get("in") or "query") not in ("headers", "query"):
            return False
    return True


def credential_params(template: dict[str, Any]) -> list[dict[str, Any]]:
    return [spec for spec in template.get("params") or [] if spec.get("secret")]


def validate_values(template: dict[str, Any], values: dict[str, Any] | None) -> list[str]:
    """Per-field validation errors (empty list = OK)."""

    provided = values or {}
    errors: list[str] = []
    for spec in template.get("params") or []:
        key = str(spec.get("key") or "")
        raw = provided.get(key)
        text = "" if raw is None else str(raw).strip()
        if spec.get("required") and not text:
            errors.append(f"缺少必填参数 {key}")
            continue
        if not text:
            continue
        kind = str(spec.get("type") or "string")
        if kind == "integer":
            try:
                int(text)
            except ValueError:
                errors.append(f"参数 {key} 必须是整数")
        elif kind == "number":
            try:
                float(text)
            except ValueError:
                errors.append(f"参数 {key} 必须是数字")
        elif kind == "boolean" and text.lower() not in ("true", "false", "1", "0"):
            errors.append(f"参数 {key} 必须是布尔值")
    return errors


def _render_url(template: dict[str, Any], values: dict[str, Any]) -> tuple[str, str]:
    """Return `(url, auth_token)` after substituting the template placeholders."""

    config_template = template.get("config_template") or {}
    url = str(config_template.get("url") or "")
    auth_type = str(template.get("auth_type") or "none")
    managed = credential_managed(template)
    auth_token = ""

    for spec in template.get("params") or []:
        key = str(spec.get("key") or "")
        if not key:
            continue
        placeholder = "${" + key + "}"
        if placeholder not in url:
            # Header-carried credentials never appear in the URL but must still
            # land in config.authToken so 034 can encrypt them.
            if spec.get("secret") and managed:
                auth_token = str(values.get(key) or "").strip()
            continue
        where = str(spec.get("in") or "query")
        if spec.get("secret"):
            if managed:
                # 托管凭证：值进 config.authToken（034 加密），URL 里不留占位。
                auth_token = str(values.get(key) or "").strip()
                url = url.replace(placeholder, "")
            else:
                # 无法托管：保留 {key} 交给调用期传参，绝不把值写进 config。
                url = url.replace(placeholder, "{" + key + "}")
        elif where in ("path", "query"):
            url = url.replace(placeholder, "{" + key + "}")
        else:
            # body/header 参数不进 URL。
            url = url.replace(placeholder, "")

    # 摘除占位后可能留下空的 query 尾。
    url = re.sub(r"[?&]+$", "", url).replace("?&", "?")
    if auth_type == "none":
        auth_token = ""
    return url, auth_token


def render_config(
    template: dict[str, Any],
    values: dict[str, Any] | None = None,
    *,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Render an `external_tools.config` from the template + user supplied values."""

    provided = values or {}
    config_template = template.get("config_template") or {}
    url, auth_token = _render_url(template, provided)
    method = str(config_template.get("method") or "POST").strip().upper() or "POST"
    auth_type = str(template.get("auth_type") or "none")

    config: dict[str, Any] = {
        "url": url,
        "method": method,
        "timeoutSeconds": max(1, int(timeout_seconds)),
    }

    headers = {
        str(key): str(value)
        for key, value in (config_template.get("headers") or {}).items()
        if str(key).strip()
    }
    if headers:
        config["headers"] = headers

    if auth_type in ("bearer", "api_key"):
        config["authType"] = auth_type
        config["authToken"] = auth_token
        if auth_type == "api_key":
            config["apiKeyHeader"] = str(template.get("api_key_header") or "X-API-Key")

    config["inputSchema"] = [
        {
            "name": str(spec.get("key") or ""),
            "location": _LOCATION_LABELS.get(str(spec.get("in") or "query"), "Query"),
            "type": str(spec.get("type") or "string"),
            "required": bool(spec.get("required")),
            "description": str((spec.get("description") or {}).get("zh") or ""),
        }
        for spec in template.get("params") or []
        if spec.get("key")
    ]
    return config


def template_view(template: dict[str, Any]) -> dict[str, Any]:
    """Public shape returned by the market API (camelCase, no source paths)."""

    return {
        "id": template.get("id"),
        "version": template.get("version"),
        "category": template.get("category"),
        "name": template.get("name") or {},
        "description": template.get("description") or {},
        "authType": template.get("auth_type") or "none",
        "credentialKey": template.get("credential_key") or "",
        "apiKeyHeader": template.get("api_key_header") or "",
        "credentialManaged": credential_managed(template),
        "params": [
            {
                "key": spec.get("key"),
                "label": spec.get("label") or {},
                "type": spec.get("type") or "string",
                "required": bool(spec.get("required")),
                "secret": bool(spec.get("secret")),
                "in": spec.get("in") or "query",
                "description": spec.get("description") or {},
                "example": spec.get("example") or "",
            }
            for spec in template.get("params") or []
        ],
        "testHint": template.get("test_hint") or {},
    }


def template_categories() -> list[str]:
    return sorted({str(item.get("category") or "") for item in load_templates().values() if item.get("category")})
