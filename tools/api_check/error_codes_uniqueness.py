#!/usr/bin/env python3
"""025 T007 — 跨服务错误码唯一性检查（FR-29，CI 执行）。

规则：
1. **通用命名空间 `api.<error>`**（如 `api.not_found`）：允许在多个服务的
   `app/core/errors.py` 中重复定义，但各服务 `DEFAULT_HTTP_STATUS` 的映射必须一致
   （同义同码；状态码漂移即失败）。
2. **专属命名空间**：`api.admin.*` / `api.chat.*` / `api.parser.*` 前缀分属对应服务，
   某服务不得在自家 errors.py 里定义他人前缀的码；专属码跨服务全局唯一。
3. 每个服务 errors.py 中定义的每个 code 必须登记在该服务的
   `app/core/errors_codes.md` 字典表里（四字段文档化，FR-30 的最小强制）。
4. 每个 code 的命名段只允许 [a-z0-9_.]，必须以 `api.` 开头。

退出码：0 通过；1 发现违规（打印明细）。
用法：python3 tools/api_check/error_codes_uniqueness.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SERVICES = {
    "admin-api": ("services/admin-api/app/core/errors.py", "services/admin-api/app/core/errors_codes.md"),
    "chat-api": ("services/chat-api/app/core/errors.py", "services/chat-api/app/core/errors_codes.md"),
    "document-parser": (
        "services/document-parser/app/core/errors.py",
        "services/document-parser/app/core/errors_codes.md",
    ),
}
OWNER_PREFIX = {
    "admin-api": "api.admin.",
    "chat-api": "api.chat.",
    "document-parser": "api.parser.",
}
CODE_RE = re.compile(r'^[a-z0-9_.]+$', re.S)
ENUM_ASSIGN_RE = re.compile(r'=\s*"(api\.[a-z0-9_.]+)"')
STATUS_MAP_RE = re.compile(r'"(api\.[a-z0-9_.]+)"\s*:\s*(\d{3})')

COMMON_NAMESPACE_SEGMENTS = 2  # api.<error> 即通用；api.<svc>.<...> 即专属


def _parse_errors_py(path: Path) -> tuple[set[str], dict[str, int]]:
    """返回 (code 集合, code→http_status 映射)。"""
    text = path.read_text(encoding="utf-8")
    code_set = set(ENUM_ASSIGN_RE.findall(text))
    status_map = {c: int(s) for c, s in STATUS_MAP_RE.findall(text)}
    return code_set, status_map


def main() -> int:
    problems: list[str] = []
    seen: dict[str, str] = {}  # code -> first service that defined it (专属码查重)
    common_status: dict[str, tuple[str, int]] = {}  # code -> (service, status)

    for service, (errors_rel, dict_rel) in SERVICES.items():
        errors_path = REPO / errors_rel
        dict_path = REPO / dict_rel
        if not errors_path.exists():
            # 尚未接入该服务（Phase 1 渐进铺开）：只有 admin-api 是硬性要求
            if service == "admin-api":
                problems.append(f"[missing] {errors_rel} 不存在")
            continue
        codes, status_map = _parse_errors_py(errors_path)

        for code in sorted(codes):
            if not code.startswith("api."):
                problems.append(f"[naming] {service}: 错误码必须以 api. 开头: {code}")
                continue
            if not CODE_RE.match(code):
                problems.append(f"[naming] {service}: 非法字符: {code}")
                continue
            parts = code.split(".")
            owner_prefix = OWNER_PREFIX[service]
            if parts[1] in {"admin", "chat", "parser"}:
                # 专属码：不得越界定义，且全局唯一
                if not code.startswith(owner_prefix):
                    other = next((s for s, p in OWNER_PREFIX.items() if code.startswith(p)), None)
                    problems.append(
                        f"[ownership] {service}: 定义了他服务命名空间的专属码 {code}（owner={other}）"
                    )
                    continue
                if code in seen:
                    problems.append(f"[duplicate] 专属码重复定义: {code} 同时出现在 {seen[code]} 与 {service}")
                else:
                    seen[code] = service
            else:
                # 通用码：状态映射必须一致
                status = status_map.get(code)
                if status is None:
                    problems.append(f"[status] {service}: 通用码 {code} 未登记 DEFAULT_HTTP_STATUS")
                elif code in common_status:
                    prev_svc, prev = common_status[code]
                    if prev != status:
                        problems.append(
                            f"[drift] 通用码 {code} 状态漂移: {prev_svc}={prev} vs {service}={status}"
                        )
                else:
                    common_status[code] = (service, status)

        # 登记完整性：errors.py 的每个 code 都要出现在字典表
        if dict_path.exists():
            dict_text = dict_path.read_text(encoding="utf-8")
            for code in sorted(codes):
                if code not in dict_text:
                    problems.append(f"[undocumented] {service}: {code} 未登记到 {dict_rel}")
        elif codes:
            problems.append(f"[missing] {service}: 缺字典文件 {dict_rel}")

    if problems:
        print("error-codes uniqueness FAILED:")
        for p in problems:
            print("  " + p)
        return 1
    print(
        f"error-codes uniqueness OK — {len(seen)} service-specific codes, "
        f"{len(common_status)} common codes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
