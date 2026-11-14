#!/usr/bin/env python3
"""T037 弃用字段观察期检查（FR-22, US3-7, US3-8）。

扫描契约文件里带 ``deprecated: true`` 的 interaction / 响应字段，检查：

1. **声明完整**：带 ``deprecated`` 的项必须同时声明 ``deprecated_since``（弃用起始版本），
   否则视为声明缺失（错误，退出码 1）。
2. **观察期未满**：弃用后保留默认 2 个 minor 版本的观察期（FR-22），
   观察期内**禁止**移除该字段/端点（状态 = ``观察中``，视为合规，不阻断）。
3. **观察期已满**：当前版本 >= deprecated_since + 2 minor 时，该字段/端点
   **允许**被移除（状态 = ``可移除``），但仍需契约内无消费方引用才真正删除；
   工具同时报告当前版本是否已可移除，供删除前 CI 复核。

当前版本取契约顶层 ``version`` 字段（契约持有主副本，FR-16）。

用法::

    python3 tools/contract/deprecation_check.py [--contract PATH] [--service NAME]
    python3 tools/contract/deprecation_check.py --all

退出码：0 = 全部合规（无违规 / 仍在观察期）；1 = 存在违规（缺 deprecated_since /
deprecated_since 在未来版本）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO / "specs" / "025-api-contract-hardening" / "contracts"
SERVICES = ("admin-api", "chat-api", "document-parser")

DEFAULT_OBSERVATION_MINORS = 2  # FR-22：默认观察期 2 个 minor 版本

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


class DeprecatedItem:
    """契约中一处已声明弃用的元素（interaction 或响应字段）。"""

    def __init__(
        self,
        *,
        service: str,
        kind: str,
        interaction_id: str,
        path: str,
        field: str,
        deprecated_since: str | None,
        current_version: str,
    ) -> None:
        self.service = service
        self.kind = kind  # "interaction" | "field"
        self.interaction_id = interaction_id
        self.path = path
        self.field = field
        self.deprecated_since = deprecated_since
        self.current_version = current_version

    @property
    def location(self) -> str:
        if self.kind == "interaction":
            return f"{self.service}: interaction {self.interaction_id} ({self.path})"
        return f"{self.service}: interaction {self.interaction_id} 字段 {self.field!r}"

    def describe(self, allowed_version: str) -> str:
        state = "观察中（不可移除）" if self.current_version < allowed_version else "已过观察期（可移除）"
        return (
            f"{self.location} 弃用于 {self.deprecated_since}，当前 {self.current_version}，"
            f"最早 {allowed_version} 可移除 → {state}"
        )


def parse_version(text: str) -> tuple[int, int, int]:
    """解析 ``major.minor.patch``（patch 可省）为三元组。非法版本抛 ValueError。"""
    m = _VERSION_RE.match(str(text))
    if not m:
        raise ValueError(f"无法解析版本号: {text!r}（期望 major.minor[.patch]）")
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def bump_minor(version: str, minors: int = DEFAULT_OBSERVATION_MINORS) -> str:
    """版本号加上 ``minors`` 个 minor 版本（patch 归零）。"""
    major, minor, _ = parse_version(version)
    total = minor + minors
    return f"{major + total // 10}.{total % 10}.0"


def walk_interaction_fields(interaction: dict) -> list[tuple[str, dict]]:
    """遍历 interaction 的全部响应字段，返回 ``(JSONPath 风格字段名, 字段 dict)``。

    覆盖 ``responses[].fields`` 里的扁平和嵌套（点号）与数组（``[]``）字段名。
    """
    out: list[tuple[str, dict]] = []

    def _walk(fields: dict, prefix: str = "") -> None:
        for name, spec in (fields or {}).items():
            key = f"{prefix}{name}" if not prefix else f"{prefix}.{name}"
            if isinstance(spec, dict):
                out.append((key, spec))
                # 嵌套对象：spec 下的 fields 子映射
                nested = spec.get("fields")
                if isinstance(nested, dict):
                    _walk(nested, key)
                # 数组元素：spec 下的 item（契约 README：数组用 `type: array` + `item`）
                item = spec.get("item")
                if isinstance(item, dict) and isinstance(item.get("fields"), dict):
                    _walk(item["fields"], f"{key}[]")

    for resp in interaction.get("responses") or []:
        if isinstance(resp, dict) and isinstance(resp.get("fields"), dict):
            _walk(resp["fields"])
    return out


def collect_deprecated(
    contract: dict, service: str, current_version: str
) -> list[DeprecatedItem]:
    """收集契约内所有带 ``deprecated: true`` 的 interaction / 字段。"""
    items: list[DeprecatedItem] = []
    for interaction in contract.get("interactions") or []:
        if not isinstance(interaction, dict):
            continue
        if interaction.get("deprecated") is True:
            items.append(
                DeprecatedItem(
                    service=service,
                    kind="interaction",
                    interaction_id=interaction.get("id", ""),
                    path=interaction.get("path", ""),
                    field="",
                    deprecated_since=interaction.get("deprecated_since"),
                    current_version=current_version,
                )
            )
        for field_name, field_spec in walk_interaction_fields(interaction):
            if isinstance(field_spec, dict) and field_spec.get("deprecated") is True:
                items.append(
                    DeprecatedItem(
                        service=service,
                        kind="field",
                        interaction_id=interaction.get("id", ""),
                        path=interaction.get("path", ""),
                        field=field_name,
                        deprecated_since=field_spec.get("deprecated_since"),
                        current_version=current_version,
                    )
                )
    return items


def check_contract(
    contract: dict,
    service: str,
    *,
    minors: int = DEFAULT_OBSERVATION_MINORS,
) -> tuple[bool, list[str]]:
    """校验单份契约的弃用声明。

    返回 ``(是否合规, 报告行列表)``。报告行以 ``[error]`` / ``[warn]`` / ``[info]`` 前缀
    标注级别；出现 ``[error]`` 即不合规（退出码 1）。
    """
    current_version = str(contract.get("version", ""))
    try:
        cur = parse_version(current_version)
    except ValueError as exc:  # 契约版本非法，无法判定观察期
        return False, [f"[error] {service}: 契约顶层 version 非法（{exc}）"]

    problems: list[str] = []
    notes: list[str] = []
    try:
        parse_version(current_version)
    except ValueError:
        return False, problems + notes

    deprecated_items = collect_deprecated(contract, service, current_version)
    if not deprecated_items:
        notes.append(f"[info] {service}: 无 deprecated 声明，跳过观察期检查")
        return True, notes

    for item in deprecated_items:
        if not item.deprecated_since:
            problems.append(
                f"[error] {item.location} 声明 deprecated 但缺少 deprecated_since（弃用起始版本）"
            )
            continue
        try:
            parse_version(item.deprecated_since)
        except ValueError as exc:
            problems.append(f"[error] {item.location} 的 deprecated_since 非法（{exc}）")
            continue
        try:
            since = parse_version(item.deprecated_since)
        except ValueError:
            continue
        if since > cur:
            problems.append(
                f"[error] {item.location} 的 deprecated_since {item.deprecated_since} "
                f"晚于当前版本 {current_version}（弃用起始版本不能在未来）"
            )
            continue
        allowed_version = bump_minor(item.deprecated_since, minors)
        notes.append(f"[{'warn' if cur >= parse_version(allowed_version) else 'info'}] {item.describe(allowed_version)}")

    return (not problems), notes + problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service",
        choices=SERVICES,
        help="只检查指定服务的契约（默认检查全部）",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        help="直接指定单个契约 YAML 路径（与 --service 互斥时优先）",
    )
    parser.add_argument(
        "--minors",
        type=int,
        default=DEFAULT_OBSERVATION_MINORS,
        help=f"观察期 minor 版本数（默认 {DEFAULT_OBSERVATION_MINORS}）",
    )
    parser.add_argument("--all", action="store_true", help="遍历并检查全部三份契约")
    args = parser.parse_args(argv)

    if args.contract:
        targets = [(args.contract, args.contract.stem)]
    elif args.service:
        targets = [(CONTRACTS_DIR / f"{args.service}.yaml", args.service)]
    else:
        targets = [(CONTRACTS_DIR / f"{name}.yaml", name) for name in SERVICES]

    ok_all = True
    for path, service in targets:
        if not path.exists():
            print(f"{service}: 契约文件不存在: {path}")
            ok_all = False
            continue
        try:
            contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(f"{service}: 契约 YAML 解析失败: {exc}")
            ok_all = False
            continue
        ok, report = check_contract(contract, service, minors=args.minors)
        ok_all = ok_all and ok
        for line in report:
            print(line)
        if ok:
            print(f"{service}: deprecation check OK")
        else:
            print(f"{service}: deprecation check FAILED")

    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
