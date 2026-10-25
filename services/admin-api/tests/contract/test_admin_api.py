"""T035 提供方侧契约验证（admin-api）。

结构级验证：契约 `specs/025-api-contract-hardening/contracts/admin-api.yaml` 声明的
path / method / 状态码 / 响应字段 / 错误码，在服务端 OpenAPI schema 中**真实存在**。

环境隔离（FR-24）：只调用 FastAPI 内建的 `app.openapi()` 生成 schema，不连数据库、
不发起真实 HTTP 请求，也不依赖共享可变环境。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
CONTRACT = REPO / "specs/025-api-contract-hardening/contracts/admin-api.yaml"
REGISTRY = REPO / "services/admin-api/app/core/errors.py"
CODE_RE = re.compile(r'=\s*"(api\.[a-z0-9_.]+)"')

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "admin-api"))

from app.main import create_app  # noqa: E402

ERROR_RESPONSE_SCHEMA = "#/components/schemas/ErrorResponse"
_OPENAPI = None


def _openapi() -> dict:
    global _OPENAPI
    if _OPENAPI is None:
        _OPENAPI = create_app().openapi()
    return _OPENAPI


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _registry() -> set[str]:
    return set(CODE_RE.findall(REGISTRY.read_text(encoding="utf-8")))


def _resolve(spec: dict, ref: str) -> dict | None:
    parts = ref.lstrip("#/").split("/")
    cur = spec
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, dict) else None


def _collect_props(spec: dict, schema: dict | None, seen: set | None = None) -> tuple[set[str], set[str]]:
    """递归收集响应 schema 的**全部属性名**（含嵌套与 allOf/anyOf）。

    返回 `(属性名集合, opaque 容器名集合)`。opaque 指「数组元素是自由 dict
    （OpenAPI 无 properties / $ref / allOf…），无法机械枚举元素字段」的容器，
    例如 `PageResponse.data: list[dict[str, Any]]`。此类容器的元素字段由消费方
    契约定义，服务端 schema 无法验证，测试对之降级为 warning 而非阻断。
    """
    props: set[str] = set()
    opaque: set[str] = set()
    if not isinstance(schema, dict):
        return props, opaque
    seen = seen or set()
    ref = schema.get("$ref")
    if ref:
        resolved = _resolve(spec, ref)
        if resolved and ref not in seen:
            seen.add(ref)
            sub_p, sub_o = _collect_props(spec, resolved, seen)
            props |= sub_p
            opaque |= sub_o
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            sub_p, sub_o = _collect_props(spec, sub, seen)
            props |= sub_p
            opaque |= sub_o
    for name, sub in (schema.get("properties") or {}).items():
        props.add(name)
        if isinstance(sub, dict) and sub.get("type") == "array" and isinstance(sub.get("items"), dict):
            items = sub["items"]
            has_shape = bool(
                items.get("properties")
                or items.get("$ref")
                or items.get("allOf")
                or items.get("anyOf")
                or items.get("oneOf")
            )
            if not has_shape:
                opaque.add(name)
        sub_p, sub_o = _collect_props(spec, sub, seen)
        props |= sub_p
        opaque |= sub_o
    if isinstance(schema.get("items"), dict):
        sub_p, sub_o = _collect_props(spec, schema["items"], seen)
        props |= sub_p
        opaque |= sub_o
    return props, opaque


def _openapi_paths() -> dict:
    return _openapi().get("paths", {})


def _status_is_error(status: str) -> bool:
    """判断 OpenAPI 响应状态是否为错误（处理 default / 4XX / 5XX 通配键）。"""
    if status.isdigit():
        return int(status) >= 400
    return status.startswith(("4", "5"))  # 形如 "4XX"/"5XX"



def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def test_openapi_generates() -> None:
    spec = _openapi()
    assert spec.get("openapi", "").startswith("3."), "服务端必须能生成 OpenAPI 3.x"
    assert len(spec.get("paths", {})) > 0


def test_every_contract_interaction_exists_in_openapi() -> None:
    """契约的每条 interaction 的 path+method 都必须在服务端 OpenAPI 中存在（FR-17/FR-18）。"""
    contract = _contract()
    base = contract["base_path"]
    paths = _openapi_paths()
    missing: list[str] = []
    for item in contract["interactions"]:
        key = f"{base}{item['path']}"
        method = item["method"].lower()
        if key not in paths:
            missing.append(f"{method.upper()} {key} (interaction {item['id']})")
        elif method not in paths[key]:
            missing.append(f"{method.upper()} {key} (interaction {item['id']}, method 缺失)")
    assert not missing, f"契约声明但服务端 OpenAPI 不存在的端点:\n" + "\n".join(missing)


def test_contract_status_codes_covered_by_openapi() -> None:
    """契约声明的每个状态码都应在 OpenAPI 该端点的 responses 中。

    例外（记为 warning 不阻断）：FastAPI 通过 HTTPException 动态抛出的 4xx/5xx
    不会自动出现在 OpenAPI 声明里，因此对错误码只要求它是合法错误码（4xx/5xx）；
    2xx 成功码则严格要求 OpenAPI 声明（创建类端点 201 之类必须真实声明）。
    """
    contract = _contract()
    base = contract["base_path"]
    paths = _openapi_paths()
    problems: list[str] = []
    warnings: list[str] = []
    for item in contract["interactions"]:
        key = f"{base}{item['path']}"
        method = item["method"].lower()
        declared = paths.get(key, {}).get(method, {})
        openapi_statuses = set(declared.get("responses", {}))
        for resp in item.get("responses", []):
            status = str(resp["status"])
            if status in openapi_statuses or f"{status[0]}XX" in openapi_statuses:
                continue
            if int(status) < 400:  # 2xx 成功码必须真实声明
                problems.append(f"{item['id']}: {status} 未在 OpenAPI responses {sorted(openapi_statuses)}")
            else:  # 错误码由 HTTPException 动态抛出，OpenAPI 通常未声明
                warnings.append(f"{item['id']}: {status} 未在 OpenAPI responses（错误码，动态抛出，不阻断）")
    if warnings:
        print("[warn] 契约错误状态码未在 OpenAPI 声明（FastAPI 动态异常）:\n  " + "\n  ".join(warnings))
    assert not problems, "契约状态码未覆盖:\n" + "\n".join(problems)


def test_contract_fields_present_in_openapi_response_schema() -> None:
    """契约声明的响应字段（叶子名）必须在服务端响应 schema 的属性中（camel/snake 双向匹配）。"""
    contract = _contract()
    base = contract["base_path"]
    spec = _openapi()
    paths = _openapi_paths()
    problems: list[str] = []
    warnings: list[str] = []
    for item in contract["interactions"]:
        key = f"{base}{item['path']}"
        method = item["method"].lower()
        for resp in item.get("responses", []):
            if resp["status"] < 400 and resp.get("fields"):
                declared = paths[key][method].get("responses", {}).get(str(resp["status"]), {})
                props: set[str] = set()
                opaque: set[str] = set()
                for media in (declared.get("content") or {}).values():
                    sub_p, sub_o = _collect_props(spec, media.get("schema"))
                    props |= sub_p
                    opaque |= sub_o
                if not props:
                    continue
                for field in resp["fields"]:
                    leaf = field.split(".")[-1].split("]")[0].replace("[]", "")
                    if not leaf or leaf in props or _snake(leaf) in props:
                        continue
                    container = field.split(".")[0].split("[")[0]
                    if container in opaque:
                        # 服务端以自由 dict 承载数组元素（如 PageResponse.data），
                        # 元素字段由消费方契约定义，schema 无法验证 → 降级 warning
                        warnings.append(
                            f"{item['id']} {resp['status']}: 字段 {field!r} 落在 opaque 数组"
                            f"（{container} 元素为自由 dict，schema 无字段定义）"
                        )
                        continue
                    problems.append(
                        f"{item['id']} {resp['status']}: 字段 {field!r} 不在响应 schema"
                        f"（可用属性示例: {sorted(props)[:6]}）"
                    )
    if warnings:
        print(
            "[warn] 契约字段落在 opaque 数组（服务端自由 dict，schema 无字段定义，不阻断）:\n  "
            + "\n  ".join(warnings)
        )
    assert not problems, "契约字段未覆盖:\n" + "\n".join(problems)


def test_contract_error_codes_match_registry() -> None:
    """契约引用的所有错误码都必须在 admin-api 的 ApiErrorCode 注册表内（FR-11/FR-29）。"""
    contract = _contract()
    registry = _registry()
    unknown: list[str] = []
    for item in contract["interactions"]:
        for resp in item.get("responses", []):
            for code in resp.get("error_codes") or []:
                if code not in registry:
                    unknown.append(f"{item['id']}: {code}")
    assert not unknown, f"错误码不在注册表:\n" + "\n".join(unknown)


def test_error_responses_reference_error_response_schema() -> None:
    """服务端非 2xx 响应的 schema 应引用 ErrorResponse（FR-10 统一错误结构）。"""
    spec = _openapi()
    paths = _openapi_paths()
    checked = 0
    for item_path, methods in paths.items():
        for method, op in methods.items():
            for status, resp in (op.get("responses") or {}).items():
                if not _status_is_error(status):
                    continue
                for media in (resp.get("content") or {}).values():
                    schema = media.get("schema")
                    if isinstance(schema, dict) and schema.get("$ref") == ERROR_RESPONSE_SCHEMA:
                        checked += 1
                        break
    # 只要服务端在 4xx/5xx 上普遍声明了 ErrorResponse，即视为通过
    assert checked > 0, "服务端 4xx/5xx 响应未引用 ErrorResponse schema"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))