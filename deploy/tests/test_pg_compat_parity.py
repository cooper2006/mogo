"""PanWeiDB 兼容层的一致性守卫。

背景：`app/core/pg_compat.py` 在三个服务各有一份（仓库既有架构就是每服务自包含，
`app/core/db.py` / `app/core/config.py` 同样如此）。重复代码最大的风险是**漂移**：
只改了 admin-api 那一份，另两个服务的翻译规则就悄悄落后了。

本守卫固化三件事：

1. **异步两份必须逐字节相同**（admin-api 与 chat-api 都用 motor，兼容层完全一致）。
2. **同步那份必须等于异步份的机械变换结果**（`async def`→`def`、`async with`→`with`、
   `async for`→`for`、去掉 `await`，并把游标换成同步迭代）。这样只要有人改了异步版
   而忘了同步版，测试就会失败并指出差异。
3. **不得引入 PanWeiDB A 模式禁用的 JSONB 函数/运算符**（`sql_compatibility=A`
   下会报 `FeatureNotSupported`，且该参数是 `internal` 上下文、不可修改）。

运行::

    python -m pytest deploy/tests/test_pg_compat_parity.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("admin-api", "chat-api", "document-parser")
ASYNC_SERVICES = ("admin-api", "chat-api")
SYNC_SERVICE = "document-parser"

#: A 模式下实测不可用的 JSONB **函数名**（2026-10-13 实测）。
FORBIDDEN_FUNCTIONS = (
    "jsonb_build_array",
    "jsonb_build_object",
    "jsonb_strip_nulls",
    "jsonb_pretty",
    "jsonb_to_record",
    "jsonb_object_agg",
    "jsonb_path_ops",
)

#: A 模式下不可用的 **运算符**：`doc #- '{a,b}'`（删路径）。
FORBIDDEN_OPERATOR_PATTERN = re.compile(r"#-\s*'")

#: 同步版游标块的替换文本，必须与生成脚本一致。
SYNC_CURSOR_BLOCK = '''class PgCursor:
    """``find()`` 的返回物；支持 ``for doc in cursor`` 与 ``to_list()``。"""

    def __init__(self, collection: "PgCollection", filt: Mapping[str, Any] | None) -> None:
        self._collection = collection
        self._filter = filt or {}
        self._sort: list[tuple[str, int]] = []
        self._limit = 0
        self._skip = 0
        self.projection: Mapping[str, Any] | None = None

    def sort(self, key: Any, direction: int | None = None) -> "PgCursor":
        if isinstance(key, str):
            self._sort.append((key, 1 if direction is None else int(direction)))
        else:
            for field, order in key:
                self._sort.append((str(field), int(order)))
        return self

    def limit(self, count: int) -> "PgCursor":
        self._limit = int(count)
        return self

    def skip(self, count: int) -> "PgCursor":
        self._skip = int(count)
        return self

    def __iter__(self) -> Iterator[dict[str, Any]]:
        yield from self._collection._run_find(self)

    def __len__(self) -> int:
        return len(self._collection._run_find(self))

    def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = self._collection._run_find(self)
        if length is not None and length >= 0:
            return docs[:length]
        return docs


'''


def _read(service: str, module: str) -> str:
    path = REPO_ROOT / "services" / service / "app" / "core" / module
    assert path.is_file(), f"缺少 {path}"
    return path.read_text(encoding="utf-8")


def _to_sync(async_source: str) -> str:
    """把异步兼容层机械变换成同步版（与生成时使用的变换完全一致）。"""
    text = async_source.replace(
        "from typing import Any, AsyncIterator, Iterable, Mapping, Sequence",
        "from typing import Any, Iterable, Iterator, Mapping, Sequence",
    )
    text = text.replace("async with ", "with ")
    text = text.replace("async for ", "for ")
    text = text.replace("async def ", "def ")
    text = re.sub(r"\bawait\s+", "", text)
    start = text.index("class PgCursor:")
    end = text.index("# ── 集合 ─")
    text = text[:start] + SYNC_CURSOR_BLOCK + text[end:]
    return text.replace("**R1 已实现**", "**R1 已实现（同步 pymongo 子集）**")


@pytest.mark.parametrize("service", SERVICES)
def test_pg_compat_exists(service: str) -> None:
    assert _read(service, "pg_compat.py")


def test_async_copies_are_byte_identical() -> None:
    sources = {service: _read(service, "pg_compat.py") for service in ASYNC_SERVICES}
    baseline_service, baseline = next(iter(sources.items()))
    for service, source in sources.items():
        assert source == baseline, (
            f"services/{service}/app/core/pg_compat.py 与 "
            f"services/{baseline_service}/app/core/pg_compat.py 不一致；"
            "两份异步兼容层必须完全相同，否则翻译规则会漂移。"
        )


def test_sync_copy_matches_async_after_transformation() -> None:
    async_source = _read(ASYNC_SERVICES[0], "pg_compat.py")
    expected = _to_sync(async_source)
    actual = _read(SYNC_SERVICE, "pg_compat.py")
    if actual != expected:
        actual_lines = actual.splitlines()
        expected_lines = expected.splitlines()
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(actual_lines, expected_lines)) if a != b),
            min(len(actual_lines), len(expected_lines)),
        )
        pytest.fail(
            f"services/{SYNC_SERVICE}/app/core/pg_compat.py 已与异步版脱节"
            f"（首个差异在第 {first_diff + 1} 行）。\n"
            "请按 docs/mongo-to-panweidb-migration-plan.md 的说明重新生成同步版，"
            "或同步更新本测试里的变换规则。"
        )


def _code_identifiers(source: str) -> set[str]:
    """提取源码里**作为标识符**出现的名字（丢弃字符串与注释）。

    直接对原文做子串匹配会误伤——本模块的文档字符串与行内注释里**必须**提到这些
    禁用函数名（它们正是用来解释「为什么不能用」的）。因此用 tokenize 只看真实代码。
    """
    import io
    import tokenize

    names: set[str] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.NAME:
                names.add(token.string)
    except (tokenize.TokenError, IndentationError):  # pragma: no cover - 语法错误另有测试兜底
        pass
    return names


@pytest.mark.parametrize("service", SERVICES)
def test_no_functions_unavailable_in_panweidb_a_mode(service: str) -> None:
    source = _read(service, "pg_compat.py")
    identifiers = _code_identifiers(source)
    offenders = [name for name in FORBIDDEN_FUNCTIONS if name in identifiers]
    assert not offenders, (
        f"services/{service}/app/core/pg_compat.py 的**代码**里使用了 PanWeiDB A 模式"
        f"禁用的 {offenders}。sql_compatibility=A 是 internal 参数、不可修改，"
        "这些函数会报 FeatureNotSupported；请改用文档「A 模式下的 JSONB 能力」"
        "一节列出的替代手法。"
    )
    assert not FORBIDDEN_OPERATOR_PATTERN.search(source), (
        f"services/{service}/app/core/pg_compat.py 使用了 `#-` 删路径运算符；"
        "A 模式下不可用，请改用 _unset_expression() 的「取出父节点 → 删键 → 写回」写法。"
    )


@pytest.mark.parametrize("service", SERVICES)
def test_pg_module_has_both_pools(service: str) -> None:
    """连接池模块必须提供健康探测与关闭入口，供 /health 与生命周期使用。"""
    source = _read(service, "pg.py")
    assert "def health_payload" in source
    assert "def close_pg" in source
    if service in ASYNC_SERVICES:
        assert "async def init_async_pg" in source
        assert "async def close_async_pg" in source
        # 异步服务的健康检查必须走异步探测，否则会为了探活额外建一组同步连接池。
        assert "async def health_payload" in source
        assert "await ping_async()" in source


def _strip_docstrings(source: str) -> str:
    """去掉模块/类/函数的 docstring，返回可检查的代码文本。

    本仓库的守卫普遍需要「只看真实代码」——被检查的模块**必须**在文档字符串里
    提到被禁用的东西（那正是用来解释「为什么不能用」的），直接子串匹配会误报。
    """
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
    return ast.unparse(tree)


def test_ddl_generator_does_not_emit_gin_index() -> None:
    """建表 DDL 不得生成 GIN 索引。

    实测（2026-10-13）：openGauss 的 ``USING GIN (doc jsonb_ops)`` 遇到**任何空字符串
    值**就报 ``jsonb_gin.cpp : 519 : The parameter destMax is equal to zero ...``，
    顶层与嵌套值都触发；更麻烦的是表里只要已有一行含空串，连 ``CREATE INDEX`` 本身
    都会失败。空串在真实数据里极其常见（``email: ""`` / ``phone: ""``），
    因此 DDL 只建 ``tenant_id`` btree 索引。

    实测对照（同一张含空串的表）：无索引 ✅ / ``btree (tenant_id)`` ✅ /
    ``btree ((doc #> '{f}'))`` ✅ / ``GIN (doc jsonb_ops)`` ❌。
    """
    source = (REPO_ROOT / "scripts" / "pg" / "generate_ddl.py").read_text(encoding="utf-8")
    assert "USING GIN" not in _strip_docstrings(source), (
        "scripts/pg/generate_ddl.py 又生成了 GIN 索引。openGauss 的 jsonb GIN 索引"
        "在遇到空字符串值时会报错（见本测试文档字符串），请勿恢复。"
    )
    schema_sql = REPO_ROOT / "deploy" / "pg" / "schema.sql"
    if schema_sql.is_file():
        # SQL 文件没有 docstring，但 `--` 注释里会解释原因，同样要先剔除。
        sql_body = "\n".join(
            line for line in schema_sql.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("--")
        )
        assert "USING GIN" not in sql_body, (
            "deploy/pg/schema.sql 含 GIN 索引；请重新运行 generate_ddl.py 生成。"
        )


def test_ddl_generator_supports_authoritative_mongo_source() -> None:
    """DDL 生成器必须支持以源 MongoDB 为权威来源（静态扫描有已知漏扫）。

    集合名若来自配置项（如 document-parser 的 ``settings.jobs_collection``）、
    f-string 或变量传递，静态扫描看不到。实测该漏扫会导致 DDL 少 11 张表。
    """
    source = (REPO_ROOT / "scripts" / "pg" / "generate_ddl.py").read_text(encoding="utf-8")
    assert "--from-mongo" in source
    assert "collect_names_from_mongo" in source


def test_migration_tool_documents_delete_semantics() -> None:
    """搬迁工具必须提供 --prune 并有说明。

    upsert 只能保证「源库有的目标库也有」；源库在搬迁期间被写入（会话 GC / TTL 清理）
    时，目标库会留残留，导致 ``--verify`` 报「目标多于源」。
    """
    source = (REPO_ROOT / "scripts" / "pg" / "migrate_mongo_to_panweidb.py").read_text(encoding="utf-8")
    assert "--prune" in source
    assert "def prune_collection" in source
