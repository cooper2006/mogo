#!/usr/bin/env python3
"""025 T008 — 路径命名检查（FR-1，QF-202，CI 执行）。

规则：所有路由路径必须**表达资源**（`/users`、`/documents/{id}`），禁止动词段
（`/getUsers`、`/listDocuments`、`/doParse`）。本脚本扫描三个服务的
`app/api/routes/`，逐个 FastAPI 路由拼接（本地 `APIRouter(prefix=...)` +
装饰器路径），按 `/` 分段，命中以下动词即报违规：

  get / list / create / update / delete / do

判定口径（避免误报）：
- 段命中 = 段本身就是动词（`/delete`），或段以动词开头且紧接大写/下划线/数字
  （`getUsers` / `do_parse` / `list0`）。纯名词后缀（`getting`）不算。
- 路径变量（`{id}`、`{tenant_id}`、`:param`）段跳过。
- 以 `_` 开头的内部专用段（如 `_internal`）跳过，避免与内部路由耦合。

退出码：0 通过；1 发现违规（打印明细）。

用法：
  python3 tools/api_check/path_naming.py [--root <repo>] [--strict]
                                        [--json] [--verbose]
选项：
  --strict  额外把 add / remove / fetch / set / save / destroy 视为动词段
  --json    输出 JSON 便于 CI 聚合
  --verbose 打印全部扫描到的路由路径（配合 --json 诊断）
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SERVICES = ("admin-api", "chat-api", "document-parser")
ROUTES_REL = "app/api/routes"

# FR-1 明列的动词段
DEFAULT_VERBS = ("get", "list", "create", "update", "delete", "do")
STRICT_VERBS = ("add", "remove", "fetch", "set", "save", "destroy")

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _iter_routes(root: Path):
    """遍历三个服务 routes 目录下所有 .py 文件。"""
    for service in SERVICES:
        routes_dir = root / "services" / service / ROUTES_REL
        if not routes_dir.is_dir():
            continue
        for path in sorted(routes_dir.rglob("*.py")):
            yield service, path


def _parse_prefix(path: Path) -> str:
    """解析文件里 `router = APIRouter(prefix=...)` 的 prefix 常量值。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return ""
    prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "router":
                    prefix = _prefix_of(node.value)
                    break
    return prefix


def _prefix_of(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return ""


def _method_of(decorator: ast.AST) -> str | None:
    """从 `@router.get("...", ...)` 装饰器取 (http_method, path)。"""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    method = func.attr
    if method not in HTTP_METHODS:
        return None
    # func.value 应为 Name('router')
    if not isinstance(func.value, ast.Name) or func.value.id != "router":
        return None
    if not decorator.args:
        return None
    arg0 = decorator.args[0]
    if not isinstance(arg0, ast.Constant) or not isinstance(arg0.value, str):
        return None
    return f"{method.upper()} {arg0.value}"


def _is_false(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _is_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_compat_alias(decorator: ast.AST) -> bool:
    """`include_in_schema=False` 或 `deprecated=True` 的装饰器视为向后兼容别名。

    T009/T010 把违规动词段改名后，旧路径会以 ``include_in_schema=False`` 注册为
    重定向别名（不入公开 API 文档），默认不参与命名检查；``--strict`` 下仍检查，
    这样整改后仓库默认 0 违规，又不至于在严格模式下漏掉真问题。
    """
    if not isinstance(decorator, ast.Call):
        return False
    for kw in decorator.keywords:
        if kw.arg == "include_in_schema" and _is_false(kw.value):
            return True
        if kw.arg == "deprecated" and _is_true(kw.value):
            return True
    return False


def _join(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if path.startswith("/"):
        return prefix + path
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _segments(route: str) -> list[str]:
    out = []
    for seg in route.split("/"):
        if not seg:
            continue
        if seg.startswith("{") or ":" in seg:
            out.append(None)  # 路径变量，跳过
            continue
        out.append(seg)
    return out


def _hit(seg: str, verbs: tuple[str, ...]) -> str | None:
    if seg is None:
        return None
    if seg.startswith("_"):
        return None
    low = seg.lower()
    for verb in verbs:
        if low == verb:
            return verb
        if low.startswith(verb) and len(low) > len(verb):
            # 用原始段判边界：camelCase（getUsers→'U'）/snake（do_parse→'_'）/数字（list0）
            nxt = seg[len(verb)]
            if nxt.isupper() or nxt == "_" or nxt.isdigit():
                return verb
    return None


def scan(root: Path, verbs: tuple[str, ...], verbose: bool, strict: bool = False) -> list[dict]:
    problems: list[dict] = []
    seen_paths: list[dict] = []

    for service, path in _iter_routes(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        prefix = _parse_prefix(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                info = _method_of(dec)
                if info is None:
                    continue
                route = _join(prefix, info.split(" ", 1)[1])
                full = info.split(" ", 1)[0] + " " + route
                alias = _is_compat_alias(dec)
                seen_paths.append(
                    {
                        "service": service,
                        "file": str(path.relative_to(root)),
                        "route": full,
                        "alias": alias,
                    }
                )
                if alias and not strict:
                    # 兼容别名（旧路径重定向）不入公开 schema，默认跳过
                    continue
                for seg in _segments(route):
                    verb = _hit(seg, verbs)
                    if verb:
                        problems.append(
                            {
                                "service": service,
                                "file": str(path.relative_to(root)),
                                "route": full,
                                "segment": seg,
                                "verb": verb,
                            }
                        )

    if verbose:
        for item in seen_paths:
            if item.get("alias"):
                print(f"[alias] {item['service']:15s} {item['route']}  （兼容别名，默认跳过）")
            else:
                print(f"[route] {item['service']:15s} {item['route']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    verbs = DEFAULT_VERBS + (STRICT_VERBS if args.strict else ())

    problems = scan(root, verbs, args.verbose, strict=args.strict)

    if args.json:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=2))
    else:
        for p in problems:
            print(
                f"[verb] {p['service']:15s} {p['route']} "
                f"（段 `{p['segment']}` 命中动词 `{p['verb']}`）"
                f"  @ {p['file']}"
            )

    if problems:
        print(f"\npath-naming FAILED — {len(problems)} verb segment(s)", file=sys.stderr)
        return 1
    print("path-naming OK — no verb segments found")
    return 0


if __name__ == "__main__":
    sys.exit(main())