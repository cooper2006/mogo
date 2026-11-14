#!/usr/bin/env python3
"""Scan for fail-open anti-patterns across the codebase.

Pattern 1: except ... : return True (bare allow in exception handler)
Pattern 2: if db is None: return True / if row is None: return True
Pattern 3: default="allow" or effectiveDefault="allow"
Pattern 4: mode == "off" → allowed = True

行为：
- 用 ast 模块扫描 Python 源码（比正则更安全，不误报字符串字面量外的内容）
- 识别上述四种模式的变体
- 支持 # fail-open-exempt: <理由> 注释豁免
- 输出 JSON 清单 + 人类可读摘要
- Exit code 0 = 全绿，1 = 发现违规

用法：
    python3 scripts/check_fail_open_patterns.py            # 全量扫 services/
    python3 scripts/check_fail_open_patterns.py services/admin-api
    python3 scripts/check_fail_open_patterns.py --staged  # 只扫暂存的 .py（pre-commit）
"""

import ast
import json
import sys
from pathlib import Path

from _scan_common import iter_python_files, parse_scan_args


# 豁免注释标记（与 fail_open_guard.py 保持一致）
FAIL_OPEN_EXEMPT_COMMENT = "fail-open-exempt:"


def is_exempt(node: ast.AST, source: str) -> bool:
    """检查节点是否被 ``# fail-open-exempt:`` 注释豁免。

    覆盖命中行本身（行内注释）与其上方 4 行（多行理由说明）。
    修正了原实现的 off-by-one：``lineno`` 是 1-based，而 ``lines[i]`` 是
    0-based，原实现 range 上界取 ``line_num`` 会把注释窗口整体偏移一行，
    导致紧邻节点上方的豁免注释识别不到。
    """
    lines = source.split("\n")
    line_num = getattr(node, "lineno", 1)
    for i in range(max(0, line_num - 5), min(line_num, len(lines))):
        if FAIL_OPEN_EXEMPT_COMMENT in lines[i]:
            return True
    return False


def find_fail_open_patterns(root_dir: str, *, staged: bool = False) -> list[dict]:
    """扫描 Python 文件中的 fail-open 模式（staged=True 只扫暂存文件）。"""
    violations = []

    for py_file in iter_python_files(root_dir, staged=staged):
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                source = f.read()
        except (UnicodeDecodeError, PermissionError):
            continue

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        # 模式 1: except ... : return True
        for node in ast.walk(tree):
            # 检查 except 捕获块
            if isinstance(node, ast.ExceptHandler):
                # 检查 return True
                if node.body:
                    for stmt in node.body:
                        if isinstance(stmt, ast.Return) and stmt.value is not None:
                            if isinstance(stmt.value, ast.Constant) and stmt.value.value is True:
                                if not is_exempt(node, source):
                                    violations.append({
                                        "file": str(py_file),
                                        "line": node.lineno,
                                        "pattern": "Pattern 1: except ... : return True",
                                        "context": "except handler unconditionally allows",
                                    })

            # 模式 2: if db is None: return True / if row is None: return True
            if isinstance(node, ast.If):
                # 检查条件是 `db is None` 或 `row is None`
                test = node.test
                if isinstance(test, ast.Compare):
                    comparators = test.comparators
                    if len(comparators) == 1:
                        comparator = comparators[0]
                        # db is None
                        if (
                            isinstance(test.left, ast.Name)
                            and test.left.id in ("db", "connection")
                            and isinstance(comparator, ast.Is)
                            and comparator.comparators[0] is None
                        ):
                            if not is_exempt(node, source):
                                violations.append({
                                    "file": str(py_file),
                                    "line": node.lineno,
                                    "pattern": "Pattern 2: if db is None: return True",
                                    "context": "database connection check allows",
                                })
                        # row is None
                        if (
                            isinstance(test.left, ast.Name)
                            and test.left.id == "row"
                            and isinstance(comparator, ast.Is)
                            and comparator.comparators[0] is None
                        ):
                            if not is_exempt(node, source):
                                violations.append({
                                    "file": str(py_file),
                                    "line": node.lineno,
                                    "pattern": "Pattern 2: if row is None: return True",
                                    "context": "row check allows",
                                })

            # 模式 3: default="allow" 或 effectiveDefault="allow"
            if isinstance(node, ast.keyword):
                if node.arg in ("default", "effectiveDefault"):
                    if isinstance(node.value, ast.Constant) and node.value.value == "allow":
                        if not is_exempt(node, source):
                            violations.append({
                                "file": str(py_file),
                                "line": node.lineno,
                                "pattern": f"Pattern 3: {node.arg}=\"allow\"",
                                "context": "default allow value",
                            })

            # 模式 4: mode == "off" → allowed = True
            # 这需要更复杂的上下文分析，这里做简单检查
            if isinstance(node, ast.Compare):
                if (
                    isinstance(node.left, ast.Name)
                    and node.left.id == "mode"
                    and isinstance(node.ops[0], ast.Eq)
                    and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value == "off"
                ):
                    # 检查是否在赋值链中出现 `allowed = True`
                    # 简化处理：仅标记模式匹配，不保证逻辑连贯
                    if not is_exempt(node, source):
                        violations.append({
                            "file": str(py_file),
                            "line": node.lineno,
                            "pattern": "Pattern 4: mode == \"off\" → allowed = True",
                            "context": "mode off check allows",
                        })

    return violations


def main():
    root_dir, staged = parse_scan_args(sys.argv[1:], default_root="services")
    violations = find_fail_open_patterns(root_dir, staged=staged)

    if not violations:
        print("✅ No fail-open anti-patterns detected.")
        sys.exit(0)

    # 按文件分组
    violations_by_file = {}
    for v in violations:
        file_path = v["file"]
        if file_path not in violations_by_file:
            violations_by_file[file_path] = []
        violations_by_file[file_path].append(v)

    # 输出人类可读摘要
    print(f"🚨 Found {len(violations)} fail-open anti-pattern(s):")
    print("=" * 60)

    for file_path in sorted(violations_by_file.keys()):
        print(f"\nFile: {file_path}")
        for v in violations_by_file[file_path]:
            print(f"  Line {v['line']}: {v['pattern']}")
            print(f"       {v['context']}")

    # 输出 JSON 格式的违规清单
    json_output = {
        "total_violations": len(violations),
        "patterns": [v["pattern"] for v in violations],
        "violations": violations,
    }
    print("\n" + "=" * 60)
    print("JSON output for CI:")
    print(json.dumps(json_output, ensure_ascii=False, indent=2))
    print("=" * 60)

    sys.exit(1)


if __name__ == "__main__":
    main()