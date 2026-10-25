#!/usr/bin/env python3
r"""025 T021 / T022 / T023 — 错误响应规范静态扫描（FR-10 / FR-11 / FR-12）。

扫描 `services/{admin-api,chat-api,document-parser}/app/api/routes/**/*.py` 中所有错误
响应构造点（`HTTPException` / `build_error_payload` / `JSONResponse`），按四类报告：

- `[code]` 稳定错误码：detail 为 dict 且含 `code` 键时，值必须是 `ApiErrorCode.XXX`
  或已登记注册表的 `api.<域>.<名>` 字符串；否则违规。**纯字符串 detail（无 code）只给
  `[info]` 提示，不算违规**——与 errors.py 声明的兼容层口径一致（T011 范围）。
- `[leak]` 不泄漏内部信息（FR-12）：detail / message 里出现内部模块名（`app.*`）、
  绝对文件路径、SQL 关键字片段、`v\d+\.\d+` 版本号、`Traceback` / `File "` 堆栈片段。
- `[auth-shape]` 401/403 同形（FR-12）：登录相关端点若同时存在「用户不存在」型与
  「密码错误」型两条**不同** 401/403 响应文本 → 违规（泄漏资源存在性）。
- `[openapi]` OpenAPI 引用 ErrorResponse：各服务 `app/main.py` 未把通用 4xx/5xx 响应
  schema 引用到 `ErrorResponse` → 违规。

风格对齐 `tools/api_check/error_codes_uniqueness.py`：CLI + 退出码 0 通过 / 1 违规 +
打印明细 + REPO 相对路径定位。
用法：python3 tools/api_check/error_response_refs.py [--openapi] [--root <仓库根>]
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[2]

SERVICES = ("admin-api", "chat-api", "document-parser")
ROUTES_DIR = "services/{}/app/api/routes"
# chat-api 无 `app/api/routes/` 目录（路由在 `app/api/endpoints/*.py`），扫描时兜底。
ROUTES_DIR_FALLBACK = "services/{}/app/api/endpoints"
MAIN_PY = "services/{}/app/main.py"

# ── [code]：错误码识别 ──
CODE_PREFIX = "api."
# 025 T022 遗留豁免：这些自定义字符串码是**既有跨服务前端契约**
# （apps/admin-web 与 apps/user-web 的 skillInstallError.ts / messages.ts、
# 以及 DSH 会话/工具执行的既有错误映射）依赖它们做错误提示，
# 不以 `api.` 开头、无法登记进 T001 注册表。强改会破坏前端错误提示与 DSH 契约。
# 显式白名单 + 文档化，待前端联动后再迁移；不计违规，只给 info 提示。
LEGACY_CODES = frozenset({
    # admin-api
    "DUPLICATE_FILENAME",
    "zip_required",
    "archive_too_large",
    "release_digest_mismatch",
    # chat-api（apps/admin-web、apps/user-web 与 DSH 运行时依赖）
    "position_role_denied",
    "session_already_running",
    "dsh_runtime_unavailable",
    "dsh_cancel_pending",
    "skill_upgrade_confirmation_required",
    "organization_install_forbidden",
    "skill_publish_required",
    "tool_execution_failed",
})
ENUM_ASSIGN_RE = re.compile(r'=\s*"(api\.[a-z0-9_.]+)"')
ENUM_MEMBER_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*\"(api\.[a-z0-9_.]+)\"\s*$", re.M)

# ── [leak]：内部信息正则 ──
MODULE_RE = re.compile(r"\bapp\.[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*")
ABS_PATH_RE = re.compile(r"(?:/[A-Za-z0-9_.\-~]{1,}){2,}|[A-Za-z]:\\[^\"'\s]*")
SQL_RE = re.compile(
    r"\b(?:SELECT\b[^\"'\n]{0,40}\bFROM\b|INSERT\s+INTO\b|DELETE\s+FROM\b|UPDATE\s+[a-z_]+\s+SET\b)",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")
STACK_RE = re.compile(r"\bTraceback\b|File \"| at 0x[0-9a-fA-F]{6,}")

LEAK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (MODULE_RE, "内部模块名 app.*"),
    (ABS_PATH_RE, "绝对文件路径"),
    (SQL_RE, "SQL 片段"),
    (VERSION_RE, "版本号"),
    (STACK_RE, "堆栈片段"),
]

# ── [auth-shape]：登录语义分类 ──
NOTFOUND_RE = re.compile(
    r"(user|account|用户|账号)\s*(not found|不存在|未找到|not exist)", re.IGNORECASE
)
PASSWORD_RE = re.compile(
    r"(password|密码|credential|凭证|口令)\s*(wrong|incorrect|invalid|不正确|错误|无效|失配)",
    re.IGNORECASE,
)


@dataclass
class Issue:
    """一条违规（或提示）。"""

    category: str
    path: str  # REPO 相对路径
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line} [{self.category}] {self.message}"


# ── 注册表 ────────────────────────────────────────────────────────────────────────


def load_registry(root: Path | None = None) -> dict[str, str]:
    """返回 {code: 来源 errors.py 相对路径}，来自各服务 app/core/errors.py 的枚举赋值。"""
    base = root or REPO
    registry: dict[str, str] = {}
    for service in SERVICES:
        path = base / f"services/{service}/app/core/errors.py"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for code in ENUM_ASSIGN_RE.findall(text):
            registry.setdefault(code, f"services/{service}/app/core/errors.py")
    return registry


def load_enum_members(root: Path | None = None) -> set[str]:
    """所有服务 errors.py 里声明的枚举成员名集合（`XXX = "api.xxx"`）。"""
    base = root or REPO
    members: set[str] = set()
    for service in SERVICES:
        path = base / f"services/{service}/app/core/errors.py"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in ENUM_MEMBER_RE.finditer(text):
            members.add(m.group(1))
    return members


# ── AST 辅助 ──────────────────────────────────────────────────────────────────────


def _string_literals(node: ast.AST) -> Iterable[tuple[int, str]]:
    """递归提取表达式树里的字符串常量与 f-string 片段。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.lineno, node.value
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield part.lineno, part.value
    else:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Constant, ast.JoinedStr, ast.Dict, ast.List, ast.Tuple)):
                yield from _string_literals(child)


def _enum_member_ref(attr: ast.Attribute) -> str | None:
    """判断 Attribute 是否是 ApiErrorCode 的成员引用，返回成员名（如 'VALIDATION_ERROR'）。"""
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", attr.attr) and isinstance(attr.value, ast.Name):
        if attr.value.id == "ApiErrorCode":
            return attr.attr
    return None


def _static_code(node: ast.expr) -> tuple[str, str] | None:
    """静态解析 code 表达式，返回 ('enum', 成员名) 或 ('literal', 字符串值)；无法识别→None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "literal", node.value
    if isinstance(node, ast.Attribute):
        # ApiErrorCode.MEMBER 或 ApiErrorCode.MEMBER.value
        member = _enum_member_ref(node)
        if member is None and isinstance(node.value, ast.Attribute) and node.attr == "value":
            member = _enum_member_ref(node.value)
        if member is not None:
            return "enum", member
    return None


def _static_int(node: ast.expr | None) -> int | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute) and node.attr.isdigit() and len(node.attr) == 3:
        return int(node.attr)
    return None


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _rel(path: Path, root: Path | None = None) -> str:
    base = root or REPO
    try:
        return str(path.resolve().relative_to(base))
    except ValueError:
        return str(path)


def _classify_auth_shape(msg: str) -> str | None:
    if NOTFOUND_RE.search(msg):
        return "notfound"
    if PASSWORD_RE.search(msg):
        return "password"
    return None


# ── 单文件扫描 ────────────────────────────────────────────────────────────────────


def scan_file(
    path: Path,
    registry: dict[str, str],
    enum_members: set[str],
    root: Path | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError) as exc:
        issues.append(Issue("parse", _rel(path, root), 0, f"无法解析: {exc}"))
        return issues

    rel = _rel(path, root)
    auth_shapes: list[tuple[int, str]] = []  # (行号, 分类) 用于 auth-shape 判定

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = _call_name(node)
        if func_name not in ("HTTPException", "build_error_payload", "JSONResponse"):
            continue

        status_expr: ast.expr | None = None
        detail_expr: ast.expr | None = None
        message_expr: ast.expr | None = None
        code_expr: ast.expr | None = None
        for kw in node.keywords:
            if kw.arg == "status_code":
                status_expr = kw.value
            elif kw.arg == "detail":
                detail_expr = kw.value
            elif kw.arg == "message":
                message_expr = kw.value
            elif kw.arg == "code":
                code_expr = kw.value
        if func_name == "HTTPException" and detail_expr is None and len(node.args) >= 2:
            detail_expr = node.args[1]

        if func_name == "JSONResponse":
            content_expr = None
            for kw in node.keywords:
                if kw.arg == "content":
                    content_expr = kw.value
            if content_expr is None and node.args:
                content_expr = node.args[0]
            if isinstance(content_expr, ast.Call) and _call_name(content_expr) == "build_error_payload":
                for kw in content_expr.keywords:
                    if kw.arg == "code":
                        code_expr = kw.value
                    elif kw.arg == "message":
                        message_expr = kw.value
                detail_expr = message_expr
            else:
                detail_expr = content_expr

        text_expr = detail_expr if detail_expr is not None else message_expr
        raw_lines: list[tuple[int, str]] = []
        if text_expr is not None:
            raw_lines = list(_string_literals(text_expr))

        # ── [code] ──
        code_to_check: tuple[int, ast.expr] | None = None
        if code_expr is not None:
            code_to_check = (code_expr.lineno, code_expr)
        elif isinstance(detail_expr, ast.Dict):
            for key, value in zip(detail_expr.keys, detail_expr.values):
                if key is None or value is None:
                    continue
                if isinstance(key, ast.Constant) and str(key.value) == "code":
                    code_to_check = (value.lineno, value)
                    break
            else:
                issues.append(Issue(
                    "info", rel, node.lineno,
                    "detail 为 dict 但无 code 键（兼容层允许，仅提示）",
                ))

        if code_to_check is not None:
            ln, expr = code_to_check
            info = _static_code(expr)
            if info is None:
                issues.append(Issue(
                    "code", rel, ln,
                    "code 不是可静态识别的 ApiErrorCode 成员或 api.* 字面量",
                ))
            elif info[0] == "literal":
                value = info[1]
                if value in LEGACY_CODES:
                    issues.append(Issue(
                        "info", rel, ln,
                        f"legacy 自定义错误码 {value!r}（豁免，见 LEGACY_CODES 说明，待前端联动后迁移）",
                    ))
                elif not value.startswith(CODE_PREFIX):
                    issues.append(Issue(
                        "code", rel, ln,
                        f"稳定错误码必须以 {CODE_PREFIX} 开头，实际: {value!r}",
                    ))
                elif value not in registry:
                    issues.append(Issue(
                        "code", rel, ln,
                        f"code {value} 不在错误码注册表（app/core/errors.py 未登记）",
                    ))
            else:  # enum 成员
                if info[1] not in enum_members:
                    issues.append(Issue(
                        "code", rel, ln,
                        f"ApiErrorCode.{info[1]} 不是已登记的错误码枚举成员",
                    ))
        elif detail_expr is not None and not isinstance(detail_expr, ast.Dict):
            issues.append(Issue(
                "info", rel, node.lineno,
                "detail 为纯字符串、无稳定 code（兼容层允许，仅提示）",
            ))

        # ── [leak] ──
        for ln, text in raw_lines:
            for pattern, label in LEAK_PATTERNS:
                if pattern.search(text):
                    issues.append(Issue(
                        "leak", rel, ln, f"{label}: {text.strip()[:160]}",
                    ))
                    break

        # ── [auth-shape] 收集 ──
        status = _static_int(status_expr)
        if status in (401, 403):
            for _, text in raw_lines:
                cat = _classify_auth_shape(text)
                if cat:
                    auth_shapes.append((node.lineno, cat))

    # 同一文件内同时出现两类登录语义 → 违规
    cats: dict[str, list[int]] = {}
    for ln, cat in auth_shapes:
        cats.setdefault(cat, []).append(ln)
    if "notfound" in cats and "password" in cats:
        issues.append(Issue(
            "auth-shape", rel, cats["notfound"][0],
            "登录端点 401/403 区分资源存在性：notfound 行 vs password 行"
            f"（FR-12 要求同形；notfound@{cats['notfound'][0]} password@{cats['password'][0]}）",
        ))
    return issues


# ── 目录 / 全量扫描 ───────────────────────────────────────────────────────────────


def scan_routes_tree(
    root: Path,
    registry: dict[str, str],
    enum_members: set[str],
    repo: Path | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    if not root.exists():
        return issues
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        issues.extend(scan_file(path, registry, enum_members, repo))
    return issues


def _service_route_dir(base: Path, service: str) -> Path:
    """返回某服务的路由目录；无 `app/api/routes` 时兜底 `app/api/endpoints`（chat-api）。"""
    primary = base / ROUTES_DIR.format(service)
    if primary.exists():
        return primary
    return base / ROUTES_DIR_FALLBACK.format(service)


def iter_route_files(root: Path | None = None) -> Iterable[Path]:
    base = root or REPO
    for service in SERVICES:
        d = base / ROUTES_DIR.format(service)
        if not d.exists():
            continue
        for path in sorted(d.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path


def _code_text(path: Path) -> str:
    """提取 .py 文件的"代码文本"：去掉注释、docstring、字符串常量。

    用于检查 main.py 是否**实际使用**了 ErrorResponse，避免被注释里的
    "响应体为 ... ErrorResponse 结构" 之类说明文字误导。
    """
    import io
    import tokenize

    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL):
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        return text
    return " ".join(out)


def check_openapi(root: Path | None = None) -> list[Issue]:
    """检查各服务 app/main.py 是否把通用错误响应引用到 ErrorResponse。"""
    base = root or REPO
    issues: list[Issue] = []
    for service in SERVICES:
        main_path = base / MAIN_PY.format(service)
        if not main_path.exists():
            continue
        if "ErrorResponse" not in _code_text(main_path):
            issues.append(Issue(
                "openapi",
                _rel(main_path, base),
                0,
                "未把通用 4xx/5xx 响应 schema 引用到 ErrorResponse",
            ))
    return issues


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", action="store_true", help="只检查 OpenAPI 引用")
    parser.add_argument("--root", type=Path, default=None, help="仓库根（默认由脚本路径推断）")
    args = parser.parse_args(argv)
    root = args.root or REPO

    registry = load_registry(root)
    enum_members = load_enum_members(root)

    issues: list[Issue] = []
    if args.openapi:
        issues = check_openapi(root)
    else:
        for service in SERVICES:
            issues.extend(
                scan_routes_tree(_service_route_dir(root, service), registry, enum_members, root)
            )
        issues.extend(check_openapi(root))

    violations = [i for i in issues if i.category not in ("info", "parse")]
    infos = [i for i in issues if i.category == "info"]
    parses = [i for i in issues if i.category == "parse"]

    print(f"registered error codes: {len(registry)} | enum members: {len(enum_members)}")
    if parses:
        print("PARSE ERRORS:")
        for i in parses:
            print("  " + i.render())
    if violations:
        print("error-response refs FAILED:")
        for i in violations:
            print("  " + i.render())
    if infos:
        print(f"info ({len(infos)} 条兼容层提示，不计入违规):")
        for i in infos[:20]:
            print("  " + i.render())
        if len(infos) > 20:
            print(f"  ... 还有 {len(infos) - 20} 条")
    if not violations:
        print(f"error-response refs OK — {len(infos)} informational notes, 0 violations")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())