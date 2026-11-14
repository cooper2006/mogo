#!/usr/bin/env python3
"""025 T012 — Pydantic 未知字段策略一致性检查（QF-210，CI 执行）。

规则：
1. **禁止 `extra='allow'`**（无论 pydantic v2 `model_config = ConfigDict(extra="allow")`
   还是 v1 风格 `class Config: extra = "allow"`）：会静默吞掉未知字段，
   把客户端拼写错误当成"多字段"放行，破坏契约 —— 一律硬失败。
2. 默认策略 `extra='ignore'`（前向兼容）；严格 schema 应 `extra='forbid'`。
3. `--strict` 下额外检查命名含 `Strict`/`CreateRequest`/`UpdateRequest`/`Command`
   的模型必须显式 `extra='forbid'`（契约输入侧应拒绝未知字段）。

退出码：0 通过；1 发现违规（打印明细）。
用法：
  python3 tools/api_check/schema_extra_policy.py
  python3 tools/api_check/schema_extra_policy.py --strict
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICES = ("admin-api", "chat-api", "document-parser")
APP_ROOT = "app"

# --strict 下要求 forbid 的严格命名模式
STRICT_PATTERNS = ("Strict", "CreateRequest", "UpdateRequest", "Command")


class Violation:
    __slots__ = ("path", "cls", "message")

    def __init__(self, path: str, cls: str, message: str) -> None:
        self.path = path
        self.cls = cls
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}: {self.cls}: {self.message}"


def _imports_pydantic(tree: ast.AST) -> tuple[set[str], set[str]]:
    """返回 (本模块内可用作 BaseModel 的名字集合, pydantic 模块别名集合)。"""
    names: set[str] = set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("pydantic", "pydantic.v1"):
            for alias in node.names:
                if alias.name == "BaseModel":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pydantic":
                    mods.add(alias.asname or "pydantic")
    return names, mods


def _is_basemodel_base(node: ast.expr, base_names: set[str], pydantic_mods: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in base_names
    if isinstance(node, ast.Attribute):
        return node.attr == "BaseModel" and isinstance(node.value, ast.Name) and node.value.id in pydantic_mods
    return False


def _class_extra(node: ast.ClassDef) -> str | None:
    """返回类中显式声明的 extra 值；无法确定时返回 None。"""
    for item in node.body:
        if isinstance(item, ast.ClassDef) and item.name == "Config":
            for stmt in item.body:
                value = _extra_from_assign(stmt)
                if value is not None:
                    return value
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            value = _extra_from_assign(item)
            if value is not None:
                return value
    return None


def _extra_from_assign(stmt: ast.stmt) -> str | None:
    targets: list[ast.expr] = []
    value: ast.expr | None = None
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        targets = [stmt.target]
        value = stmt.value
    if value is None:
        return None
    target_names = {t.id for t in targets if isinstance(t, ast.Name)}
    if "model_config" not in target_names and "extra" not in target_names:
        return None
    if "extra" in target_names:
        return _literal_str(value)
    return _extra_from_configdict(value)


def _extra_from_configdict(value: ast.expr) -> str | None:
    # ConfigDict(extra="allow", ...)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "ConfigDict":
        for kw in value.keywords:
            if kw.arg == "extra":
                return _literal_str(kw.value)
    # {"extra": "allow"} 或 {**other, "extra": "allow"}
    if isinstance(value, ast.Dict):
        for key, val in zip(value.keys, value.values):
            if key is not None and _literal_str(key) == "extra":
                return _literal_str(val)
    return None


def _literal_str(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_base_model_class(node: ast.ClassDef, base_names: set[str], pydantic_mods: set[str]) -> bool:
    return any(_is_basemodel_base(b, base_names, pydantic_mods) for b in node.bases)


def scan(service_root: Path, strict: bool = False) -> list[Violation]:
    violations: list[Violation] = []
    for py in sorted(service_root.rglob("*.py")):
        try:
            source = py.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        base_names, pydantic_mods = _imports_pydantic(tree)
        if not base_names and not pydantic_mods:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_base_model_class(node, base_names, pydantic_mods):
                continue
            rel = py.relative_to(service_root)
            extra = _class_extra(node)
            if extra == "allow":
                violations.append(Violation(str(rel), node.name, "显式 `extra='allow'` 会静默吞掉未知字段，破坏契约（QF-210）"))
            elif strict and extra != "forbid" and any(p in node.name for p in STRICT_PATTERNS):
                violations.append(
                    Violation(str(rel), node.name, "严格命名模型（Strict/CreateRequest/UpdateRequest/Command）应显式 `extra='forbid'`")
                )
    return violations


def main() -> int:
    strict = "--strict" in sys.argv[1:]
    root = REPO
    if "--root" in sys.argv:
        idx = sys.argv.index("--root")
        if idx + 1 < len(sys.argv):
            root = Path(sys.argv[idx + 1])
    total = 0
    for svc in SERVICES:
        service_root = root / "services" / svc / APP_ROOT
        if not service_root.is_dir():
            continue
        for v in scan(service_root, strict=strict):
            total += 1
            print(f"schema-extra-policy FAILED [{svc}] {v}")
    if total:
        print(f"schema-extra-policy FAILED: 共 {total} 处违规（--strict={strict}）")
        return 1
    print("schema-extra-policy OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())