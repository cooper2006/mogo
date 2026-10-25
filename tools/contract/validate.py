"""025 US3 契约验证脚本（FR-16 ~ FR-24）。

校验 `specs/025-api-contract-hardening/contracts/<service>.yaml` 的结构合法性，
并把 `error_codes` 与各服务 `app/core/errors.py` 的稳定错误码注册表做一致性比对。

两侧验证（提供方 T035 / 消费方 T036）通过 import 本模块的 `validate_contract` /
`check_structure` 复用同一套校验逻辑，避免实现分叉。

用法：
    python3 tools/contract/validate.py                # 校验三份契约
    python3 tools/contract/validate.py --service admin-api

退出码：0 全部通过；1 存在违规（供 CI 阻断，FR-18）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO / "specs/025-api-contract-hardening" / "contracts"
SERVICES = ("admin-api", "chat-api", "document-parser")
REGISTRY_PATH = "services/{}/app/core/errors.py"
REQUIRED_TOP_KEYS = ("name", "version", "provider", "consumers", "base_path", "interactions")
REQUIRED_ITEM_KEYS = ("id", "method", "path", "responses")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
CODE_RE = re.compile(r'=\s*"(api\.[a-z0-9_.]+)"')

# 允许的字段类型（README 第 3 节）
FIELD_TYPES = {"str", "int", "float", "bool", "object", "array"}


def load_registry(service: str) -> set[str]:
    """从服务端 `app/core/errors.py` 收集所有 `api.*` 稳定错误码。"""
    path = REPO / REGISTRY_PATH.format(service)
    if not path.exists():
        return set()
    codes: set[str] = set()
    for match in CODE_RE.finditer(path.read_text(encoding="utf-8")):
        codes.add(match.group(1))
    return codes


def load_contract(service: str) -> dict:
    import yaml

    path = CONTRACTS_DIR / f"{service}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"契约文件不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_structure(data: dict, service: str, registries: dict[str, set[str]] | None = None) -> list[str]:
    """结构 + 错误码校验，返回错误消息列表（空 = 通过）。

    `registries` 可注入（测试用）；缺省从 services/<service>/app/core/errors.py 读取。
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{service}: 契约顶层必须是 mapping"]

    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            errors.append(f"{service}: 缺少顶层键 {key!r}")
    if errors:
        return errors

    registry = (registries or {}).get(service)
    if registry is None:
        registry = load_registry(service)

    if not isinstance(data["consumers"], list) or not data["consumers"]:
        errors.append(f"{service}: consumers 必须是非空数组（契约由消费方定义，FR-16）")
    if not isinstance(data["interactions"], list):
        errors.append(f"{service}: interactions 必须是数组")
        return errors

    seen_ids: set[str] = set()
    for idx, item in enumerate(data["interactions"]):
        prefix = f"{service}.interactions[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: 必须是 mapping")
            continue
        for key in REQUIRED_ITEM_KEYS:
            if key not in item:
                errors.append(f"{prefix}: 缺少 {key!r}")
        iid = item.get("id")
        if not isinstance(iid, str) or not iid:
            errors.append(f"{prefix}: id 必须是非空字符串")
        elif iid in seen_ids:
            errors.append(f"{prefix}: interaction id {iid!r} 重复（FR-17 全局唯一）")
        else:
            seen_ids.add(iid)
        method = item.get("method")
        if method not in METHODS:
            errors.append(f"{prefix}: method {method!r} 不在 {sorted(METHODS)}")
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"{prefix}: path 必须以 / 开头")
        elif "//" in path:
            errors.append(f"{prefix}: path 含空段 {path!r}")

        responses = item.get("responses")
        if not isinstance(responses, list) or not responses:
            errors.append(f"{prefix}: responses 必须是非空数组")
            continue
        for r_idx, resp in enumerate(responses):
            rprefix = f"{prefix}.responses[{r_idx}]"
            if not isinstance(resp, dict):
                errors.append(f"{rprefix}: 必须是 mapping")
                continue
            status = resp.get("status")
            if not isinstance(status, int) or not 100 <= status <= 599:
                errors.append(f"{rprefix}: status 必须是合法 HTTP 状态码，实际 {status!r}")
            # 非 2xx 应声明 error_codes（FR-17 覆盖消费方实际分支的错误码）
            codes = resp.get("error_codes") or []
            if not isinstance(codes, list):
                errors.append(f"{rprefix}: error_codes 必须是数组")
                codes = []
            for code in codes:
                if code not in registry:
                    errors.append(
                        f"{rprefix}: 错误码 {code!r} 不在 {service} 注册表"
                        f"（services/{service}/app/core/errors.py，已登记 {len(registry)} 个）"
                    )
            if status >= 400 and not codes:
                errors.append(f"{rprefix}: 非 2xx 响应应声明 error_codes（消费方实际分支）")
            # 字段类型合法性
            for field, spec in (resp.get("fields") or {}).items():
                if not isinstance(spec, dict):
                    errors.append(f"{rprefix}.fields.{field}: 字段说明必须是 mapping")
                    continue
                ftype = spec.get("type")
                if ftype not in FIELD_TYPES:
                    errors.append(
                        f"{rprefix}.fields.{field}: type {ftype!r} 不在 {sorted(FIELD_TYPES)}"
                    )
    return errors


def validate_contract(service: str) -> tuple[bool, list[str]]:
    """加载并校验单个服务的契约。返回 (是否通过, 错误消息)。"""
    try:
        data = load_contract(service)
    except FileNotFoundError as exc:
        return False, [str(exc)]
    except Exception as exc:  # noqa: BLE001 — YAML 解析失败
        return False, [f"{service}: 契约 YAML 解析失败: {exc}"]
    return not check_structure(data, service), check_structure(data, service)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=SERVICES, default=None, help="只校验指定服务")
    args = parser.parse_args(argv)

    targets = [args.service] if args.service else list(SERVICES)
    failed = False
    for service in targets:
        ok, errors = validate_contract(service)
        if ok:
            data = load_contract(service)
            print(f"{service}: contract OK — {len(data.get('interactions', []))} interactions")
        else:
            failed = True
            print(f"{service}: contract FAILED:")
            for err in errors:
                print("  " + err)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())