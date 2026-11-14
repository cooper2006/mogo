"""T038 序列化一致性检查（FR-23, US3-9）。

FR-23 要求 JSON + snake_case 两侧一致，契约测试显式断言。

本工具做契约侧序列化审计：
  1. 枚举契约所有 interaction 响应字段（含嵌套 `fields`）；
  2. 判定字段名是否 snake_case；
  3. camelCase 字段必须登记在 `contracts/_camel_case_known.yaml`（FR-23 已知偏差白名单），
     否则视为未登记偏差 -> error（--strict 默认）；登记在表的仅提示；
  4. 输出 snake_case 覆盖率作为指标（覆盖率低不代表契约错误，只反映服务端 wire 格式
     仍为 camelCase，需服务端迁移）。

白名单是「显式登记而非静默豁免」：`--seed` 依据当前契约重新生成，需人工审阅后提交，
并在契约 gaps 中记录迁移方向。

用例: python3 tools/contract/serialization_check.py --all
生成白名单: python3 tools/contract/serialization_check.py --seed
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO / "specs" / "025-api-contract-hardening" / "contracts"
KNOWN_PATH = CONTRACTS_DIR / "_camel_case_known.yaml"

SERVICES = ["admin-api", "chat-api", "document-parser"]

SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def load_known(path: Path | None = None) -> dict:
    """加载已知 camelCase 偏差白名单：{service: {interaction_id: set(field_names)}}."""
    p = path or KNOWN_PATH
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {
        svc: {it: set(fields) for it, fields in (data or {}).items()}
        for svc, data in raw.items()
    }


def iter_response_fields(item: dict) -> list[tuple[str, Any, int | str | None]]:
    """枚举 interaction 内所有响应字段名（含嵌套 `fields`），返回 (字段名, meta, status)."""
    out: list[tuple[str, Any, int | str | None]] = []

    def walk(fields: dict, status: int | str | None) -> None:
        for name, meta in (fields or {}).items():
            out.append((name, meta, status))
            if isinstance(meta, dict) and isinstance(meta.get("fields"), dict):
                walk(meta["fields"], status)

    for resp in item.get("responses") or []:
        walk(resp.get("fields") or {}, resp.get("status"))
    return out


def is_snake(name: str) -> bool:
    """snake_case 判定：全小写字母数字 + 下划线，非下划线开头结尾。"""
    if not SNAKE_RE.match(name):
        return False
    # 不允许连续下划线 / 首尾下划线（正则已保证首字符为小写字母）
    if "__" in name or name.startswith("_") or name.endswith("_"):
        return False
    return True


def collect_camel(contract: dict) -> dict[str, dict[str, int]]:
    """返回 {interaction_id: {camelCase 字段名: 出现次数}}."""
    out: dict[str, dict[str, int]] = {}
    for item in contract.get("interactions") or []:
        iid = item.get("id") or "<anonymous>"
        counts: dict[str, int] = {}
        for name, _meta, _status in iter_response_fields(item):
            if not is_snake(name):
                counts[name] = counts.get(name, 0) + 1
        if counts:
            out[iid] = counts
    return out


def _seed_text(service: str, camel: dict) -> str:
    lines = [f"{service}:"]
    for iid in sorted(camel):
        lines.append(f"  {iid}:")
        for name in sorted(camel[iid]):
            lines.append(f"    - {name}")
    return "\n".join(lines)


def seed(output_path: Path | None = None) -> tuple[int, Path]:
    """重新生成白名单（覆盖现有文件），返回 (受影响交互数, 输出路径)."""
    known = load_known()
    text_parts = [
        "# FR-23 已知 camelCase 偏差登记表（T038 自动生成 + 人工审阅）",
        "#",
        "# 契约按消费方实际读取的服务端字段名登记（服务端 wire 格式为 camelCase，见各契约 gaps）；",
        "# FR-23 目标是 snake_case，待服务端逐项迁移到 snake_case 后从本表移除。",
        "# 未登记在表的 camelCase 字段会被 serialization_check.py 视为未登记偏差（error）。",
        "# 生成命令: python3 tools/contract/serialization_check.py --seed",
        "",
    ]
    affected = 0
    for service in SERVICES:
        path = CONTRACTS_DIR / f"{service}.yaml"
        if not path.exists():
            continue
        contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        camel = collect_camel(contract)
        known.setdefault(service, {})
        # 保留手写条目，合并自动收集结果
        merged = {iid: set(fields) for iid, fields in known[service].items()}
        for iid, fields in camel.items():
            merged.setdefault(iid, set()).update(fields)
            affected += 1
        text_parts.append(_seed_text(service, {iid: sorted(v) for iid, v in merged.items()}))
    text = "\n".join(text_parts).rstrip() + "\n"
    p = output_path or KNOWN_PATH
    p.write_text(text, encoding="utf-8")
    return affected, p


def check_contract(contract: dict, service: str, known: dict | None = None, strict: bool = True) -> tuple[bool, list[str]]:
    """检查单份契约序列化一致性，返回 (ok, 报告行)."""
    k = known if known is not None else load_known()
    camel = collect_camel(contract)
    errors: list[str] = []
    notes: list[str] = []
    total = 0
    snake_count = 0
    service_known = k.get(service, {})
    for item in contract.get("interactions") or []:
        iid = item.get("id") or "<anonymous>"
        known_fields = service_known.get(iid, set())
        for name, _meta, _status in iter_response_fields(item):
            total += 1
            if is_snake(name):
                snake_count += 1
            elif name in known_fields:
                notes.append(f"  [info] {iid}.{name}: 已在 FR-23 白名单登记（消费方实际读取的服务端 camelCase）")
            else:
                tag = "error" if strict else "warn"
                msg = (
                    f"  [{tag}] {iid}.{name}: camelCase 字段未在 _camel_case_known.yaml 登记"
                    "（FR-23 要求 snake_case）"
                )
                if strict:
                    errors.append(msg)
                else:
                    notes.append(msg)
    if total:
        ratio = snake_count / total * 100
        notes.insert(0, f"  [info] {service}: snake_case 覆盖率 {snake_count}/{total} = {ratio:.1f}%")
    if camel:
        notes.append(
            f"  [info] {service}: 存在 camelCase 字段的 interaction 共 {len(camel)} 个，"
            "明细见 contracts/_camel_case_known.yaml"
        )
    return (not errors), (errors + notes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FR-23 序列化一致性检查")
    ap.add_argument("--service", choices=SERVICES)
    ap.add_argument("--all", action="store_true", help="检查三份契约")
    ap.add_argument("--seed", action="store_true", help="重新生成 FR-23 白名单文件")
    ap.add_argument("--strict", action="store_true", help="未登记 camelCase 即 error（默认）")
    ap.add_argument("--no-strict", action="store_true", help="未登记 camelCase 降为 warn")
    args = ap.parse_args(argv)

    if args.seed:
        affected, path = seed()
        print(f"已重新生成白名单: {path}（{affected} 个 interaction）")
        return 0

    strict = not args.no_strict
    services = SERVICES if args.all else ([args.service] if args.service else SERVICES)
    known = load_known()
    rc = 0
    for service in services:
        path = CONTRACTS_DIR / f"{service}.yaml"
        if not path.exists():
            print(f"{service}: 契约文件不存在: {path}", file=sys.stderr)
            rc = 1
            continue
        contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ok, report = check_contract(contract, service, known, strict=strict)
        print(f"{service}: {'OK' if ok else 'FAIL'} — {'；'.join(report) if report else '无异常字段'}")
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
