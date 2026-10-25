#!/usr/bin/env python3
"""025 T046 — 错误码 ↔ HTTP 状态码映射稳定性检查（FR-31, QF-270, CI 执行）。

设计口径（对齐 `docs/error-codes.md` §4「稳定性与变更流程」与
`docs/api-versioning.md` 幅度规则）：`code` 值一经发布不可变更含义；
某 code 的 `http_status` 一旦改变，客户端对该错误的分支逻辑即失效，
属 `changed_status_semantics`（`tools/contract/diff.py` 的 BREAKING_TYPES），
必须 major 版本升级。本工具在 CI 中阻断这类静默漂移。

检测三类问题：

1. **映射漂移（破坏性，须 major 升级）**——与**基线快照**
   `specs/025-api-contract-hardening/baseline/error-code-mapping.json` 比对：
   - 基线里存在的 code，当前 `http_status` 变了 → `changed_status_semantics`
   - 基线里存在的 code，当前实现里**被移除** → 客户端分支失效，同样破坏性
2. **字典不一致**——`docs/error-codes.md` §2 通用码表（唯一权威字典，FR-30）
   与三服务 `app/core/errors.py` 的 `ApiErrorCode` 枚举 + `DEFAULT_HTTP_STATUS`
   不一致（字典有的码实现里没有 / 实现有的码字典里没有 / 状态码不一致）。
3. **信息提示**——当前实现**新增**了 code（向后兼容，只打印，不阻断）。

基线策略：
- **首次运行**（快照不存在）：用当前实现生成快照，打印 `created`，rc=0。
- **之后运行**（快照存在）：与当前实现比对，发现漂移 rc=1。
- `--update-baseline`：用当前实现**重写**快照（在有意变更并完成 major
  版本升级后重建基线；重建本身不报漂移）。

快照结构：`{ "schema_version": 1, "generated_at": ..., "services": {
"admin-api": {"api.internal_error": 500, ...}, ... } }`

退出码：0 通过；1 发现漂移或字典不一致（打印明细）。

用法：
    python3 tools/api_check/error_code_mapping.py [--baseline PATH]
        [--dict PATH] [--services s1,s2] [--update-baseline]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ALL_SERVICES = ("admin-api", "chat-api", "document-parser")

DEFAULT_BASELINE = (
    REPO / "specs" / "025-api-contract-hardening" / "baseline" / "error-code-mapping.json"
)
DEFAULT_DICT = REPO / "docs" / "error-codes.md"

SERVICES = {
    "admin-api": "services/admin-api/app/core/errors.py",
    "chat-api": "services/chat-api/app/core/errors.py",
    "document-parser": "services/document-parser/app/core/errors.py",
}

# 与 tools/api_check/error_codes_uniqueness.py 保持同一套解析口径
ENUM_ASSIGN_RE = re.compile(r'=\s*"(api\.[a-z0-9_.]+)"')
STATUS_MAP_RE = re.compile(r'"(api\.[a-z0-9_.]+)"\s*:\s*(\d{3})')
# docs/error-codes.md §2 通用表行：| `api.xxx` | `500` | ... |
DOC_ROW_RE = re.compile(r'^\|\s*`(api\.[a-z0-9_.]+)`\s*\|\s*`?(\d{3})`?\s*\|')

SCHEMA_VERSION = 1


def parse_errors_py(path: Path) -> tuple[set[str], dict[str, int]]:
    """返回 (code 集合, code→http_status 映射)。文件缺失返回空。"""
    if not path.exists():
        return set(), {}
    text = path.read_text(encoding="utf-8")
    codes = set(ENUM_ASSIGN_RE.findall(text))
    status_map = {c: int(s) for c, s in STATUS_MAP_RE.findall(text)}
    return codes, status_map


def parse_docs_dict(path: Path) -> dict[str, int]:
    """解析 docs/error-codes.md §2 通用码表，返回 code→http_status。

    只认 `api.*` 通用表行（第 2 列为 3 位状态码）；§3 业务码表
    （http_status 由 handler 决定）不在机器断言范围内。
    """
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = DOC_ROW_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def read_baseline(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[baseline] 快照解析失败（视为无基线）: {exc}")
        return None


def write_baseline(path: Path, mapping: dict[str, dict[str, int]]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "services": mapping,
    }
    path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, default=DEFAULT_BASELINE, help="基线快照路径"
    )
    parser.add_argument(
        "--dict", type=Path, default=DEFAULT_DICT, help="docs/error-codes.md 路径"
    )
    parser.add_argument(
        "--services",
        default="admin-api,chat-api,document-parser",
        help="逗号分隔的服务列表",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="用当前实现重写基线快照（不比对漂移）",
    )
    args = parser.parse_args(argv)

    selected = [s.strip() for s in args.services.split(",") if s.strip()]
    unknown = [s for s in selected if s not in ALL_SERVICES]
    if unknown:
        parser.error(f"未知服务: {', '.join(unknown)}（可选 {', '.join(ALL_SERVICES)}）")
    # 未接入的服务（SERVICES 里无路径映射）跳过，不阻断其它服务
    selected = [s for s in selected if s in SERVICES]

    # 1) 当前实现映射
    current: dict[str, dict[str, int]] = {}
    missing_files: list[str] = []
    for svc in selected:
        svc_path = Path(SERVICES[svc])
        if not svc_path.is_absolute():
            svc_path = REPO / svc_path
        codes, status_map = parse_errors_py(svc_path)
        # 枚举是权威：DEFAULT_HTTP_STATUS 里残留的孤儿条目（枚举已删除）不算可用映射
        current[svc] = {c: status_map[c] for c in codes if c in status_map}
        for code in sorted(codes):
            if code not in status_map:
                missing_files.append(f"{svc}: 码 {code} 未登记 DEFAULT_HTTP_STATUS")
    if missing_files:
        print("error-code mapping FAILED:")
        for m in missing_files:
            print("  [status] " + m)
        return 1

    # 2) 字典一致性（docs/error-codes.md §2 通用表 vs 三服务实现）
    doc_map = parse_docs_dict(args.dict)
    problems: list[str] = []
    info: list[str] = []

    # 三服务通用码映射必须一致（否则无法对外声明稳定语义）
    all_codes = set()
    for svc, sm in current.items():
        all_codes |= set(sm)
    for code in sorted(all_codes):
        statuses = {sm[code] for sm in current.values() if code in sm}
        if len(statuses) > 1:
            problems.append(
                f"[drift] 跨服务状态不一致 {code}: "
                + ", ".join(f"{svc}={sm[code]}" for svc, sm in current.items() if code in sm)
            )

    if doc_map:
        for code in sorted(doc_map):
            impl = {svc: sm[code] for svc, sm in current.items() if code in sm}
            if not impl:
                problems.append(f"[doc-orphan] 字典 {args.dict} 登记 {code}，但三服务实现里都没有")
            else:
                bad = {svc: st for svc, st in impl.items() if st != doc_map[code]}
                if bad:
                    problems.append(
                        f"[doc-drift] 字典 {code}={doc_map[code]}, 实现 "
                        + ", ".join(f"{svc}={st}" for svc, st in bad.items())
                    )
        for code in sorted(all_codes - set(doc_map)):
            problems.append(f"[undocumented] {code} 未登记到 {args.dict} §2 通用表")

    # 3) 与基线比对（changed_status_semantics）
    baseline_path = args.baseline
    baseline = read_baseline(baseline_path)

    if args.update_baseline or baseline is None:
        snap = write_baseline(baseline_path, current)
        if args.update_baseline:
            print(f"[baseline] 已用当前实现更新基线: {baseline_path}")
        else:
            print(
                f"[baseline] 首次运行，已生成基线快照 "
                f"({sum(len(v) for v in current.values())} 映射) — 后续运行将检测漂移"
            )
        # 首次/更新基线不报漂移，但仍要报字典一致性问题
        if problems:
            print("error-code mapping FAILED:")
            for p in problems:
                print("  " + p)
            return 1
        print("error-code mapping OK — baseline created, dict consistent")
        return 0

    if baseline.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"[baseline] 快照 schema_version 不匹配: {baseline.get('schema_version')}")

    base_services = baseline.get("services") or {}
    for svc in selected:
        base_map = base_services.get(svc) or {}
        cur = current.get(svc) or {}
        for code in sorted(base_map):
            if code not in cur:
                problems.append(
                    f"[changed_status_semantics] {svc}: {code} 已被移除（客户端分支失效）"
                )
            elif cur[code] != base_map[code]:
                problems.append(
                    f"[changed_status_semantics] {svc}: {code} http_status "
                    f"{base_map[code]} -> {cur[code]}（须 major 版本升级）"
                )
        for code in sorted(set(cur) - set(base_map)):
            info.append(f"[compat] {svc}: 新增错误码 {code}={cur[code]}（向后兼容，记录）")

    if problems:
        print("error-code mapping FAILED (requires major version bump):")
        for p in problems:
            print("  " + p)
        for i in info:
            print("  " + i)
        return 1

    print("error-code mapping OK — no status-semantics drift")
    for i in info:
        print("  " + i)
    return 0


if __name__ == "__main__":
    sys.exit(main())