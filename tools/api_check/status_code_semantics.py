#!/usr/bin/env python3
"""025 FR-2 (T011)：路由状态码语义扫描（只读，QF-204 / QF-207）。

扫描三个服务的 `app/api/routes/`，找出「HTTP 状态码语义错误」的两类模式：

1. **错误路径用了 200**：`raise HTTPException(status_code=200, ...)` —— 错误必须
   用 4xx/5xx；把错误挂到 200 会让客户端无法区分成功与失败。
2. **业务错误以 200 返回**：`return {"code": <非 0 字面量>, ...}` 或
   `return {"success": False, ...}` 且未显式 `status_code` —— FastAPI 默认 200，
   即「200 包裹错误」。

保守口径（避免误报刷屏，只报静态可确定的）：
- 只看**字面量**：`code` 键的值是 `ast.Constant` 的非 0 整数 / `success: False`；
  变量/表达式一律跳过。
- `raise HTTPException(status_code=<4xx|5xx>)` 属正确用法，跳过。
- `include_in_schema=False` 的兼容别名跳过（与 path_naming.py 同口径）。

退出码：0 无违规 / 1 存在违规。只读，不修改任何文件。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SERVICES: dict[str, str] = {
    "admin-api": "services/admin-api/app/api/routes",
    "chat-api": "services/chat-api/app/api/routes",
    "document-parser": "services/document-parser/app/api/routes",
}

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _iter_routes(root: Path):
    for service, rel in SERVICES.items():
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            yield service, path


def _is_compat_alias(decorator: ast.AST) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    for kw in decorator.keywords:
        if kw.arg == "include_in_schema" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
        if kw.arg == "deprecated" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _is_router_route(decorator: ast.AST) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in HTTP_METHODS:
        return False
    return isinstance(func.value, ast.Name) and func.value.id == "router"


def _literal_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _http_exception_status(node: ast.Call) -> int | None:
    """`HTTPException(status_code=<字面量>)` → 该状态码，否则 None。"""
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "HTTPException":
        return None
    for kw in node.keywords:
        if kw.arg == "status_code":
            return _literal_int(kw.value)
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int):
        return node.args[0].value
    return None


def _dict_code_and_success(dnode: ast.Dict) -> tuple[int | None, bool | None, bool]:
    """解析返回字典里的 `code` 与 `success` 字面量。

    返回 (code_literal, success_literal, explicit_status_code_present)。
    """
    code: int | None = None
    success: bool | None = None
    has_status = False
    for key, value in zip(dnode.keys, dnode.values):
        if not isinstance(key, ast.Constant):
            continue
        k = key.value
        if k == "code":
            code = _literal_int(value)
        elif k == "success":
            if isinstance(value, ast.Constant) and isinstance(value.value, bool):
                success = value.value
        elif k in ("status_code", "http_status"):
            has_status = True
    return code, success, has_status


def scan(root: Path, verbose: bool = False) -> list[dict]:
    problems: list[dict] = []
    stats = {"routes": 0, "files": 0}

    for service, path in _iter_routes(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        stats["files"] += 1
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not _is_router_route(dec):
                    continue
                if _is_compat_alias(dec):
                    continue
                stats["routes"] += 1
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                        # 1) 错误路径用了 200
                        if child.func.id == "HTTPException":
                            status = _http_exception_status(child)
                            if status is not None and not (400 <= status < 600):
                                problems.append(
                                    {
                                        "service": service,
                                        "file": str(path.relative_to(root)),
                                        "function": node.name,
                                        "kind": "error-raised-with-2xx/3xx",
                                        "status_code": status,
                                        "line": child.lineno,
                                    }
                                )
                    # 2) 业务错误以 200 返回（默认状态码）
                    if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                        code, success, has_status = _dict_code_and_success(child.value)
                        if not has_status:
                            if code is not None and code != 0:
                                problems.append(
                                    {
                                        "service": service,
                                        "file": str(path.relative_to(root)),
                                        "function": node.name,
                                        "kind": "error-returned-with-default-200",
                                        "code": code,
                                        "line": child.lineno,
                                    }
                                )
                            elif success is False:
                                problems.append(
                                    {
                                        "service": service,
                                        "file": str(path.relative_to(root)),
                                        "function": node.name,
                                        "kind": "error-returned-with-default-200",
                                        "success": False,
                                        "line": child.lineno,
                                    }
                                )
                    # 2b) JSONResponse / Response 显式 status_code=200 包裹 code 非 0
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id in ("JSONResponse", "Response")
                    ):
                        status = None
                        for kw in child.keywords:
                            if kw.arg == "status_code":
                                status = _literal_int(kw.value)
                        if status == 200:
                            for kw in child.keywords:
                                if kw.arg == "content" and isinstance(kw.value, ast.Dict):
                                    code, success, _ = _dict_code_and_success(kw.value)
                                    if (code is not None and code != 0) or success is False:
                                        problems.append(
                                            {
                                                "service": service,
                                                "file": str(path.relative_to(root)),
                                                "function": node.name,
                                                "kind": "error-wrapped-in-explicit-200",
                                                "line": child.lineno,
                                            }
                                        )
    if verbose:
        print(f"[scan] {stats['files']} file(s), {stats['routes']} route(s)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    problems = scan(root, args.verbose)

    if args.json:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=2))
    else:
        for p in problems:
            print(
                f"[sem] {p['service']:15s} {p['kind']:36s} "
                f"{p.get('status_code', p.get('code', p.get('success', '')))}  "
                f"@ {p['file']}:{p['line']}  in {p['function']}()"
            )

    if problems:
        print(f"\nstatus-code-semantics FAILED — {len(problems)} finding(s)", file=sys.stderr)
        return 1
    print("status-code-semantics OK — no findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())