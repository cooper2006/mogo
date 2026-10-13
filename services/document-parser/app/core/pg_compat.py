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
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Iterable, Iterator, Mapping, Sequence

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


# ── 路径与字面量工具（纯函数，便于单测）──────────────────────────────
_SAFE_PART = re.compile(r"^[A-Za-z0-9_]+$")


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
    """

    def __init__(self) -> None:
        self.params: list[Any] = []

    def _p(self, value: Any) -> str:
        self.params.append(value)
        return "%s"

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
        value_path = _value_path(field)
        text_path = _text_path(field)

        if op == "$eq":
            return f"{value_path} = {self._p(to_json_text(operand))}::jsonb"
        if op == "$ne":
            # Mongo 语义：字段缺失同样满足 $ne。
            return f"({value_path} IS NULL OR {value_path} <> {self._p(to_json_text(operand))}::jsonb)"
        if op in {"$gt", "$gte", "$lt", "$lte"}:
            symbol = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
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
            operator = "~*" if "i" in options else "~"
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
        raise PgCompatUnsupported(f"过滤算子 {op}")

    def _in(self, field: str, operand: Any, *, negate: bool) -> str:
        if not isinstance(operand, (list, tuple, set)):
            raise ValueError("$in/$nin 需要一个数组")
        items = list(operand)
        value_path = _value_path(field)
        if not items:
            return "TRUE" if negate else "FALSE"
        rendered = ", ".join(f"{self._p(to_json_text(item))}::jsonb" for item in items)
        if negate:
            return f"({value_path} IS NULL OR {value_path} NOT IN ({rendered}))"
        return f"{value_path} IN ({rendered})"


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


# ── 游标 ─────────────────────────────────────────────────────────────
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


class PgCollection:
    """单个集合（= 一张 ``<collection>`` 表）的门面。"""

    def __init__(self, pool: Any, name: str, schema: str) -> None:
        self._pool = pool
        self.name = name
        self._schema = schema
        self._qualified = f'"{schema}"."{name}"'
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
                cur.execute(TABLE_DDL.format(qualified=self._qualified), [])
        self._table_ready = True

    # -- 内部 ------------------------------------------------------------
    def _where(self, filt: Mapping[str, Any] | None) -> tuple[str, list[Any]]:
        compiler = _FilterCompiler()
        return compiler.compile(filt), compiler.params

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
        sql = f"SELECT doc FROM {self._qualified} WHERE {where}{_order_by(sort)} LIMIT 1"
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
        sql = f"SELECT doc FROM {self._qualified} WHERE {where}"
        if cursor._sort:
            sql += " ORDER BY " + ", ".join(
                f"doc #> '{path_literal(field)}' {'ASC' if direction >= 0 else 'DESC'}"
                for field, direction in cursor._sort
            )
        if cursor._limit:
            sql += f" LIMIT {int(cursor._limit)}"
        if cursor._skip:
            sql += f" OFFSET {int(cursor._skip)}"
        docs = self._fetch(sql, params)
        return [_apply_projection(doc, cursor.projection) for doc in docs]

    def count_documents(self, filter: Mapping[str, Any] | None = None) -> int:
        where, params = self._where(filter)
        total = self._scalar(f"SELECT count(*) FROM {self._qualified} WHERE {where}", params)
        return int(total or 0)

    def distinct(self, key: str, filter: Mapping[str, Any] | None = None) -> list[Any]:
        where, params = self._where(filter)
        sql = (
            f"SELECT DISTINCT doc #> '{path_literal(key)}' AS v "
            f"FROM {self._qualified} WHERE {where}"
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [row[0] for row in rows if row[0] is not None]

    # -- 写入 ------------------------------------------------------------
    def insert_one(self, document: Mapping[str, Any]) -> InsertOneResult:
        doc = dict(document)
        doc_id = doc.get("_id")
        if doc_id is None:
            doc_id = uuid.uuid4().hex
            doc["_id"] = doc_id
        tenant_id = doc.get("tenant_id")
        sql = (
            f"INSERT INTO {self._qualified} (id, tenant_id, doc) "
            f"VALUES (%s, %s, %s::jsonb) ON CONFLICT (id) DO NOTHING"
        )
        self._execute(
            sql,
            [str(doc_id), None if tenant_id is None else str(tenant_id), to_json_text(doc)],
        )
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
        self._execute(
            f"UPDATE {self._qualified} SET doc = %s::jsonb, tenant_id = %s, updated_at = now() "
            f"WHERE id = %s",
            [to_json_text(doc), None if tenant_id is None else str(tenant_id), existing],
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
        target = (
            f"WITH {', '.join(ctes)} "
            f"UPDATE {self._qualified} AS tgt SET doc = {last}.doc, updated_at = now() "
            f"FROM {last} WHERE tgt.id = {last}.id"
        )
        modified = self._execute(target, [*params, *compiler.params])
        return UpdateResult(matched, max(modified, 0))

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
        **_: Any,
    ) -> str:
        """Mongo 索引声明 → PG 表达式索引。

        单字段 → ``(doc #> '{field}')``；复合 → 多列表达式索引。
        方向（``-1``）被忽略：PG 的 btree 可双向扫描，方向不改变可用性。
        text / geo / TTL / 部分索引需在 R2 单独处理。
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
        expressions = ", ".join(f"(doc #> '{path_literal(field)}')" for field in fields)
        unique_sql = "UNIQUE " if unique else ""
        self._execute(
            f"CREATE {unique_sql}INDEX IF NOT EXISTS \"{index_name}\" "
            f"ON {self._qualified} ({expressions})",
            [],
        )
        return index_name

    def create_indexes(self, indexes: Iterable[Any]) -> list[str]:
        names: list[str] = []
        for spec in indexes:
            keys = getattr(spec, "document", None) or getattr(spec, "_keys", None) or spec
            names.append(self.create_index(keys, unique=bool(getattr(spec, "unique", False))))
        return names

    # -- 明确未覆盖 -------------------------------------------------------
    def aggregate(self, pipeline: Any, **_: Any) -> Any:
        raise PgCompatUnsupported("aggregate 聚合管道")

    def bulk_write(self, requests: Any, **_: Any) -> Any:
        raise PgCompatUnsupported("bulk_write")


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


def _order_by(sort: Any) -> str:
    if not sort:
        return ""
    if isinstance(sort, str):
        pairs: list[tuple[str, int]] = [(sort, 1)]
    elif isinstance(sort, Mapping):
        pairs = [(str(field), int(order)) for field, order in sort.items()]
    else:
        pairs = [(str(field), int(order)) for field, order in sort]
    rendered = ", ".join(
        f"doc #> '{path_literal(field)}' {'ASC' if order >= 0 else 'DESC'}"
        for field, order in pairs
    )
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
