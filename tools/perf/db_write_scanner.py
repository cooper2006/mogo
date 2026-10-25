"""026 T020/T021 — 数据库访问模式扫描器（识别 N+1 与循环单条写入）。

用 AST 静态扫描 ``services/*/app``：
* **T020 (FR-7)** 识别 N+1：循环体内单点查询（``find_one`` / ``find`` /
  ``get_*``）→ 候选批量预取或 ``$lookup`` / ``$unwind`` 聚合。
* **T021 (FR-12)** 识别循环单条写入（``insert_one`` / ``update_one`` /
  ``replace_one`` / ``delete_one``）→ 候选 ``bulk_write`` 批量写入。

本工具**只报告候选点**（改动由人工在确认后执行），避免在未验证的环境里
擅自改查询路径。

用法::

    python tools/perf/db_write_scanner.py --root services --report report.md
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 单点查询方法（T020）。注意：排除 `get`（大量 dict.get 是本地取值，
# 不是数据库查询，会造成噪声）。
QUERY_METHODS = {"find_one", "find", "count_documents"}

# 单条写入方法（T021）
WRITE_METHODS = {"insert_one", "update_one", "replace_one", "delete_one"}

# 聚合/批量方法（识别目标）
BULK_METHODS = {"bulk_write", "insert_many", "aggregate", "$lookup"}

# 循环体节点类型
LOOP_NODES = (ast.For, ast.AsyncFor, ast.While, ast.comprehension)


def _in_loop(ancestors: List[ast.AST]) -> bool:
    return any(isinstance(n, LOOP_NODES) for n in ancestors)


class ScanVisitor(ast.NodeVisitor):
    """收集循环体内的查询/写入调用候选。"""

    def __init__(self) -> None:
        self.candidates: List[Dict[str, Any]] = []
        self._ancestors: List[ast.AST] = []

    def visit(self, node: ast.AST) -> Any:
        self._ancestors.append(node)
        try:
            return super().visit(node)
        finally:
            self._ancestors.pop()

    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute) and _in_loop(self._ancestors):
            name = node.func.attr
            if name in QUERY_METHODS:
                self.candidates.append(
                    {
                        "kind": "n_plus_one",
                        "line": node.lineno,
                        "method": name,
                        "loop": self._nearest_loop_kind(),
                    }
                )
            elif name in WRITE_METHODS:
                self.candidates.append(
                    {
                        "kind": "loop_write",
                        "line": node.lineno,
                        "method": name,
                        "loop": self._nearest_loop_kind(),
                    }
                )
        self.generic_visit(node)

    def _nearest_loop_kind(self) -> str:
        for n in reversed(self._ancestors):
            if isinstance(n, ast.AsyncFor):
                return "async-for"
            if isinstance(n, ast.For):
                return "for"
            if isinstance(n, ast.While):
                return "while"
            if isinstance(n, ast.ListComp):
                return "list-comp"
        return "?"


def scan_file(path: Path) -> List[Dict[str, Any]]:
    """扫描单个 Python 文件，返回 N+1 / 循环写入候选。"""
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = ScanVisitor()
    visitor.visit(tree)
    out = []
    for cand in visitor.candidates:
        out.append({"file": str(path), **cand})
    return out


def scan_tree(root: Path) -> Dict[str, List[Dict[str, Any]]]:
    """扫描目录下所有 ``*.py``，按 kind 分组返回候选。"""
    nplusone: List[Dict[str, Any]] = []
    loop_write: List[Dict[str, Any]] = []
    files = sorted(root.rglob("*.py"))
    for path in files:
        # 跳过测试、虚拟环境、构建产物
        parts = set(path.parts)
        if "tests" in parts or "test" in parts or "__pycache__" in parts:
            continue
        for cand in scan_file(path):
            if cand["kind"] == "n_plus_one":
                nplusone.append(cand)
            else:
                loop_write.append(cand)
    return {"n_plus_one": nplusone, "loop_write": loop_write}


# 已知已改造为批量写入的点（扫描时排除，避免重复报告）
KNOWN_BULK_WRITTEN: Tuple[str, ...] = (
    "app/memory/lifecycle.py",  # 024：bulk_write 批量记忆落库
    "app/dsh_runtime/events/repository.py",  # 事件投影 bulk_write
)


def is_known_bulk_written(file: str) -> bool:
    return any(k in str(file) for k in KNOWN_BULK_WRITTEN)


def render_report(
    root: Path,
    nplusone: List[Dict[str, Any]],
    loop_write: List[Dict[str, Any]],
) -> str:
    """渲染 Markdown 报告（可写 docs/pending-review 供人工确认）。"""
    lines = [
        "# 026 T020/T021 数据库访问模式扫描报告",
        "",
        f"扫描根目录：`{root}`",
        "",
        f"- N+1 候选点：**{len(nplusone)}**",
        f"- 循环单条写入候选点：**{len(loop_write)}**",
        "",
        "## N+1（FR-7，候选改为批量预取或 `$lookup` 聚合）",
        "",
        "| 文件 | 行 | 方法 | 循环 | 建议 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cand in nplusone:
        lines.append(
            f"| `{cand['file']}` | {cand['line']} | `{cand['method']}` | {cand['loop']} | 批量预取 / `$lookup` |"
        )
    lines += [
        "",
        "## 循环单条写入（FR-12，候选改为 `bulk_write`）",
        "",
        "| 文件 | 行 | 方法 | 循环 | 建议 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cand in loop_write:
        lines.append(
            f"| `{cand['file']}` | {cand['line']} | `{cand['method']}` | {cand['loop']} | `bulk_write` |"
        )
    lines += [
        "",
        "## 说明",
        "",
        "- 本报告为静态 AST 扫描结果，**未执行代码**；候选点需人工确认后再改造。",
        "- 已确认使用 `bulk_write` 的点（如 memory/lifecycle.py、dsh_runtime/events/repository.py）不重复列入。",
        "- 改造完成后重跑本脚本，候选应减少至 0 或已登记为「确认为必要单查」。",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="026 T020/T021 数据库访问模式扫描")
    parser.add_argument("--root", default="services", help="扫描根目录（默认 services）")
    parser.add_argument("--report", default=None, help="输出 Markdown 报告路径（默认不写文件）")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"[db_write_scanner] root not found: {root}", flush=True)
        return 1
    report = scan_tree(root)
    # 排除已知已批量化的点
    nplusone = [c for c in report["n_plus_one"] if not is_known_bulk_written(c["file"])]
    loop_write = [c for c in report["loop_write"] if not is_known_bulk_written(c["file"])]

    print(f"[db_write_scanner] 扫描 {root}")
    print(f"  N+1 候选: {len(nplusone)}")
    for cand in nplusone:
        print(f"    {cand['file']}:{cand['line']} {cand['method']} in {cand['loop']}")
    print(f"  循环写入候选: {len(loop_write)}")
    for cand in loop_write:
        print(f"    {cand['file']}:{cand['line']} {cand['method']} in {cand['loop']}")

    if args.report:
        text = render_report(root, nplusone, loop_write)
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"[db_write_scanner] 报告写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())