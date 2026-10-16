"""MongoDB → PanWeiDB 兼容门面（Motor / PyMongo 子集）。

目标：让 ``app/core/db.get_db()`` 在 ``MOGO_DATA_BACKEND=panweidb`` 时返回一个
**形状与 motor 一致**的对象，使既有业务调用点无需改动即可读写 PanWeiDB。
完整映射规则、覆盖范围与已知缺口见
``docs/mongo-to-panweidb-migration-plan.md``。

表结构约定（每个集合一张表，表名 = 集合名）::

    CREATE TABLE <collection> (
        id         TEXT PRIMARY KEY,        -- str(_id)
        tenant_id  TEXT,                    -- 从文档提升，用于租户隔离与清理
        doc        JSONB NOT NULL,          -- 完整文档（含 _id 原值）
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

字段访问一律走 JSONB 路径表达式（``doc #> '{a,b}'``），不依赖预建列，
因此新增字段无需 DDL 变更。

**R1 已实现（同步 pymongo 子集）**：``find_one`` / ``find`` / ``insert_one`` / ``insert_many`` /
``replace_one`` / ``update_one`` / ``update_many`` / ``find_one_and_update`` /
``delete_one`` / ``delete_many`` / ``count_documents`` / ``distinct`` /
``create_index`` / ``create_indexes`` / ``list_collection_names`` / ``command``。

过滤算子：``$eq $ne $gt $gte $lt $lte $in $nin $exists $regex $or $and $nor
$not $all $size``。
更新算子：``$set $unset $inc $setOnInsert $push $addToSet $max $min $currentDate``。

**明确未覆盖**（调用即抛 :class:`PgCompatUnsupported`，消息指向迁移文档）：
``aggregate`` 管道（含 ``$lookup``/``$facet``/``$graphLookup``/``$unwind``）、
``bulk_write``、``$elemMatch``、``$pull``、``$text``/``$near`` 等。这些调用点
需要在 R2 改写为 SQL 或扩展本模块。

**PanWeiDB A 模式（``sql_compatibility=A``）的函数限制**（实测 2026-10-13）：
``sql_compatibility`` 是 ``internal`` 上下文、不可改，且 PanWeiDB 3.2 的
``CREATE DATABASE`` 不支持 ``DBCOMPATIBILITY`` 选项，因此**必须**在 A 模式子集内实现：

* 可用：``jsonb_set`` / ``jsonb_typeof`` / ``jsonb_array_length`` / ``to_jsonb`` /
  ``||`` / ``@>`` / ``?`` / ``jsonb_agg`` / ``jsonb_array_elements`` /
  ``jsonb_extract_path(_text)`` / ``jsonb_insert`` / ``jsonb_path_query`` /
  ``jsonb - text`` / ``jsonb_delete``
* **不可用**：``jsonb_build_array`` / ``jsonb_build_object`` / ``#-`` /
  ``jsonb_strip_nulls`` / ``jsonb_pretty`` / ``jsonb_to_record`` / ``jsonb_object_agg``

**GIN 索引不可用（openGauss 缺陷，实测 2026-10-13）**：
``USING GIN (doc jsonb_ops)`` 遇到**任何空字符串值**就报
``jsonb_gin.cpp : 519 : The parameter destMax is equal to zero ...``（顶层与嵌套值均触发）。
更麻烦的是表里只要已有一行含空串，**连 ``CREATE INDEX`` 本身都会失败**。
空串在真实数据里极其常见（``email: ""`` / ``phone: ""``），因此建表 DDL
**只建 ``tenant_id`` btree 索引，不建 GIN**。实测对照：无索引 / ``btree (tenant_id)`` /
``btree ((doc #> '{f}'))`` 三者遇空串均可写，只有 GIN 失败。
代价可控：GIN 只服务于 ``@>`` / ``?``，而本模块只有 ``$all`` 用到 ``@>``；
按字段过滤走 ``create_index`` 生成的表达式索引。

对应的规避手法已内联在实现里（``_unset_expression`` 与 ``$push`` 分支），
修改本模块时不要引入上述不可用函数。

**R3 扁平化（027 方案 §5，2026-10-16 起）**：``docs/027-r3-relational-four-tables-plan.md``
对 44 张表做了扁平化（21 全 + 23 部分），库内已加列回填（见
``specs/027-mongo-to-panweidb-migration/r3-flatten/``）。本模块据此做 §5 的
兼容层改造，数据源是 ``app/core/column_map.py`` 的 ``COLUMN_MAP``：

* **双写**：``INSERT`` / ``UPDATE`` / ``replace_one`` 在同一语句内把 doc 键同步
  写进映射列（``_update`` 直接基于新 doc 的 ``#>>`` 表达式，保持原子性；
  jsonb 路径一律用 ``#>`` / ``#>>``，本库没有 ``->> text[]`` 运算符）。
* **读路径列优先**：``find_one`` / ``find`` 的 ``SELECT`` 附带映射列，列值非空
  即覆盖 doc 同名键（datetime 序列化回 ISO 字符串，doc 形状不变）。doc 仍是
  兜底与 ❌ / 🔶 动态字段的存储，因此 ``doc JSONB NOT NULL`` 保留。
* **筛选 / 索引路由**：COLUMN_MAP 命中的键走真实列（可用 btree 索引），未命中
  走 doc JSONB 路径；``$size`` / ``$all`` / ``$type`` 仅对 JSONB 型映射列生效。
* **排序 / 去重 / 聚合路由（后续优化已落地）**：``ORDER BY``（find_one、cursor
  sort）与 ``distinct`` 对命中的顶层键走真实列；``aggregate`` 的 ``$match`` /
  ``$sort`` 仅在**直接读基表的首阶段**路由（CTE 阶段只有 ``(id, doc)``，
  没有那些列，维持 doc 路径）。``$group`` 的 ``_id`` 与累加器仍走 doc 路径
  （jsonb 分组与输出组装语义不变，留待后续）。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Iterator, Mapping, Sequence

from app.core.column_map import column_type, mapped_columns

logger = logging.getLogger(__name__)


class PgCompatUnsupported(NotImplementedError):
    """调用了 R1 尚未覆盖的 Mongo API / 算子。"""

    def __init__(self, what: str) -> None:
        super().__init__(
            f"{what} 尚未在 PanWeiDB 兼容层实现。"
            "参见 docs/mongo-to-panweidb-migration-plan.md 的「覆盖范围与缺口」；"
            "该调用点需在 R2 改写为 SQL 或扩展 app/core/pg_compat.py。"
        )
        self.what = what


# ── 结果对象（形状对齐 pymongo，业务代码只读属性）─────────────────────
class InsertOneResult:
    __slots__ = ("inserted_id", "acknowledged")

    def __init__(self, inserted_id: Any) -> None:
        self.inserted_id = inserted_id
        self.acknowledged = True


class InsertManyResult:
    __slots__ = ("inserted_ids", "acknowledged")

    def __init__(self, inserted_ids: list[Any]) -> None:
        self.inserted_ids = inserted_ids
        self.acknowledged = True


class UpdateResult:
    __slots__ = ("matched_count", "modified_count", "upserted_id", "acknowledged")

    def __init__(self, matched_count: int, modified_count: int, upserted_id: Any = None) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id
        self.acknowledged = True


class DeleteResult:
    __slots__ = ("deleted_count", "acknowledged")

    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count
        self.acknowledged = True


class BulkWriteResult:
    """``bulk_write()`` 的结果，字段对齐 pymongo 的 ``BulkWriteResult``。"""

    __slots__ = (
        "inserted_count",
        "matched_count",
        "modified_count",
        "deleted_count",
        "upserted_count",
        "upserted_ids",
        "acknowledged",
        "bulk_api_result",
    )

    def __init__(
        self,
        *,
        inserted_count: int = 0,
        matched_count: int = 0,
        modified_count: int = 0,
        deleted_count: int = 0,
        upserted_ids: Mapping[Any, Any] | None = None,
    ) -> None:
        self.inserted_count = inserted_count
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.deleted_count = deleted_count
        self.upserted_ids = dict(upserted_ids or {})
        self.upserted_count = len(self.upserted_ids)
        self.acknowledged = True
        self.bulk_api_result = {
            "nInserted": inserted_count,
            "nMatched": matched_count,
            "nModified": modified_count,
            "nRemoved": deleted_count,
            "nUpserted": self.upserted_count,
        }


# ── 路径与字面量工具（纯函数，便于单测）──────────────────────────────
_SAFE_PART = re.compile(r"^[A-Za-z0-9_]+$")


def _inline_placeholders(sql: str, params: Sequence[Any]) -> str:
    """把 ``%s`` 占位符替换成 SQL 单引号字面量（仅用于 DDL 上下文）。

    ``CREATE INDEX ... WHERE`` 里 PG 无法推断参数类型（实测连 ``%s::jsonb`` 都报
    ``could not determine data type of parameter $1``），只能内联字面量。
    过滤器传给 :meth:`_FilterCompiler._p` 的值**已经是 JSON 文本**
    （``to_json_text(value``），因此单引号包裹后就是合法的 SQL 字面量。

    仅用于索引定义（源码常量、非用户输入）；普通查询仍然走参数绑定。
    """
    result = sql
    for value in params:
        text = value if isinstance(value, str) else to_json_text(value)
        escaped = text.replace("'", "''")
        result = result.replace("%s", f"'{escaped}'", 1)
    if "%s" in result:
        raise ValueError(f"占位符与参数数量不一致：{result!r} vs {params!r}")
    return result


def translate_regex_pattern(pattern: str) -> str:
    r"""把 MongoDB（PCRE）正则翻译成 openGauss 的 ARE。

    差分测试（32 个构造 × 12 个样本在 MongoDB 6.0 与 PanWeiDB 上比对）发现的
    差异分两类：

    **静默错结果**（最危险，必须翻译）：

    * ``\b`` / ``\B``：PG 的 ARE 里它们是**退格符**而非词边界 ——
      ``'admin' ~ '\badmin\b'`` 实测为 False，即整条模式永远不命中。
      PG 的词边界是 ``\y``（词边界）/ ``\Y``（非词边界）。
    * ``\w`` / ``\W``：PG 在 UTF-8 locale 下**含非 ASCII**
      （``'café' ~ '\w+'`` 为 True），而 PCRE 默认只含 ASCII。
      这里显式换成 ASCII 语义，否则含重音的字段会被多命中。

    **硬报错**（openGauss ARE 不支持，无法靠翻译修复 —— 显式拒绝而非让驱动抛裸错误）：

    * ``\p{...}`` / ``\pL`` Unicode 属性
    * ``(?P<name>...)`` 命名组（PG 用 ``(?<name>...)``）
    * ``[[:word:]]`` 字符类（PG 用 ``[[:alnum:]_]``）

    **已验证一致、无需翻译的构造**：``[a-z]+``、``[[:alnum:]]``、``[[:digit:]]``、
    ``[\w]``、``[\d]``、``\d``、``\s``、``^``／``$``、``|``、``\\``、
    ``(?:...)``、``(?i)``、前向/后向断言、量词、``(?#注释)``、空分支。

    注意字符类**内部**不翻译：类内 ``\b`` 在两个方言里都是退格符。
    """
    out: list[str] = []
    index = 0
    in_class = False
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "\\":
            if index + 1 >= length:
                out.append(char)
                break
            nxt = pattern[index + 1]
            if not in_class:
                if nxt in {"p", "P"}:
                    raise PgCompatUnsupported(
                        fr"$regex 的 \p{{...}}/\pL Unicode 属性（openGauss ARE 不支持）"
                    )
                if nxt == "b":
                    out.append(r"\y")   # PG 的 \b 是退格符，不是词边界
                    index += 2
                    continue
                if nxt == "B":
                    out.append(r"\Y")
                    index += 2
                    continue
                if nxt == "w":
                    out.append("[A-Za-z0-9_]")   # ASCII 语义，避免 UTF-8 locale 吸入非 ASCII
                    index += 2
                    continue
                if nxt == "W":
                    out.append("[^A-Za-z0-9_]")
                    index += 2
                    continue
            out.append(char)
            out.append(nxt)
            index += 2
            continue
        if pattern.startswith("[[:word:]]", index):
            raise PgCompatUnsupported(r"$regex 的 [[:word:]] 字符类（openGauss ARE 不支持，请用 [[:alnum:]_]）")
        if char == "(" and (
            pattern.startswith("(?P<", index) or pattern.startswith("(?P'", index)
        ):
            raise PgCompatUnsupported(r"$regex 的 (?P<name>...) 命名组（openGauss ARE 用 (?<name>...)）")
        if char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        out.append(char)
        index += 1
    return "".join(out)


#: TTL 索引声明登记表：``collection -> (field, expireAfterSeconds)``。
#: openGauss 无原生 TTL 索引，``create_index(..., expireAfterSeconds=N)`` 只登记声明，
#: 过期删除由 :func:`purge_expired_ttl` 在应用层定期执行。
_TTL_REGISTRY: dict[str, tuple[str, int]] = {}


def ttl_registry_snapshot() -> dict[str, tuple[str, int]]:
    """返回 TTL 声明快照（测试 / 诊断用）。"""
    return dict(_TTL_REGISTRY)


def purge_expired_ttl(pool: Any, schema: str, *, now: Any = None) -> int:
    """按登记的 TTL 声明删除过期文档，返回删除总条数（best-effort）。

    对每条声明 ``(field, N)`` 执行
    ``DELETE FROM <schema>.<collection> WHERE (doc->>'<field>')::timestamptz <= now - N 秒``；
    ``N=0`` 即字段值本身是绝对过期时间，与 Mongo ``expireAfterSeconds=0`` 语义一致。
    表不存在（未建表）或权限不足时跳过并记日志，不中断清理循环。
    """
    import logging
    from datetime import datetime, timedelta, timezone

    log = logging.getLogger(__name__)
    reference = now or datetime.now(timezone.utc)
    total = 0
    for collection, (field, seconds) in list(_TTL_REGISTRY.items()):
        cutoff = reference - timedelta(seconds=seconds)
        sql = (
            f'DELETE FROM "{schema}"."{collection}" '
            f"WHERE (doc ->> %s)::timestamptz <= %s"
        )
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, [field, cutoff])
                    total += int(getattr(cur, "rowcount", 0) or 0)
        except Exception:  # noqa: BLE001 - best-effort：单表失败不阻断其余表
            log.warning("TTL 清理失败：%s.%s", schema, collection, exc_info=True)
    return total


def _build_create_index_sql(
    qualified: str,
    index_name: str,
    fields: list[str],
    *,
    unique: bool = False,
    sparse: bool = False,
    partialFilterExpression: Mapping[str, Any] | None = None,
    column_map: Mapping[str, str] | None = None,
) -> str:
    """构造 ``CREATE [UNIQUE] INDEX ...`` 的 SQL（含部分/稀疏 WHERE 子句）。

    纯函数、不触库，便于单测。DDL 上下文里 PG 无法推断参数类型（实测连
    ``%s::jsonb`` 都报 ``could not determine data type of parameter $1``），
    因此 ``partialFilterExpression`` 的参数会被 ``_inline_placeholders`` 内联成
    字面量；过滤器值都来自代码常量、非用户输入，内联前对单引号转义。

    R3 扁平化：``column_map``（表的 {doc_key: column}）命中且顶层字段时，
    直接在真实列上建 btree 索引（替代 ``(doc #> path)`` 表达式索引），
    ``partialFilterExpression`` 也按同一映射编译，保持筛选路径一致。
    """
    columns = dict(column_map or {})

    def _expr(field: str) -> str:
        col = columns.get(field) if "." not in field else None
        return f'"{col}"' if col else f"(doc #> '{path_literal(field)}')"

    expressions = ", ".join(_expr(field) for field in fields)
    conditions: list[str] = []
    params: list[Any] = []
    if sparse:
        conditions.extend(f"{_expr(field)} IS NOT NULL" for field in fields)
    if partialFilterExpression is not None:
        compiler = _FilterCompiler(columns)
        conditions.append(compiler.compile(partialFilterExpression))
        params.extend(compiler.params)
    where_body = _inline_placeholders(
        " AND ".join(conditions) if conditions else "", params
    )
    where_sql = f" WHERE {where_body}" if where_body else ""
    unique_sql = "UNIQUE " if unique else ""
    return (
        f'CREATE {unique_sql}INDEX IF NOT EXISTS "{index_name}" '
        f"ON {qualified} ({expressions}){where_sql}"
    )


def _path_parts(field: str) -> list[str]:
    return field.split(".")


def path_literal(field: str) -> str:
    """把 ``a.b`` 转成 PG jsonb 路径字面量 ``{a,b}``。

    字段名来自代码字面量而非用户输入；仍做白名单校验，避免任意标识符拼进 SQL。
    """
    parts = _path_parts(field)
    for part in parts:
        if not _SAFE_PART.match(part):
            raise ValueError(f"非法的字段路径: {field!r}")
    return "{" + ",".join(parts) + "}"


def _value_path(field: str) -> str:
    """``doc #> '{a,b}'`` —— 保留 JSON 类型。"""
    return f"(doc #> '{path_literal(field)}')"


def _text_path(field: str) -> str:
    """``doc #>> '{a,b}'`` —— 取文本。"""
    return f"(doc #>> '{path_literal(field)}')"


def _column_param_sql(column: str) -> str:
    """映射列写入占位符的 SQL：JSONB 列 ``::jsonb``，其余按列类型强转。

    psycopg3 把 Python bool/int/str 适配成对应 PG 类型；``::text`` /
    ``::timestamptz`` 这类赋值转换对 text 参数同样成立（ISO 字符串可解析），
    None 落 NULL。强转会在脏数据上直接报错——与 r3-flatten 回填补写用的
    是同一套 CAST 语义（该批数据已验证 0 错误）， fail-loud 优于静默不一致。
    """
    if column_type(column) == "JSONB":
        return "%s::jsonb"
    return f"%s::{column_type(column).lower()}"


def _column_value_to_doc(value: Any) -> Any:
    """读路径列值 → doc 值形状：datetime 序列化为 ISO 字符串、Decimal 归一回数字。

    doc JSONB 里日期以 ISO 字符串存储（写入时 ``to_json_text``），业务代码
    拿到的一直是字符串；列值覆盖 doc 键时必须保持同形状，否则 datetime
    对象会改变既有代码对 doc 字段类型的假设。同理 jsonb 数字解码出
    int/float，而 numeric/bigint 列解码出 Decimal——JSON 序列化与等值
    比较都要求保持 int/float 形状（``Decimal(5) == 5`` 虽为真，但
    ``json.dumps`` 不认 Decimal）。
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _column_sync_sql(source: str, key: str, column: str) -> str:
    """UPDATE 里的列同步表达式：基于新 doc 的键取值并强转到列类型。

    JSON null 必须转成 SQL NULL：``#>>`` 会把 JSON null 渲染成字符串
    ``'null'``，直接 ``::integer`` / ``::boolean`` / ``::timestamptz`` 会
    cast 报错，而 doc-only 时代写 JSON null 是**合法更新**——双写不能把
    合法写入变成故障。

    **jsonb 路径必须用 ``#>`` / ``#>>``（2026-10-16 真库复测定位的坑）**：
    本库（openGauss 3.2.0 A 模式）**没有 ``jsonb ->> text[]`` 运算符**，
    ``->`` / ``->>`` 右遇 ``'{a,b}'`` 字面量只匹配 **text 重载**，键名变成
    字面字符串 ``"{a,b}"`` → 恒为 NULL。常量即可复现：
    ``'{"{title}":"Y"}'::jsonb ->> '{title}'`` 得 ``'Y'``，而
    ``'{"title":"X"}'::jsonb ->> '{title}'`` 得 NULL；显式
    ``doc ->> ('{title}'::text[])`` 直接报 ``operator does not exist``。
    ``#>`` / ``#>>`` 只接受 text[]，无歧义，且缺失键返回 SQL NULL、
    JSON null 返回 JSON null：

    * 键缺失 → ``#>`` 得 SQL NULL → 比较为 unknown → 走 ELSE → ``#>>``
      为 NULL → cast 得 NULL（✓ 缺失即 NULL）；
    * JSON null → ``#>`` 得 JSON null → 比较为真 → THEN NULL（✓）；
    * 有值 → 走 ELSE cast（✓）。

    历史教训：列同步曾写成 ``->>'{key}'``，真库上**列被静默写 NULL**
    （doc 完好、``UPDATE 1`` 照常返回，极具迷惑性），一度被误诊为
    「SET 上下文函数调用返回 NULL」。凡jsonb路径表达式一律 ``#>`` / ``#>>``。
    """
    if column_type(column) == "JSONB":
        return f"{source} #> '{path_literal(key)}'"
    raw = f"{source} #>> '{path_literal(key)}'"
    return (
        f"(CASE WHEN ({source} #> '{path_literal(key)}') = 'null'::jsonb "
        f"THEN NULL ELSE ({raw})::{column_type(column).lower()} END)"
    )


def to_json_text(value: Any) -> str:
    """序列化为 JSON 文本，供 ``%s::jsonb`` 使用。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _numeric_literal(value: Any) -> str | None:
    """数值型字面量；非数值（含 bool）返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return repr(value)
    return None


def _dotted_set(target: dict[str, Any], field: str, value: Any) -> None:
    """按 ``a.b.c`` 语义写入嵌套 dict（``$set`` 的 Python 侧等价）。"""
    parts = _path_parts(field)
    cursor = target
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _dotted_get(target: Mapping[str, Any], field: str) -> Any:
    cursor: Any = target
    for part in _path_parts(field):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _jsonb_set_path(base: str, field: str, value_sql: str, *, create: bool = True) -> str:
    """生成「把 ``value_sql`` 写到 ``field`` 路径」的 JSONB 表达式（**深合并**）。

    PanWeiDB（openGauss）的 ``jsonb_set`` 与 PostgreSQL 有一处关键差异：
    **不会创建中间层对象**。即 ``jsonb_set('{"x":1}', '{a,b}', v, true)`` 在
    openGauss 下原样返回，而在 PG 下会得到 ``{"x":1,"a":{"b":v}}``。

    因此对 ``a.b.c`` 这类点号路径必须**逐层回卷**构造：

    1. 内层：``jsonb_set(COALESCE(base #> '{a,b}', '{}'), '{c}', v, true)``
    2. 回卷：``jsonb_set(COALESCE(base #> '{a}', '{}'), '{b}', <内层>, true)``
    3. 收口：``jsonb_set(base, '{a}', <上一层>, true)``

    这样既补上缺失的中间对象，又保留同级已有字段（真正的深合并语义，
    与 Mongo ``$set`` 一致）。
    """
    parts = _path_parts(field)
    if len(parts) == 1:
        return f"jsonb_set({base}, '{{{parts[0]}}}', {value_sql}, {'true' if create else 'false'})"
    for part in parts:
        if not _SAFE_PART.match(part):
            raise ValueError(f"非法的字段路径: {field!r}")

    inner_prefix = "{" + ",".join(parts[:-1]) + "}"
    expression = (
        f"jsonb_set(COALESCE({base} #> '{inner_prefix}', '{{}}'::jsonb), "
        f"'{{{parts[-1]}}}', {value_sql}, {'true' if create else 'false'})"
    )
    for depth in range(len(parts) - 2, -1, -1):
        key = parts[depth]
        if depth == 0:
            parent = base
        else:
            prefix = "{" + ",".join(parts[:depth]) + "}"
            parent = f"COALESCE({base} #> '{prefix}', '{{}}'::jsonb)"
        expression = f"jsonb_set({parent}, '{{{key}}}', {expression}, {'true' if create else 'false'})"
    return expression


def _unset_expression(expr: str, field: str) -> str:
    """生成「删除某路径」的 JSONB 表达式。

    PanWeiDB 的 ``sql_compatibility`` 固定为 ``A``（Oracle 模式），该模式下
    ``#-`` 运算符被禁用（``jsonb #- operator is supported only in PG-format
    database``）。因此改用「取出父节点 → ``-`` 删键 → ``jsonb_set`` 写回」的等价写法：

    * 顶层字段：``doc - 'key'``
    * 嵌套字段：``jsonb_set(doc, '{a,b}', COALESCE(doc #> '{a,b}', '{}') - 'c', false)``

    父节点缺失时 ``COALESCE`` 兜成空对象，配合 ``create_if_missing=false``
    保证整条语句是 no-op（与 Mongo 的 ``$unset`` 语义一致）。
    ``jsonb_typeof`` 判断是为了避免对数组误用 ``- text``。
    """
    parts = _path_parts(field)
    if len(parts) == 1:
        return f"({expr} - '{parts[0]}')"
    parent = "{" + ",".join(parts[:-1]) + "}"
    key = parts[-1]
    node = f"COALESCE({expr} #> '{parent}', '{{}}'::jsonb)"
    removed = f"CASE WHEN jsonb_typeof({node}) = 'object' THEN {node} - '{key}' ELSE {node} END"
    return f"jsonb_set({expr}, '{parent}', {removed}, false)"


# ── 过滤器编译 ───────────────────────────────────────────────────────
class _FilterCompiler:
    """把 Mongo 过滤条件编译成 ``(sql, params)``。

    取舍：等值 / ``$in`` 一律走 JSONB 比较（``doc #> path = %s::jsonb``），
    统一覆盖字符串、数字、布尔、null 与嵌套结构；范围比较在字面量为数值时
    走 ``numeric`` 转换，否则退化为文本比较。

    R3 扁平化（027 方案 §5.3）：``column_map`` 传入表的 ``{doc_key: column}``
    后，命中的顶层键改走真实列（按列类型比较，可命中列上的 btree 索引），
    未命中维持 doc JSONB 路径；``$size`` / ``$all`` / ``$type`` 只对 JSONB
    型映射列生效（直接用列名替代 ``doc #> path``），非 JSONB 列退回 doc 路径。
    """

    def __init__(self, column_map: Mapping[str, str] | None = None) -> None:
        self.params: list[Any] = []
        self._columns: dict[str, str] = dict(column_map or {})

    def _p(self, value: Any) -> str:
        self.params.append(value)
        return "%s"

    def _mapped(self, field: str) -> str | None:
        """字段命中 COLUMN_MAP 且是顶层键（无点号嵌套路径）时返回列名。"""
        if "." in field:
            return None
        return self._columns.get(field)

    def _accessor(self, field: str) -> tuple[str, str]:
        """返回 ``(value_sql, text_sql)``：JSONB 型映射列直接用列名，其余 doc 路径。"""
        col = self._mapped(field)
        if col is not None and column_type(col) == "JSONB":
            return f'"{col}"', f'"{col}"::text'
        return _value_path(field), _text_path(field)

    def _column_eq(self, column: str, value: Any) -> str:
        """映射列等值：JSONB 列走 jsonb 相等，其余按列类型比较。

        ``value is None`` 时走 ``IS NULL``：SQL 的 ``= NULL`` 恒不为真，且
        DDL 内联上下文（create_index 的 partialFilterExpression）会把 None
        变成字面量 ``'null'``，``'null'::timestamptz`` 直接 cast 失败。
        列缺失即 NULL，与 Mongo「{field: null} 匹配缺失」语义一致。
        """
        if value is None:
            return f'"{column}" IS NULL'
        if column_type(column) == "JSONB":
            return f'"{column}" = {self._p(to_json_text(value))}::jsonb'
        return f'"{column}" = {self._p(value)}::{column_type(column).lower()}'

    def compile(self, filt: Mapping[str, Any] | None) -> str:
        if not filt:
            return "TRUE"
        clauses: list[str] = []
        for key, value in filt.items():
            if key == "$or":
                clauses.append(self._group("OR", value))
            elif key == "$and":
                clauses.append(self._group("AND", value))
            elif key == "$nor":
                clauses.append(f"NOT ({self._group('OR', value)})")
            elif key.startswith("$"):
                raise PgCompatUnsupported(f"顶层算子 {key}")
            else:
                clauses.append(self._field(key, value))
        if not clauses:
            return "TRUE"
        return " AND ".join(f"({c})" for c in clauses)

    def _group(self, op: str, value: Any) -> str:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{op} 需要一个条件数组")
        parts = [self.compile(item) for item in value]
        if not parts:
            return "TRUE" if op == "AND" else "FALSE"
        return f" {op} ".join(f"({p})" for p in parts)

    def _field(self, field: str, value: Any) -> str:
        if isinstance(value, Mapping) and any(str(k).startswith("$") for k in value):
            return self._operators(field, value)
        col = self._mapped(field)
        if col is not None:
            return self._column_eq(col, value)
        return f"{_value_path(field)} = {self._p(to_json_text(value))}::jsonb"

    def _operators(self, field: str, spec: Mapping[str, Any]) -> str:
        # $options 是 $regex 的修饰符，不是独立算子，由 $regex 分支消费。
        clauses = [
            self._operator(field, op, operand, spec)
            for op, operand in spec.items()
            if op != "$options"
        ]
        return " AND ".join(f"({c})" for c in clauses)

    def _operator(self, field: str, op: str, operand: Any, spec: Mapping[str, Any]) -> str:
        value_path, text_path = self._accessor(field)
        col = self._mapped(field)

        if op == "$eq":
            if col is not None:
                return self._column_eq(col, operand)
            return f"{value_path} = {self._p(to_json_text(operand))}::jsonb"
        if op == "$ne":
            # Mongo 语义：字段缺失同样满足 $ne。
            if col is not None:
                if operand is None:
                    # {field: {$ne: null}} → 只匹配非空值（缺失=列 NULL，不匹配）。
                    return f'"{col}" IS NOT NULL'
                if column_type(col) == "JSONB":
                    return (
                        f'("{col}" IS NULL OR "{col}" <> '
                        f"{self._p(to_json_text(operand))}::jsonb)"
                    )
                return (
                    f'("{col}" IS NULL OR "{col}" <> '
                    f"{self._p(operand)}::{column_type(col).lower()})"
                )
            return f"({value_path} IS NULL OR {value_path} <> {self._p(to_json_text(operand))}::jsonb)"
        if op in {"$gt", "$gte", "$lt", "$lte"}:
            symbol = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
            if col is not None:
                typ = column_type(col)
                cast = "::numeric" if typ in {"INTEGER", "BIGINT"} else f"::{typ.lower()}"
                return f'"{col}" {symbol} {self._p(operand)}{cast}'
            num = _numeric_literal(operand)
            if num is not None:
                return (
                    f"(CASE WHEN jsonb_typeof({value_path}) = 'number' "
                    f"THEN ({text_path})::numeric END) {symbol} {num}"
                )
            return f"({text_path}) {symbol} {self._p(str(operand))}"
        if op in {"$in", "$nin"}:
            return self._in(field, operand, negate=(op == "$nin"))
        if op == "$exists":
            if col is not None:
                exists_sql = f'"{col}" IS NOT NULL'
            else:
                exists_sql = f"(doc #> '{path_literal(field)}') IS NOT NULL"
            return exists_sql if operand else f"NOT ({exists_sql})"
        if op == "$regex":
            pattern = operand.pattern if isinstance(operand, re.Pattern) else str(operand)
            options = str(spec.get("$options") or "")
            if isinstance(operand, re.Pattern):
                options += "".join(
                    flag for flag, char in ((re.IGNORECASE, "i"), (re.MULTILINE, "m"), (re.DOTALL, "s"))
                    if operand.flags & flag
                )
            # PCRE → openGauss ARE：\b/\B 在 PG 里是退格符而非词边界（静默不命中），
            # \w/\W 会因 UTF-8 locale 吸入非 ASCII。见 translate_regex_pattern 的文档字符串。
            pattern = translate_regex_pattern(pattern)
            operator = "~*" if "i" in options else "~"
            if col is not None:
                return f'("{col}"::text) {operator} {self._p(pattern)}'
            return f"({text_path}) {operator} {self._p(pattern)}"
        if op == "$size":
            return (
                f"(CASE WHEN jsonb_typeof({value_path}) = 'array' "
                f"THEN jsonb_array_length({value_path}) END) = {int(operand)}"
            )
        if op == "$all":
            items = list(operand)
            if not items:
                return "FALSE"
            parts = [f"{value_path} @> {self._p(to_json_text([item]))}::jsonb" for item in items]
            return " AND ".join(f"({p})" for p in parts)
        if op == "$not":
            inner = (
                self._operators(field, operand)
                if isinstance(operand, Mapping)
                else f"{value_path} = {self._p(to_json_text(operand))}::jsonb"
            )
            return f"NOT ({inner})"
        if op == "$elemMatch":
            raise PgCompatUnsupported("$elemMatch")
        if op == "$type":
            return self._type(field, operand)
        raise PgCompatUnsupported(f"过滤算子 {op}")

    def _in(self, field: str, operand: Any, *, negate: bool) -> str:
        if not isinstance(operand, (list, tuple, set)):
            raise ValueError("$in/$nin 需要一个数组")
        items = list(operand)
        if not items:
            return "TRUE" if negate else "FALSE"
        col = self._mapped(field)
        if col is not None:
            typ = column_type(col)
            if typ == "JSONB":
                rendered = ", ".join(f"{self._p(to_json_text(item))}::jsonb" for item in items)
            else:
                cast = "::numeric" if typ in {"INTEGER", "BIGINT"} else f"::{typ.lower()}"
                rendered = ", ".join(f"{self._p(item)}{cast}" for item in items)
            if negate:
                return f'("{col}" IS NULL OR "{col}" NOT IN ({rendered}))'
            return f'"{col}" IN ({rendered})'
        value_path = _value_path(field)
        rendered = ", ".join(f"{self._p(to_json_text(item))}::jsonb" for item in items)
        if negate:
            return f"({value_path} IS NULL OR {value_path} NOT IN ({rendered}))"
        return f"{value_path} IN ({rendered})"

    def _type(self, field: str, operand: Any) -> str:
        """Mongo ``$type`` 过滤：按 JSONB 类型匹配。

        常用类型名映射：

        - ``"null"`` / ``"missing"`` → 值为 null 或字段缺失
        - ``"string"`` / ``"int"`` / ``"long"`` / ``"double"`` / ``"bool"`` / ``"array"`` / ``"object"``
        """
        value_path = _value_path(field)
        jsonb_type = f"jsonb_typeof({value_path})"
        operand_str = str(operand)
        if operand_str in ("null", "missing"):
            # Mongo 语义：字段缺失等价于 null
            return f"({value_path} IS NULL OR {jsonb_type} = 'null')"
        if operand_str in ("int", "long", "double", "number"):
            return f"{jsonb_type} = 'number'"
        if operand_str in ("bool",):
            return f"{jsonb_type} = 'boolean'"
        if operand_str in ("array",):
            return f"{jsonb_type} = 'array'"
        if operand_str in ("object",):
            return f"{jsonb_type} = 'object'"
        # "string" 及其他：直接匹配 jsonb_typeof 返回值
        return f"{jsonb_type} = {self._p(operand_str)}"


# ── 更新编译 ─────────────────────────────────────────────────────────
class _UpdateCompiler:
    """把 Mongo 更新文档编译成一串「基于上一层 ``doc`` 计算新 ``doc``」的步骤。

    **为什么不编译成单个嵌套表达式**：PostgreSQL 的 ``UPDATE ... SET`` 不允许对
    同一列多次赋值，所以多个算子必须嵌套；而嵌套会让**占位符**随层级重复出现
    （同一个 ``%s`` 在文本里出现多次），psycopg 会报
    "query has N placeholders but M parameters"。

    改为步骤链后，每一步的表达式只引用**上一步的列名** ``doc``：

    .. code-block:: sql

        WITH s0 AS (SELECT id, doc FROM t WHERE <filter> LIMIT 1),
             s1 AS (SELECT id, jsonb_set(doc, '{age}', %s::jsonb, true) AS doc FROM s0),
             s2 AS (SELECT id, <step2> AS doc FROM s1)
        UPDATE t AS tgt SET doc = s2.doc, updated_at = now() FROM s2 WHERE tgt.id = s2.id

    占位符因此恰好出现一次，参数顺序 = 步骤顺序，与 SQL 文本顺序一致。

    逐路径 ``jsonb_set``（见 :func:`_jsonb_set_path`）保证 ``$set`` 的**深合并**
    语义与 Mongo 一致（``{"$set": {"a.b": 1}}`` 不会抹掉 ``a.c``）。
    """

    def __init__(self) -> None:
        self.params: list[Any] = []
        self.steps: list[str] = []

    def _p(self, value: Any) -> str:
        self.params.append(value)
        return "%s"

    def _step(self, expression: str) -> None:
        self.steps.append(expression)

    def compile(self, update: Mapping[str, Any], *, is_insert: bool = False) -> list[str]:
        if any(not str(k).startswith("$") for k in update):
            raise PgCompatUnsupported("整体替换式 update（应使用 replace_one）")
        for op, payload in update.items():
            self._apply(op, payload, is_insert=is_insert)
        return self.steps

    def _apply(self, op: str, payload: Any, *, is_insert: bool) -> None:
        if op in {"$set", "$setOnInsert"}:
            if op == "$setOnInsert" and not is_insert:
                return
            for field, value in payload.items():
                self._step(
                    _jsonb_set_path("doc", field, f"{self._p(to_json_text(value))}::jsonb")
                )
        elif op == "$unset":
            for field in payload:
                self._step(_unset_expression("doc", field))
        elif op == "$inc":
            for field, delta in payload.items():
                num = _numeric_literal(delta)
                if num is None:
                    raise ValueError("$inc 只支持数值增量")
                lit = path_literal(field)
                current = f"COALESCE((doc #>> '{lit}')::numeric, 0)"
                self._step(_jsonb_set_path("doc", field, f"to_jsonb({current} + {num})"))
        elif op in {"$max", "$min"}:
            fn = "GREATEST" if op == "$max" else "LEAST"
            for field, value in payload.items():
                num = _numeric_literal(value)
                if num is None:
                    continue
                lit = path_literal(field)
                current = f"COALESCE((doc #>> '{lit}')::numeric, {num})"
                self._step(_jsonb_set_path("doc", field, f"to_jsonb({fn}({current}, {num}))"))
        elif op == "$push":
            for field, value in payload.items():
                lit = path_literal(field)
                if isinstance(value, Mapping) and "$each" in value:
                    addition = f"{self._p(to_json_text(list(value['$each'])))}::jsonb"
                else:
                    # A 模式（sql_compatibility=A）下 jsonb_build_array 不可用，
                    # 直接用单元素数组字面量。
                    addition = f"{self._p(to_json_text([value]))}::jsonb"
                current = f"COALESCE(doc #> '{lit}', '[]'::jsonb)"
                self._step(_jsonb_set_path("doc", field, f"({current} || {addition})"))
        elif op == "$addToSet":
            for field, value in payload.items():
                lit = path_literal(field)
                items = list(value["$each"]) if isinstance(value, Mapping) and "$each" in value else [value]
                for item in items:
                    encoded = to_json_text(item)
                    # 该占位符在 SQL 文本里出现两次（判重 + 追加），因此必须入参两次，
                    # 否则 psycopg 会报 placeholder/parameter 数量不符。
                    probe = f"{self._p(encoded)}::jsonb"
                    append = f"{self._p(encoded)}::jsonb"
                    current = f"COALESCE(doc #> '{lit}', '[]'::jsonb)"
                    merged = (
                        f"CASE WHEN {current} @> {probe} THEN {current} "
                        f"ELSE {current} || {append} END"
                    )
                    self._step(_jsonb_set_path("doc", field, merged))
        elif op == "$currentDate":
            for field in payload:
                self._step(_jsonb_set_path("doc", field, "to_jsonb(now())"))
        elif op == "$pull":
            raise PgCompatUnsupported("更新算子 $pull")
        else:
            raise PgCompatUnsupported(f"更新算子 {op}")


def apply_update_to_document(document: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    """Python 侧应用更新算子（仅用于 upsert 的**插入**路径）。

    插入路径没有既有行可 ``jsonb_set``，直接在内存里合成新文档更简单可靠。
    """
    doc = json.loads(json.dumps(document, ensure_ascii=False, default=str))
    for op, payload in update.items():
        if op in {"$set", "$setOnInsert"}:
            for field, value in payload.items():
                _dotted_set(doc, field, value)
        elif op == "$unset":
            for field in payload:
                parts = _path_parts(field)
                cursor: Any = doc
                for part in parts[:-1]:
                    cursor = cursor.get(part) if isinstance(cursor, Mapping) else None
                    if not isinstance(cursor, dict):
                        break
                else:
                    if isinstance(cursor, dict):
                        cursor.pop(parts[-1], None)
        elif op == "$inc":
            for field, delta in payload.items():
                current = _dotted_get(doc, field)
                _dotted_set(doc, field, (current or 0) + delta)
        elif op in {"$max", "$min"}:
            fn = max if op == "$max" else min
            for field, value in payload.items():
                current = _dotted_get(doc, field)
                _dotted_set(doc, field, value if current is None else fn(current, value))
        elif op == "$push":
            for field, value in payload.items():
                items = list(value["$each"]) if isinstance(value, Mapping) and "$each" in value else [value]
                current = _dotted_get(doc, field) or []
                _dotted_set(doc, field, list(current) + items)
        elif op == "$addToSet":
            for field, value in payload.items():
                items = list(value["$each"]) if isinstance(value, Mapping) and "$each" in value else [value]
                current = list(_dotted_get(doc, field) or [])
                for item in items:
                    if item not in current:
                        current.append(item)
                _dotted_set(doc, field, current)
        elif op == "$currentDate":
            from datetime import datetime, timezone

            for field in payload:
                _dotted_set(doc, field, datetime.now(timezone.utc).isoformat())
        else:
            raise PgCompatUnsupported(f"更新算子 {op}")
    return doc


# ── 聚合管道编译 ─────────────────────────────────────────────────────

#: 无 `$sort` 时 `$first` / `$last` 的兜底排序。Mongo 在无 `$sort` 时顺序未定义，
#: 用主键兜底至少保证结果可复现。
_DEFAULT_ORDER = "id"

#: Mongo 比较运算符 → SQL
_COMPARE_OPS = {"$eq": "=", "$ne": "<>", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}
#: Mongo 算术运算符 → SQL（操作数先转 numeric）
_ARITH_OPS = {"$add": "+", "$subtract": "-", "$multiply": "*", "$divide": "/"}


class _AggregationCompiler:
    """把 Mongo 聚合管道编译成 ``WITH`` 链 + 最终 ``SELECT``。

    每个阶段产出一个 ``(id, doc)`` 形状的 CTE，与其它 API 保持一致，因此
    ``$sort`` / ``$group`` 里的字段路径都能统一写成 ``doc #> '{field}'``。

    只实现**代码里实际用到**的阶段与算子（全仓库扫描结果：``$match`` 25、
    ``$group`` 26、``$sort`` 5、``$project`` 1、``$limit`` 1、``$count`` 1；
    累加器 ``$sum``/``$avg``/``$min``/``$max``/``$push``/``$addToSet``/``$first``/``$last``）。
    其余显式抛 :class:`PgCompatUnsupported`。

    **A 模式约束**：``jsonb_build_object`` / ``jsonb_build_array`` 不可用，因此
    构造对象一律用 ``jsonb_set`` 链、构造数组用 ``'[]'::jsonb || elem``。

    **占位符纪律**：任何在 SQL 文本里出现多次的子表达式，都必须**重新构建**多次
    （而不是复用字符串），否则占位符数量会多于参数数量。``_num()`` 与
    ``_stage_group()`` 里的三处 key 表达式都遵循这条规则。

    **R3 后续优化（列路由）**：``column_map`` 传入表的 ``{doc_key: column}`` 后，
    ``$match`` / ``$sort`` **仅在阶段直接读基表时**（``self._src is None``，
    即管道第一个阶段）把命中的顶层键路由到真实列——彼时的输入就是基表，
    列真实存在。后续阶段的输入是 ``(id, doc)`` 形状的 CTE，没有那些列，
    因此一律维持 doc JSONB 路径。``$sort`` 存入 ``self._order`` 的供后续
    阶段复用的表达式同样保持 doc 路径（CTE 上才有效），只有本阶段自己
    的 ``ORDER BY`` 用路由形式。
    """

    def __init__(self, qualified: str, column_map: Mapping[str, str] | None = None) -> None:
        self._qualified = qualified
        self.params: list[Any] = []
        self._ctes: list[str] = []
        self._src: str | None = None
        self._counter = 0
        self._order: list[tuple[str, str]] = []
        self._columns: dict[str, str] = dict(column_map or {})

    # -- 基础设施 --------------------------------------------------------
    def _p(self, value: Any) -> str:
        self.params.append(value)
        return "%s"

    def _from(self) -> str:
        return self._src or self._qualified

    def _emit(self, body: str) -> None:
        self._counter += 1
        name = f"ag{self._counter}"
        self._ctes.append(f"{name} AS ({body})")
        self._src = name

    def _order_sql(self, *, reverse: bool = False) -> str:
        """当前 ``$sort`` 的 ORDER BY 子句；``reverse=True`` 时方向取反（供 ``$last``）。"""
        if not self._order:
            return _DEFAULT_ORDER
        parts = []
        for expr, direction in self._order:
            if reverse:
                direction = "ASC" if direction == "DESC" else "DESC"
            parts.append(f"{expr} {direction}")
        return ", ".join(parts)

    def _num(self, node: Any) -> str:
        """表达式 → 「numeric 或 NULL」（非数值取 NULL，供 sum/avg 忽略）。

        表达式在 SQL 文本里出现两次（``jsonb_typeof`` 与 ``#>>``），因此**构建两次**
        以保证占位符数量与参数数量一致。
        """
        first = self._expr_json(node)
        second = self._expr_json(node)
        return f"CASE WHEN jsonb_typeof({first}) = 'number' THEN ({second} #>> '{{}}')::numeric END"

    def _json_number(self, sql: str) -> str:
        """把 SQL 数值表达式包成 jsonb（``jsonb_set`` 的第三个参数必须是 jsonb）。"""
        return f"to_jsonb({sql})"

    # -- 入口 ------------------------------------------------------------
    def compile(self, pipeline: Any) -> str:
        if not isinstance(pipeline, (list, tuple)):
            raise PgCompatUnsupported("aggregate(pipeline) 需要一个管道列表")
        if not pipeline:
            raise PgCompatUnsupported("aggregate() 空管道（请改用 find()）")
        for stage in pipeline:
            if not isinstance(stage, Mapping) or len(stage) != 1:
                raise PgCompatUnsupported(f"非法的聚合阶段：{stage!r}")
            ((name, spec),) = stage.items()
            handler = getattr(self, f"_stage_{name.lstrip('$')}", None)
            if handler is None:
                raise PgCompatUnsupported(
                    f"聚合阶段 {name}。R2 只实现了代码实际用到的阶段；"
                    "若确需该阶段，请先扩展 app/core/pg_compat.py 并补充用例。"
                )
            handler(spec)
        order = f" ORDER BY {self._order_sql()}" if self._order else ""
        # 最终只取 doc 一列：`_fetch()` 读的是第 0 列（与 find 的 SELECT doc 一致）。
        return f"WITH {', '.join(self._ctes)} SELECT doc FROM {self._src}{order}"

    # -- 阶段 ------------------------------------------------------------
    def _stage_match(self, spec: Any) -> None:
        # 只有直接读基表时才能路由到真实列；CTE 输入只有 (id, doc)
        compiler = _FilterCompiler(self._columns if self._src is None else None)
        where = compiler.compile(spec)
        self.params.extend(compiler.params)
        self._emit(f"SELECT id, doc FROM {self._from()} WHERE {where}")

    def _stage_sort(self, spec: Any) -> None:
        if not isinstance(spec, Mapping):
            raise PgCompatUnsupported("$sort 需要字段映射")
        self._order = []
        order_parts: list[str] = []
        for field, direction in spec.items():
            field = str(field)
            arrow = "DESC" if int(direction) < 0 else "ASC"
            # 存入的是供后续阶段（$limit/$skip/$first/$last）复用的 doc 路径；
            # 本阶段直接读基表时才改用路由的列表达式（可用索引排序）。
            self._order.append((f"(doc #> '{path_literal(field)}')", arrow))
            order_parts.append(
                _order_expr(field, 1 if arrow == "ASC" else -1, self._columns)
                if self._src is None
                else f"(doc #> '{path_literal(field)}') {arrow}"
            )
        self._emit(f"SELECT id, doc FROM {self._from()} ORDER BY {', '.join(order_parts)}")

    def _stage_limit(self, spec: Any) -> None:
        self._emit(f"SELECT id, doc FROM {self._from()} ORDER BY {self._order_sql()} LIMIT {int(spec)}")

    def _stage_skip(self, spec: Any) -> None:
        self._emit(f"SELECT id, doc FROM {self._from()} ORDER BY {self._order_sql()} OFFSET {int(spec)}")

    def _stage_count(self, spec: Any) -> None:
        """``$count: "field"`` → 单个 ``{field: N}``。输入为空时 Mongo 返回空结果集。"""
        path = path_literal(str(spec))
        self._emit(
            f"SELECT '' AS id, "
            f"jsonb_set('{{}}'::jsonb, '{path}', to_jsonb(count(*)), true) AS doc "
            f"FROM {self._from()} HAVING count(*) > 0"
        )

    def _stage_group(self, spec: Any) -> None:
        """``$group`` 拆成两步 CTE：先聚合出普通列，再组装输出文档。

        不能一步写完，原因有三（都实测踩过）：

        1. 输出文档用 ``jsonb_set`` 链拼装，里面引用了 key 表达式；而 key 表达式
           同时出现在 ``GROUP BY`` 里 —— PG 9.2 判定不了「嵌套在 ``jsonb_set`` 里的
           表达式」与 ``GROUP BY`` 的是同一个，直接报
           ``column "..." must appear in the GROUP BY clause``。
        2. key 表达式若在 SQL 文本里出现两次而只构建一次，占位符就会多于参数。
        3. 累加器结果要先落成普通列，组装阶段才不再有聚合函数。

        第一步用 ``GROUP BY 1``（按输出列序号分组）避免重复写 key 表达式；
        jsonb 的 ``::text`` 是规范形式（键有序、空白归一），因此按文本分组与按
        jsonb 分组等价。
        """
        if not isinstance(spec, Mapping) or "_id" not in spec:
            raise PgCompatUnsupported("$group 必须包含 _id")
        key_sql = self._expr_json(spec["_id"])
        accumulators = [(field, self._accumulator(acc)) for field, acc in spec.items() if field != "_id"]

        columns = [f"({key_sql}) AS k", *(f"{sql} AS a{i}" for i, (_, sql) in enumerate(accumulators))]
        self._emit(f"SELECT {', '.join(columns)} FROM {self._from()} GROUP BY 1")

        doc = "jsonb_set('{}'::jsonb, '{_id}', k, true)"
        for index, (field, _) in enumerate(accumulators):
            doc = f"jsonb_set({doc}, '{path_literal(str(field))}', a{index}, true)"
        self._emit(f"SELECT k::text AS id, {doc} AS doc FROM {self._from()}")

    def _stage_project(self, spec: Any) -> None:
        if not isinstance(spec, Mapping):
            raise PgCompatUnsupported("$project 需要字段映射")
        percentiles = {
            field: value["$percentile"]
            for field, value in spec.items()
            if isinstance(value, Mapping) and "$percentile" in value
        }
        if percentiles:
            # `$percentile` 是累加器：`$project` 含它时整个阶段塌缩成一行。
            if len(percentiles) != len(spec):
                raise PgCompatUnsupported("$project 里混用 $percentile 与普通投影")
            doc = "jsonb_set('{}'::jsonb, '{_id}', 'null'::jsonb, true)"
            for field, value in percentiles.items():
                doc = f"jsonb_set({doc}, '{path_literal(str(field))}', {self._percentile(value)}, true)"
            self._emit(f"SELECT '' AS id, {doc} AS doc FROM {self._from()}")
            return

        # 普通投影：只支持「纯包含」或「纯排除」，与 Mongo 的规则一致。
        expressions = {f: v for f, v in spec.items() if isinstance(v, Mapping)}
        included = [f for f, v in spec.items() if not isinstance(v, Mapping) and v not in (0, False)]
        excluded = [f for f, v in spec.items() if not isinstance(v, Mapping) and v in (0, False)]
        if expressions:
            doc = "doc"
            for field, value in expressions.items():
                doc = f"jsonb_set({doc}, '{path_literal(str(field))}', {self._expr_json(value)}, true)"
            for field in excluded:
                doc = _unset_expression(doc, str(field))
            self._emit(f"SELECT id, {doc} AS doc FROM {self._from()}")
            return
        if included and excluded:
            raise PgCompatUnsupported("$project 不能同时包含与排除字段（_id 除外）")
        if excluded:
            doc = "doc"
            for field in excluded:
                doc = _unset_expression(doc, str(field))
            self._emit(f"SELECT id, {doc} AS doc FROM {self._from()}")
            return
        doc = "jsonb_set('{}'::jsonb, '{_id}', COALESCE(doc #> '{_id}', 'null'::jsonb), true)"
        for field in included:
            if field == "_id":
                continue
            path = path_literal(str(field))
            doc = f"jsonb_set({doc}, '{path}', COALESCE(doc #> '{path}', 'null'::jsonb), true)"
        self._emit(f"SELECT id, {doc} AS doc FROM {self._from()}")

    # -- 累加器 ----------------------------------------------------------
    def _accumulator(self, spec: Any) -> str:
        if not isinstance(spec, Mapping) or len(spec) != 1:
            raise PgCompatUnsupported(f"非法的累加器：{spec!r}")
        ((op, arg),) = spec.items()
        if op == "$sum":
            if isinstance(arg, (int, float)) and not isinstance(arg, bool):
                return self._json_number(f"count(*) * {arg}" if arg != 1 else "count(*)")
            return self._json_number(f"COALESCE(sum({self._num(arg)}), 0)")
        if op == "$avg":
            return self._json_number(f"avg({self._num(arg)})")
        if op in {"$min", "$max"}:
            # **不能用 min()/max() 聚合**：openGauss 的 min/max 作用在 jsonb 上按
            # **文本**比较（PostgreSQL 用 jsonb 自身的类型序），实测 max 在
            # 999 与 4343 之间取到 "999"（字典序）。而 jsonb 的**排序运算符**是正确的
            # （`ORDER BY jsonb` 对 10/9/2 给出 2/9/10），因此改用
            # `(array_agg(x ORDER BY x))[1]` 取真极值。
            # 表达式在 ORDER BY 与聚合里各出现一次，构建两次以对齐占位符。
            direction = "ASC" if op == "$min" else "DESC"
            first = self._expr_json(arg)
            second = self._expr_json(arg)
            return f"(array_agg({first} ORDER BY {second} {direction}))[1]"
        if op == "$push":
            return f"COALESCE(jsonb_agg({self._expr_json(arg)}), '[]'::jsonb)"
        if op == "$addToSet":
            return f"COALESCE(jsonb_agg(DISTINCT {self._expr_json(arg)}), '[]'::jsonb)"
        if op in {"$first", "$last"}:
            order = self._order_sql(reverse=op == "$last")
            return f"(array_agg({self._expr_json(arg)} ORDER BY {order}))[1]"
        if op == "$count":
            return self._json_number("count(*)")
        raise PgCompatUnsupported(f"聚合累加器 {op}")

    def _percentile(self, spec: Any) -> str:
        if not isinstance(spec, Mapping):
            raise PgCompatUnsupported("$percentile 需要配置对象")
        pcts = spec.get("p")
        if not isinstance(pcts, (list, tuple)) or not pcts:
            raise PgCompatUnsupported("$percentile.p 需要非空列表")
        value = self._num(spec.get("input"))
        parts = [f"percentile_cont({float(p)}) WITHIN GROUP (ORDER BY {value})" for p in pcts]
        # to_jsonb 对未知类型会报错，这里显式标注 numeric[]。
        return f"to_jsonb(ARRAY[{', '.join(parts)}]::numeric[])"

    # -- 表达式（返回 jsonb）---------------------------------------------
    def _expr_json(self, node: Any) -> str:
        if node is None:
            return "'null'::jsonb"
        if isinstance(node, bool):
            return "'true'::jsonb" if node else "'false'::jsonb"
        if isinstance(node, (int, float)):
            return f"'{node}'::jsonb"
        if isinstance(node, str):
            if node.startswith("$"):
                field = node[1:]
                if not field:
                    raise PgCompatUnsupported(f"非法的字段引用：{node!r}")
                return f"(doc #> '{path_literal(field)}')"
            # 字符串字面量必须**编码成 JSON**（带引号）再转 jsonb：
            # 直接把原文当 jsonb 会报 invalid input syntax for type json。
            return f"{self._p(to_json_text(node))}::jsonb"
        if isinstance(node, Mapping):
            if len(node) == 1 and str(next(iter(node))).startswith("$"):
                ((op, arg),) = node.items()
                return self._op_json(op, arg)
            doc = "'{}'::jsonb"
            for key, value in node.items():
                doc = f"jsonb_set({doc}, '{path_literal(str(key))}', {self._expr_json(value)}, true)"
            return doc
        if isinstance(node, (list, tuple)):
            if not node:
                return "'[]'::jsonb"
            return "(" + " || ".join(["'[]'::jsonb", *(self._expr_json(item) for item in node)]) + ")"
        raise PgCompatUnsupported(f"不支持的表达式：{node!r}")

    def _expr_bool(self, node: Any) -> str:
        if isinstance(node, Mapping) and len(node) == 1:
            op = str(next(iter(node)))
            if op in _COMPARE_OPS:
                return self._compare(op, node[op])
            if op in {"$and", "$or"}:
                joiner = " AND " if op == "$and" else " OR "
                return "(" + joiner.join(self._expr_bool(x) for x in node[op]) + ")"
            if op == "$not":
                args = node[op] if isinstance(node[op], (list, tuple)) else [node[op]]
                return "NOT (" + " AND ".join(self._expr_bool(x) for x in args) + ")"
        # 非布尔表达式（如 "$field"）：按其 jsonb 真值判断
        return f"({self._expr_json(node)} NOT IN ('null'::jsonb, 'false'::jsonb))"

    def _compare(self, op: str, arg: Any) -> str:
        if not isinstance(arg, (list, tuple)) or len(arg) != 2:
            raise PgCompatUnsupported(f"{op} 需要两个操作数")
        return f"({self._expr_json(arg[0])} {_COMPARE_OPS[op]} {self._expr_json(arg[1])})"

    def _op_json(self, op: str, arg: Any) -> str:
        if op in _COMPARE_OPS:
            return f"to_jsonb({self._compare(op, arg)})"
        if op == "$ifNull":
            if not isinstance(arg, (list, tuple)) or len(arg) < 2:
                raise PgCompatUnsupported("$ifNull 需要两个操作数")
            return f"COALESCE(NULLIF({self._expr_json(arg[0])}, 'null'::jsonb), {self._expr_json(arg[1])})"
        if op == "$cond":
            if isinstance(arg, Mapping):
                condition, then, otherwise = arg.get("if"), arg.get("then"), arg.get("else")
            elif isinstance(arg, (list, tuple)) and len(arg) == 3:
                condition, then, otherwise = arg
            else:
                raise PgCompatUnsupported("$cond 需要 {if,then,else} 或 [if,then,else]")
            return (
                f"CASE WHEN {self._expr_bool(condition)} "
                f"THEN {self._expr_json(then)} ELSE {self._expr_json(otherwise)} END"
            )
        if op in _ARITH_OPS:
            if not isinstance(arg, (list, tuple)) or len(arg) < 2:
                raise PgCompatUnsupported(f"{op} 需要至少两个操作数")
            result = f"({self._num(arg[0])} {_ARITH_OPS[op]} {self._num(arg[1])})"
            for extra in arg[2:]:
                result = f"({result} {_ARITH_OPS[op]} {self._num(extra)})"
            return f"to_jsonb({result})"
        if op in {"$max", "$min"}:
            if not isinstance(arg, (list, tuple)) or len(arg) < 2:
                raise PgCompatUnsupported(f"{op} 数组形式需要至少两个操作数")
            fn = "GREATEST" if op == "$max" else "LEAST"
            return f"{fn}(" + ", ".join(self._expr_json(x) for x in arg) + ")"
        if op == "$literal":
            return self._expr_json(arg)
        raise PgCompatUnsupported(f"聚合表达式 {op}")



class PgCursor:
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


class PgAggregationCursor:
    """``aggregate()`` 的返回物；``to_list()`` 与 ``for`` 迭代均可用。

    pymongo 的 ``aggregate()`` 是**同步**方法（返回游标）；这里保持同样的形状。
    管道在首次取数时才执行，因此构造游标不会产生查询。
    """

    def __init__(self, collection: "PgCollection", pipeline: Any) -> None:
        self._collection = collection
        self._pipeline = pipeline
        self._docs: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self._docs is None:
            self._docs = self._collection._run_aggregate(self._pipeline)
        return self._docs

    def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = self._load()
        if length is not None and length >= 0:
            return docs[:length]
        return docs

    def __iter__(self) -> Iterator[dict[str, Any]]:
        yield from self._load()


# ── 集合 ─────────────────────────────────────────────────────────────
#: 单集合建表模板。``IF NOT EXISTS`` + 惰性调用，等价于 Mongo 的「首次写入隐式建集合」。
TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {qualified} (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

#: 隐式建 schema。审计库用独立 schema 时它可能还不存在（业务 schema 由 DDL 预建），
#: 因此建表前先确保 schema 在位——否则会报 ``schema "..." does not exist``。
SCHEMA_DDL = 'CREATE SCHEMA IF NOT EXISTS {schema}'


class PgCollection:
    """单个集合（= 一张 ``<collection>`` 表）的门面。"""

    def __init__(self, pool: Any, name: str, schema: str) -> None:
        self._pool = pool
        self.name = name
        self._schema = schema
        self._qualified = f'"{schema}"."{name}"'
        # R3 扁平化：本表的 {doc_key: column}（❌ 表为空，行为与改造前一致）。
        self._columns = mapped_columns(self.name)
        # 首次操作时惰性建表；建过就置位，避免每次操作多一次往返。
        self._table_ready = False

    def _ensure_table(self) -> None:
        """确保底层表存在（幂等、可并发调用）。

        走独立连接而非 :meth:`_execute`，避免与 ``_execute`` 里的调用互相递归。
        """
        if self._table_ready:
            return
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_DDL.format(schema=f'"{self._schema}"'), [])
                cur.execute(TABLE_DDL.format(qualified=self._qualified), [])
        self._table_ready = True

    # -- 内部 ------------------------------------------------------------
    def _where(self, filt: Mapping[str, Any] | None) -> tuple[str, list[Any]]:
        compiler = _FilterCompiler(self._columns)
        return compiler.compile(filt), compiler.params

    def _column_entries(self) -> list[tuple[str, str]]:
        """本表的 ``[(doc_key, column)]``（1:1，顺序即 SELECT 列顺序）。"""
        return list(self._columns.items())

    @staticmethod
    def _decode(doc: Any) -> dict[str, Any]:
        if isinstance(doc, str):
            doc = json.loads(doc)
        return dict(doc or {})

    def _fetch(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        self._ensure_table()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [self._decode(row[0]) for row in rows]

    def _fetch_merged(
        self, sql: str, params: Sequence[Any], entries: Sequence[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        """读路径：doc JSONB + 映射列，列值非空即覆盖 doc 同名键。

        R3 方案 §5.2「读取时以列为准拼 doc」：SELECT 第 0 列是 doc，其后按
        ``entries`` 顺序是各映射列；列 NULL 不覆盖（doc 保持兜底值）。
        """
        self._ensure_table()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        merged: list[dict[str, Any]] = []
        for row in rows:
            doc = self._decode(row[0])
            if entries:
                for (key, _col), value in zip(entries, row[1:]):
                    if value is None:
                        continue
                    doc[key] = _column_value_to_doc(value)
            merged.append(doc)
        return merged

    @staticmethod
    def _columns_sql(entries: Sequence[tuple[str, str]]) -> str:
        """SELECT 里附加的映射列清单（非扁平表返回空串，SQL 与改造前一致）。"""
        return "".join(f', "{col}"' for _key, col in entries)

    def _scalar(self, sql: str, params: Sequence[Any]) -> Any:
        self._ensure_table()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        return row[0] if row else None

    def _execute(self, sql: str, params: Sequence[Any]) -> int:
        self._ensure_table()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount

    # -- 查询 ------------------------------------------------------------
    def find_one(
        self,
        filter: Mapping[str, Any] | None = None,
        projection: Mapping[str, Any] | None = None,
        sort: Any = None,
    ) -> dict[str, Any] | None:
        where, params = self._where(filter)
        entries = self._column_entries()
        sql = (
            f"SELECT doc{self._columns_sql(entries)} FROM {self._qualified} "
            f"WHERE {where}{_order_by(sort, self._columns)} LIMIT 1"
        )
        if entries:
            docs = self._fetch_merged(sql, params, entries)
        else:
            docs = self._fetch(sql, params)
        if not docs:
            return None
        return _apply_projection(docs[0], projection)

    def find(
        self,
        filter: Mapping[str, Any] | None = None,
        projection: Mapping[str, Any] | None = None,
    ) -> PgCursor:
        cursor = PgCursor(self, filter)
        cursor.projection = projection
        return cursor

    def _run_find(self, cursor: PgCursor) -> list[dict[str, Any]]:
        where, params = self._where(cursor._filter)
        entries = self._column_entries()
        sql = f"SELECT doc{self._columns_sql(entries)} FROM {self._qualified} WHERE {where}"
        if cursor._sort:
            sql += " ORDER BY " + ", ".join(
                _order_expr(field, direction, self._columns)
                for field, direction in cursor._sort
            )
        if cursor._limit:
            sql += f" LIMIT {int(cursor._limit)}"
        if cursor._skip:
            sql += f" OFFSET {int(cursor._skip)}"
        if entries:
            docs = self._fetch_merged(sql, params, entries)
        else:
            docs = self._fetch(sql, params)
        return [_apply_projection(doc, cursor.projection) for doc in docs]

    def count_documents(self, filter: Mapping[str, Any] | None = None) -> int:
        where, params = self._where(filter)
        total = self._scalar(f"SELECT count(*) FROM {self._qualified} WHERE {where}", params)
        return int(total or 0)

    def distinct(self, key: str, filter: Mapping[str, Any] | None = None) -> list[Any]:
        """去重取值。R3 后续优化：命中 COLUMN_MAP 的顶层键走真实列。

        列值解码类型与 doc JSONB 路径不同（numeric/bigint → Decimal、
        timestamptz → datetime），返回前统一过 :func:`_column_value_to_doc`
        归一化，保持 doc 路径时期的形状（数字 int/float、日期 ISO 字符串）。
        """
        where, params = self._where(filter)
        col = self._columns.get(key) if "." not in key else None
        target = f'"{col}"' if col else f"doc #> '{path_literal(key)}'"
        sql = (
            f"SELECT DISTINCT {target} AS v "
            f"FROM {self._qualified} WHERE {where}"
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_column_value_to_doc(row[0]) for row in rows if row[0] is not None]

    # -- 写入 ------------------------------------------------------------
    def insert_one(self, document: Mapping[str, Any]) -> InsertOneResult:
        doc = dict(document)
        doc_id = doc.get("_id")
        if doc_id is None:
            doc_id = uuid.uuid4().hex
            doc["_id"] = doc_id
        tenant_id = doc.get("tenant_id")
        entries = self._column_entries()
        if entries:
            # R3 双写：doc 键同步落映射列（同一 INSERT，原子）。
            cols_sql = "".join(f', "{col}"' for _key, col in entries)
            values_sql = "".join(f", {_column_param_sql(col)}" for _key, col in entries)
            sql = (
                f"INSERT INTO {self._qualified} (id, tenant_id, doc{cols_sql}) "
                f"VALUES (%s, %s, %s::jsonb{values_sql}) ON CONFLICT (id) DO NOTHING"
            )
            params: list[Any] = [
                str(doc_id), None if tenant_id is None else str(tenant_id), to_json_text(doc)
            ]
            for key, col in entries:
                value = doc.get(key)
                # JSONB 列的 None 也落 SQL NULL（与 _update 的 CASE 防护一致），
                # 避免 insert 写进 jsonb 'null' 而 update 写 SQL NULL 的两套语义。
                params.append(
                    to_json_text(value)
                    if column_type(col) == "JSONB" and value is not None
                    else value
                )
        else:
            sql = (
                f"INSERT INTO {self._qualified} (id, tenant_id, doc) "
                f"VALUES (%s, %s, %s::jsonb) ON CONFLICT (id) DO NOTHING"
            )
            params = [
                str(doc_id), None if tenant_id is None else str(tenant_id), to_json_text(doc)
            ]
        self._execute(sql, params)
        return InsertOneResult(doc_id)

    def insert_many(
        self,
        documents: Iterable[Mapping[str, Any]],
        ordered: bool = True,
    ) -> InsertManyResult:
        ids: list[Any] = []
        for document in documents:
            result = self.insert_one(document)
            ids.append(result.inserted_id)
        return InsertManyResult(ids)

    def replace_one(
        self,
        filter: Mapping[str, Any],
        replacement: Mapping[str, Any],
        upsert: bool = False,
    ) -> UpdateResult:
        where, params = self._where(filter)
        existing = self._scalar(f"SELECT id FROM {self._qualified} WHERE {where} LIMIT 1", params)
        doc = dict(replacement)
        if existing is None:
            if not upsert:
                return UpdateResult(0, 0)
            doc.setdefault("_id", uuid.uuid4().hex)
            result = self.insert_one(doc)
            return UpdateResult(0, 0, upserted_id=result.inserted_id)
        doc["_id"] = doc.get("_id", existing)
        tenant_id = doc.get("tenant_id")
        assignments = ["doc = %s::jsonb", "tenant_id = %s", "updated_at = now()"]
        params: list[Any] = [to_json_text(doc), None if tenant_id is None else str(tenant_id)]
        # R3 双写：整份替换时同步刷新映射列。
        for key, col in self._column_entries():
            assignments.append(f'"{col}" = {_column_param_sql(col)}')
            value = doc.get(key)
            params.append(to_json_text(value) if column_type(col) == "JSONB" else value)
        params.append(existing)
        self._execute(
            f"UPDATE {self._qualified} SET {', '.join(assignments)} WHERE id = %s",
            params,
        )
        return UpdateResult(1, 1)

    def update_one(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        upsert: bool = False,
    ) -> UpdateResult:
        return self._update(filter, update, upsert=upsert, many=False)

    def update_many(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        upsert: bool = False,
    ) -> UpdateResult:
        return self._update(filter, update, upsert=upsert, many=True)

    def _update(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool,
        many: bool,
    ) -> UpdateResult:
        where, params = self._where(filter)
        matched = int(self._scalar(
            f"SELECT count(*) FROM {self._qualified} WHERE {where}", params
        ) or 0)

        if matched == 0:
            if not upsert:
                return UpdateResult(0, 0)
            seed: dict[str, Any] = {
                field: value
                for field, value in (filter or {}).items()
                if not str(field).startswith("$") and not isinstance(value, Mapping)
            }
            new_doc = apply_update_to_document(seed, update)
            new_doc.setdefault("_id", uuid.uuid4().hex)
            self.insert_one(new_doc)
            # pymongo 语义：upsert 创建新文档时 matched_count=0（无既有行被匹配），
            # upserted_count 由 bulk_write 通过 upserted_id 统计。
            return UpdateResult(0, 0, upserted_id=new_doc["_id"])

        compiler = _UpdateCompiler()
        steps = compiler.compile(update, is_insert=False)
        if not steps:
            return UpdateResult(matched, 0)

        # 步骤链：s0 圈定目标行（update_one 只取 1 行），s1..sN 逐步计算新 doc，
        # 最后 UPDATE 按 id 回写。占位符顺序 = s0 的过滤参数 + 各步骤参数。
        ctes = [
            f"s0 AS (SELECT id, doc FROM {self._qualified} WHERE {where}"
            + ("" if many else " LIMIT 1")
            + ")"
        ]
        for index, step in enumerate(steps, start=1):
            ctes.append(f"s{index} AS (SELECT id, {step} AS doc FROM s{index - 1})")
        last = f"s{len(steps)}"
        # R3 双写：最终 UPDATE 基于新 doc（{last}.doc）同步刷新映射列，
        # 与 SET doc 同一语句，保持原子性；JSON null → SQL NULL（见 _column_sync_sql）。
        assignments = [f"doc = {last}.doc", "updated_at = now()"]
        for key, col in self._column_entries():
            assignments.append(f'"{col}" = {_column_sync_sql(last + ".doc", key, col)}')
        target = (
            f"WITH {', '.join(ctes)} "
            f"UPDATE {self._qualified} AS tgt SET {', '.join(assignments)} "
            f"FROM {last} WHERE tgt.id = {last}.id"
        )
        self._execute(target, [*params, *compiler.params])
        # pymongo 语义：有更新步骤时 modified == matched（每行都实际变化）。
        return UpdateResult(matched, matched)

    def find_one_and_update(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        upsert: bool = False,
        return_document: Any = None,
        sort: Any = None,
    ) -> dict[str, Any] | None:
        before = self.find_one(filter, sort=sort)
        result = self.update_one(filter, update, upsert=upsert)
        want_after = _return_after(return_document)
        if want_after:
            if before is None and result.upserted_id is not None:
                return self.find_one({"_id": result.upserted_id})
            return self.find_one(filter, sort=sort)
        return before

    def delete_one(self, filter: Mapping[str, Any]) -> DeleteResult:
        where, params = self._where(filter)
        deleted = self._execute(
            f"DELETE FROM {self._qualified} WHERE id IN "
            f"(SELECT id FROM {self._qualified} WHERE {where} LIMIT 1)",
            params,
        )
        return DeleteResult(max(deleted, 0))

    def delete_many(self, filter: Mapping[str, Any]) -> DeleteResult:
        where, params = self._where(filter)
        deleted = self._execute(f"DELETE FROM {self._qualified} WHERE {where}", params)
        return DeleteResult(max(deleted, 0))

    # -- 索引 ------------------------------------------------------------
    def create_index(
        self,
        keys: Any,
        unique: bool = False,
        name: str | None = None,
        *,
        sparse: bool = False,
        partialFilterExpression: Mapping[str, Any] | None = None,
        expireAfterSeconds: int | None = None,
        **_: Any,
    ) -> str:
        """Mongo 索引声明 → PG 表达式索引（含部分/稀疏唯一索引）。

        单字段 → ``(doc #> '{field}')``；复合 → 多列表达式索引。
        R3 扁平化：命中 COLUMN_MAP 的顶层字段直接在真实列上建 btree。
        方向（``-1``）被忽略：PG 的 btree 可双向扫描，方向不改变可用性。

        **部分索引**（``partialFilterExpression``）→ ``CREATE ... WHERE <过滤>``。
        过滤器用的就是 `find()` 的语法，因此直接复用 :class:`_FilterCompiler`。
        实测 openGauss 支持部分唯一索引，且唯一约束只作用于满足 WHERE 的行 ——
        与 Mongo 的 ``partialFilterExpression`` 语义一致。

        **稀疏索引**（``sparse=True``）→ 对每个被索引字段补
        ``WHERE (doc #> '{field}') IS NOT NULL``，等价于「只索引含该字段的文档」。
        若同时给了 ``partialFilterExpression``，以**两者合取**为准（Mongo 也要求
        sparse 与 partialFilterExpression 不冲突）。

        text / geo 仍未支持（调用即抛 :class:`PgCompatUnsupported`）；TTL
        （``expireAfterSeconds``）在 openGauss 无原生等价物，改为**登记声明**，
        由 :func:`purge_expired_ttl` 在应用层定期清理。
        """
        if isinstance(keys, str):
            fields = [keys]
        elif isinstance(keys, Mapping):
            fields = [str(item) for item in keys]
        else:
            fields = [str(item[0]) for item in keys]
        if not fields:
            raise ValueError("create_index 需要至少一个字段")
        index_name = name or f"{self.name}_{'_'.join(f.replace('.', '_') for f in fields)}_idx"
        if expireAfterSeconds is not None:
            # openGauss 无原生 TTL 索引：登记声明，改由 ``purge_expired_ttl`` 应用层清理；
            # 仍建普通 btree 索引以加速过期字段的过滤。
            _TTL_REGISTRY[self.name] = (fields[0], int(expireAfterSeconds))
        sql = _build_create_index_sql(
            self._qualified,
            index_name,
            fields,
            unique=unique,
            sparse=sparse,
            partialFilterExpression=partialFilterExpression,
            column_map=self._columns,
        )
        self._execute(sql, [])
        return index_name

    def create_indexes(self, indexes: Iterable[Any]) -> list[str]:
        names: list[str] = []
        for spec in indexes:
            keys = getattr(spec, "document", None) or getattr(spec, "_keys", None) or spec
            names.append(self.create_index(
                keys,
                unique=bool(getattr(spec, "unique", False)),
                sparse=bool(getattr(spec, "sparse", False)),
                partialFilterExpression=getattr(spec, "partialFilterExpression", None),
            ))
        return names

    # -- 聚合 ------------------------------------------------------------
    def aggregate(self, pipeline: Any, **_: Any) -> PgAggregationCursor:
        """聚合管道。返回游标（**同步**构造），与 motor 一致。

        支持的阶段与算子见 :class:`_AggregationCompiler`；未覆盖的显式抛
        :class:`PgCompatUnsupported`。
        """
        return PgAggregationCursor(self, pipeline)

    def _run_aggregate(self, pipeline: Any) -> list[dict[str, Any]]:
        compiler = _AggregationCompiler(self._qualified, self._columns)
        sql = compiler.compile(pipeline)
        return self._fetch(sql, compiler.params)

    # -- 批量写 ----------------------------------------------------------
    def bulk_write(self, requests: Any, ordered: bool = True, **_: Any) -> BulkWriteResult:
        """逐条执行 pymongo 的批量写请求。

        ``ordered=True`` 时遇错即停（与 pymongo 一致）；这里逐条执行，任一条抛错
        都会向上传播，已执行的部分不会回滚（与 pymongo 的 ordered 语义一致：
        前面成功的操作保留）。请求对象按**类名**识别，避免依赖 pymongo 私有属性
        的导入路径（``InsertOne`` / ``UpdateOne`` / ``UpdateMany`` / ``ReplaceOne`` /
        ``DeleteOne`` / ``DeleteMany``）。
        """
        inserted = matched = modified = deleted = 0
        upserted_ids: dict[Any, Any] = {}
        for index, request in enumerate(requests or ()):
            kind = type(request).__name__
            if kind == "InsertOne":
                self.insert_one(getattr(request, "_doc"))
                inserted += 1
            elif kind in {"UpdateOne", "UpdateMany"}:
                # pymongo 把更新文档存在 `_doc`（不是 `_update`），实测确认。
                upsert = bool(getattr(request, "_upsert", False))
                result = (
                    self.update_one(getattr(request, "_filter"), getattr(request, "_doc"), upsert=upsert)
                    if kind == "UpdateOne"
                    else self.update_many(getattr(request, "_filter"), getattr(request, "_doc"), upsert=upsert)
                )
                matched += result.matched_count
                modified += result.modified_count
                if result.upserted_id is not None:
                    upserted_ids[index] = result.upserted_id
            elif kind == "ReplaceOne":
                result = self.replace_one(
                    getattr(request, "_filter"), getattr(request, "_doc"),
                    upsert=bool(getattr(request, "_upsert", False)),
                )
                matched += result.matched_count
                modified += result.modified_count
                if result.upserted_id is not None:
                    upserted_ids[index] = result.upserted_id
            elif kind == "DeleteOne":
                deleted += (self.delete_one(getattr(request, "_filter"))).deleted_count
            elif kind == "DeleteMany":
                deleted += (self.delete_many(getattr(request, "_filter"))).deleted_count
            else:
                raise PgCompatUnsupported(
                    f"bulk_write 请求类型 {kind}（支持 InsertOne / UpdateOne / UpdateMany / "
                    "ReplaceOne / DeleteOne / DeleteMany）"
                )
        return BulkWriteResult(
            inserted_count=inserted,
            matched_count=matched,
            modified_count=modified,
            deleted_count=deleted,
            upserted_ids=upserted_ids,
        )

    def list_indexes(self) -> AsyncIterator[dict[str, Any]]:
        """列出当前集合（表）上的索引，返回 Mongo 形状的字典迭代器。

        通过 ``pg_indexes`` 视图读取 PG 索引元数据，映射到 Mongo 的
        ``{name, key, unique}`` 形状。未匹配 PG 的索引键被忽略；方向（``-1``）
        被丢弃（btree 可双向扫描）。
        """
        sql = (
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = %s AND tablename = %s"
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [self._schema, self.name])
                rows = cur.fetchall()
        for indexname, indexdef in rows:
            key: dict[str, int] = {}
            paren_start = indexdef.find("(")
            paren_end = indexdef.rfind(")")
            if paren_start != -1 and paren_end != -1:
                cols = [c.strip() for c in indexdef[paren_start + 1 : paren_end].split(",")]
                for col in cols:
                    m = re.search(r"#>\s*'(\{[^}]*\})'", col)
                    if m:
                        field = m.group(1).strip("{}")
                    else:
                        field = col.strip('"')
                    if field and field not in key:
                        key[field] = 1
            is_unique = "UNIQUE" in indexdef.split("(")[0]
            yield {
                "name": indexname,
                "key": key,
                "unique": is_unique,
            }


def _return_after(return_document: Any) -> bool:
    """判断 ``return_document`` 是否表示「返回更新后的文档」。

    兼容 ``ReturnDocument.AFTER``（枚举，``name == 'AFTER'``）与
    ``True``/``"after"`` 等写法。
    """
    if return_document is None:
        return False
    if isinstance(return_document, bool):
        return return_document
    name = getattr(return_document, "name", None)
    if name:
        return str(name).upper() == "AFTER"
    return str(return_document).strip().upper() in {"AFTER", "TRUE", "1"}


def _order_expr(
    field: str, order: int, columns: Mapping[str, str] | None = None
) -> str:
    """单个排序键的 SQL 表达式：COLUMN_MAP 命中的顶层键走真实列，其余 doc 路径。

    R3 后续优化：映射列是强类型（timestamptz 按时间、numeric 按数值、
    text 按字典序），既能命中列上的 btree 索引避免全表排序，也比 jsonb
    的通用序更接近 Mongo 的 BSON 排序语义。未命中（含 ``a.b`` 嵌套路径，
    扁平化只覆盖顶层键）维持 ``doc #> '{a,b}'``。非扁平表 ``columns``
    为空，输出与改造前逐字节一致。

    NULL 排序沿用 openGauss 默认（ASC 时 NULL 在后、DESC 在前），与改造前
    doc 路径对**缺失键**（``#>`` 得 SQL NULL）的行为一致；显式写 JSON null
    的旧行经双写/回填后同列为 SQL NULL，排序位置统一。
    """
    direction = "ASC" if order >= 0 else "DESC"
    col = columns.get(field) if columns and "." not in field else None
    target = f'"{col}"' if col else f"doc #> '{path_literal(field)}'"
    return f"{target} {direction}"


def _order_by(sort: Any, columns: Mapping[str, str] | None = None) -> str:
    if not sort:
        return ""
    if isinstance(sort, str):
        pairs: list[tuple[str, int]] = [(sort, 1)]
    elif isinstance(sort, Mapping):
        pairs = [(str(field), int(order)) for field, order in sort.items()]
    else:
        pairs = [(str(field), int(order)) for field, order in sort]
    rendered = ", ".join(_order_expr(field, order, columns) for field, order in pairs)
    return f" ORDER BY {rendered}" if rendered else ""


def _apply_projection(doc: dict[str, Any], projection: Mapping[str, Any] | None) -> dict[str, Any]:
    """在 Python 侧裁剪投影（R1 简化实现；R2 可下推为 SQL ``jsonb`` 构造）。"""
    if not projection:
        return doc
    includes = [key for key, flag in projection.items() if flag and key != "_id"]
    if includes:
        out = {key: value for key, value in doc.items() if key in includes}
        if projection.get("_id", 1):
            out.setdefault("_id", doc.get("_id"))
        return out
    excludes = [key for key, flag in projection.items() if not flag]
    if excludes:
        return {key: value for key, value in doc.items() if key not in excludes}
    return doc


class PgDatabase:
    """``get_db()`` 在 PanWeiDB 模式下的返回值；形状对齐 motor 的 Database。"""

    def __init__(self, pool: Any, schema: str) -> None:
        self._pool = pool
        self._schema = schema
        self._cache: dict[str, PgCollection] = {}

    def __getitem__(self, name: str) -> PgCollection:
        if name not in self._cache:
            self._cache[name] = PgCollection(self._pool, name, self._schema)
        return self._cache[name]

    def __getattr__(self, name: str) -> PgCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def list_collection_names(self) -> list[str]:
        sql = (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'"
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [self._schema])
                rows = cur.fetchall()
        return [row[0] for row in rows]

    def command(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        """``db.command("ping")`` 兼容。"""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return {"ok": 1}
