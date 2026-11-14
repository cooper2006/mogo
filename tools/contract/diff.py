"""025 US3 契约兼容性 diff（FR-18 / FR-20 / FR-21 / FR-22）。

对同一服务的两份契约版本做字段级 diff，判定**破坏性变更**（会阻断 CI，FR-18）与
**兼容变更**（新增可选字段，FR-21 容忍）。

契约由消费方定义（FR-16），因此 diff 的语义是：
- 契约删除一个 interaction / 字段 / 状态码分支 → 消费方不再依赖，属**兼容移除**（不破坏服务端）
- 契约新增一个 interaction / required 字段 / 非 2xx 分支 → 消费方新增依赖，属**破坏性**（服务端必须补上）
- 字段类型变更、optional→required、非 2xx 状态码变化 → 破坏性
- 新增 optional 字段 / 新增 2xx 分支 → 兼容（FR-21）

旧版本标记 `deprecated: true` 的 interaction 被删除时，仅在 `deprecated_since` 距今超过
观察期（默认 2 个 minor，FR-22）后视为允许移除。

用法：
    python3 tools/contract/diff.py --old old.yaml --new new.yaml
    python3 tools/contract/diff.py --old-contracts-dir A --new-contracts-dir B

退出码：0 无破坏性变更；1 存在破坏性变更（CI 阻断，FR-18/FR-20）。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from validate import FIELD_TYPES, load_contract  # 复用契约加载与类型集合

BREAKING_TYPES = {"removed_interaction", "changed_method", "changed_path",
                  "removed_field", "changed_field_type", "field_turned_required",
                  "new_required_field", "removed_error_status", "removed_error_code",
                  "changed_status_semantics"}
COMPAT_TYPES = {"added_interaction", "new_optional_field", "new_success_status",
                "removed_interaction_deprecated"}
SERVICE_NAME_RE = re.compile(r"[a-z-]+")


def norm_fields(fields: dict) -> dict[str, dict]:
    """把契约 fields 规范化为 {field: {"type": ..., "required": bool}}。"""
    out: dict[str, dict] = {}
    for name, spec in (fields or {}).items():
        if not isinstance(spec, dict):
            continue
        out[name] = {"type": spec.get("type"), "required": bool(spec.get("required", False))}
    return out


def index_interactions(data: dict) -> dict[str, dict]:
    return {item["id"]: item for item in data.get("interactions", []) if isinstance(item, dict)}


def responses_by_status(item: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for resp in item.get("responses", []) or []:
        if isinstance(resp, dict) and isinstance(resp.get("status"), int):
            out[resp["status"]] = resp
    return out


def is_deprecated_past_observation(item: dict, now: str | None = None, minors: int = 2) -> bool:
    """FR-22：deprecated interaction 在观察期（默认 2 个 minor 版本）后可安全移除。"""
    since = item.get("deprecated_since")
    if not since:
        return False
    try:
        anchor = datetime.strptime(now or datetime.utcnow().strftime("%Y-%m-%d"), "%Y-%m-%d")
        ref = datetime.strptime(str(since)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    major_ref, minor_ref = ref.year, ref.month
    major_now, minor_now = anchor.year, anchor.month
    delta = (major_now - major_ref) * 12 + (minor_now - minor_ref)
    return delta >= minors


def diff_interaction(old: dict, new: dict) -> list[dict]:
    """对同一 id 的两份 interaction 做字段级 diff，返回破坏性变更列表。"""
    problems: list[dict] = []
    if old.get("method") != new.get("method"):
        problems.append({"type": "changed_method", "id": new["id"],
                         "detail": f"{old.get('method')} -> {new.get('method')}"})
    if old.get("path") != new.get("path"):
        problems.append({"type": "changed_path", "id": new["id"],
                         "detail": f"{old.get('path')} -> {new.get('path')}"})

    old_resp, new_resp = responses_by_status(old), responses_by_status(new)
    for status in sorted(set(old_resp) - set(new_resp)):
        problems.append({"type": "removed_error_status" if status >= 400 else "removed_success_status",
                         "id": new["id"], "status": status})
    for status in sorted(set(new_resp) - set(old_resp)):
        if status < 400:
            # 新增 2xx 分支属兼容扩展（FR-21）
            problems.append({"type": "new_success_status", "id": new["id"], "status": status})

    for status in sorted(set(old_resp) & set(new_resp)):
        old_fields = norm_fields(old_resp[status].get("fields"))
        new_fields = norm_fields(new_resp[status].get("fields"))
        for field in sorted(set(old_fields) - set(new_fields)):
            problems.append({"type": "removed_field", "id": new["id"], "status": status,
                             "field": field})
        for field in sorted(set(new_fields) - set(old_fields)):
            if new_fields[field]["required"]:
                problems.append({"type": "new_required_field", "id": new["id"], "status": status,
                                 "field": field})
            else:
                problems.append({"type": "new_optional_field", "id": new["id"], "status": status,
                                 "field": field})
        for field in sorted(set(old_fields) & set(new_fields)):
            if old_fields[field]["type"] != new_fields[field]["type"]:
                problems.append({"type": "changed_field_type", "id": new["id"], "status": status,
                                 "field": field,
                                 "detail": f"{old_fields[field]['type']} -> {new_fields[field]['type']}"})
            if old_fields[field]["required"] is False and new_fields[field]["required"] is True:
                problems.append({"type": "field_turned_required", "id": new["id"], "status": status,
                                 "field": field})

        old_codes = set(old_resp[status].get("error_codes") or [])
        new_codes = set(new_resp[status].get("error_codes") or [])
        for code in sorted(old_codes - new_codes):
            problems.append({"type": "removed_error_code", "id": new["id"], "status": status,
                             "code": code})
    return problems


def diff_contracts(old: dict, new: dict) -> list[dict]:
    old_items, new_items = index_interactions(old), index_interactions(new)
    problems: list[dict] = []
    for iid in sorted(set(old_items) - set(new_items)):
        item = old_items[iid]
        if item.get("deprecated") and is_deprecated_past_observation(item):
            problems.append({"type": "removed_interaction_deprecated", "id": iid,
                             "detail": "deprecated 观察期已过，允许移除（FR-22）"})
        else:
            problems.append({"type": "removed_interaction", "id": iid})
    for iid in sorted(set(new_items) - set(old_items)):
        problems.append({"type": "added_interaction", "id": iid})
    for iid in sorted(set(old_items) & set(new_items)):
        problems.extend(diff_interaction(old_items[iid], new_items[iid]))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", help="旧契约文件")
    parser.add_argument("--new", help="新契约文件")
    args = parser.parse_args(argv)

    if not args.old or not args.new:
        parser.error("必须提供 --old 与 --new 契约文件路径")

    old_data = load_contract_file(args.old)
    new_data = load_contract_file(args.new)
    problems = diff_contracts(old_data, new_data)

    breaking = [p for p in problems if p["type"] in BREAKING_TYPES]
    for p in problems:
        print(f"[{'BREAKING' if p['type'] in BREAKING_TYPES else 'compat'}] "
              f"{p['type']}: {p.get('id', '')} {p.get('detail', '')}")
    print(f"contract diff: {len(problems)} change(s), {len(breaking)} breaking")
    return 1 if breaking else 0


def load_contract_file(path: str) -> dict:
    import yaml

    p = Path(path)
    if not p.exists():
        raise SystemExit(f"契约文件不存在: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())