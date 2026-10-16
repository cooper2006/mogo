"""``app.core.pg_compat`` 的纯逻辑单测（不需要数据库）。

覆盖两层：

1. **翻译正确性**：Mongo 过滤/更新算子 → SQL/JSONB 表达式。
2. **不变量**：生成的 SQL 里 ``%s`` 占位符数量必须等于参数数量。
   这个不变量是 R1 期间真实踩过两次的缺陷类别（嵌套表达式重复占位符、
   ``$addToSet`` 复用占位符），因此固化成断言。

真实 PanWeiDB 上的端到端验证另行执行（见
``docs/mongo-to-panweidb-migration-plan.md`` 第 7 节），不在本文件的范围内。
"""

from __future__ import annotations

import re

import pytest

from app.core.pg_compat import (
    PgCompatUnsupported,
    _FilterCompiler,
    _UpdateCompiler,
    _build_create_index_sql,
    apply_update_to_document,
    path_literal,
    translate_regex_pattern,
)

PLACEHOLDER = re.compile(r"%s")


def _compile_filter(spec):
    compiler = _FilterCompiler()
    sql = compiler.compile(spec)
    assert len(PLACEHOLDER.findall(sql)) == len(compiler.params), (
        f"占位符/参数数量不符: {sql!r} vs {compiler.params!r}"
    )
    return sql, compiler.params


def _compile_update(spec, *, is_insert=False):
    compiler = _UpdateCompiler()
    steps = compiler.compile(spec, is_insert=is_insert)
    joined = " ".join(steps)
    assert len(PLACEHOLDER.findall(joined)) == len(compiler.params), (
        f"占位符/参数数量不符: {joined!r} vs {compiler.params!r}"
    )
    return steps, compiler.params


# ── 路径字面量 ────────────────────────────────────────────────────────
def test_path_literal_converts_dots_to_pg_path():
    assert path_literal("a") == "{a}"
    assert path_literal("a.b.c") == "{a,b,c}"


def test_path_literal_rejects_injection_attempt():
    with pytest.raises(ValueError):
        path_literal("a'; drop table x; --")


# ── 过滤条件 ──────────────────────────────────────────────────────────
def test_empty_filter_is_true():
    assert _compile_filter(None)[0] == "TRUE"
    assert _compile_filter({})[0] == "TRUE"


def test_equality_uses_jsonb_comparison():
    sql, params = _compile_filter({"tenant_id": "t1"})
    assert "(doc #> '{tenant_id}') = %s::jsonb" in sql
    assert params == ['"t1"']


def test_equality_keeps_native_json_types():
    _, params = _compile_filter({"age": 30, "ok": True, "ratio": 1.5, "nil": None})
    assert params == ["30", "true", "1.5", "null"]


def test_dotted_path_equality():
    sql, _ = _compile_filter({"profile.city": "北京"})
    assert "(doc #> '{profile,city}') = %s::jsonb" in sql


def test_ne_matches_missing_field_semantics():
    sql, _ = _compile_filter({"age": {"$ne": 30}})
    # Mongo 语义：字段缺失也满足 $ne
    assert "IS NULL" in sql and "NOT IN" not in sql


def test_numeric_range_uses_numeric_cast():
    sql, params = _compile_filter({"age": {"$gte": 18}})
    assert "::numeric" in sql and "jsonb_typeof" in sql
    assert params == []  # 数值字面量内联，不占参数


def test_text_range_falls_back_to_text_comparison():
    sql, params = _compile_filter({"name": {"$gt": "m"}})
    assert "::numeric" not in sql
    assert params == ["m"]


def test_in_and_nin():
    sql, params = _compile_filter({"role": {"$in": ["a", "b"]}})
    assert sql.count("%s") == 2
    assert params == ['"a"', '"b"']

    sql, _ = _compile_filter({"role": {"$nin": ["a"]}})
    assert "IS NULL OR" in sql and "NOT IN" in sql


def test_in_empty_list_short_circuits():
    assert "FALSE" in _compile_filter({"role": {"$in": []}})[0]
    assert "TRUE" in _compile_filter({"role": {"$nin": []}})[0]


def test_exists():
    positive = _compile_filter({"profile": {"$exists": True}})[0]
    negative = _compile_filter({"profile": {"$exists": False}})[0]
    assert "IS NOT NULL" in positive
    # 取反时在外层包一层 NOT
    assert "IS NOT NULL" in negative and negative != positive
    assert negative.replace("NOT", "", 1) != positive.replace("NOT", "", 1)


def test_regex_without_and_with_case_insensitive_option():
    sql, params = _compile_filter({"name": {"$regex": "^a"}})
    assert "~ %s" in sql and params == ["^a"]

    sql, _ = _compile_filter({"name": {"$regex": "^a", "$options": "i"}})
    assert "~*" in sql
    # $options 是修饰符，不应被当成独立算子
    assert "$options" not in sql


def test_size_and_all():
    assert "jsonb_array_length" in _compile_filter({"tags": {"$size": 2}})[0]
    sql, params = _compile_filter({"tags": {"$all": ["a", "b"]}})
    assert sql.count("@>") == 2 and params == ['["a"]', '["b"]']


def test_or_and_nor_and_not():
    sql, _ = _compile_filter({"$or": [{"a": 1}, {"b": 2}]})
    assert " OR " in sql
    sql, _ = _compile_filter({"$nor": [{"a": 1}]})
    assert "NOT" in sql
    sql, _ = _compile_filter({"a": {"$not": {"$gt": 5}}})
    assert "NOT" in sql


def test_unsupported_filter_operators_fail_loudly():
    with pytest.raises(PgCompatUnsupported):
        _compile_filter({"a": {"$elemMatch": {"b": 1}}})
    with pytest.raises(PgCompatUnsupported):
        _compile_filter({"$where": "this.a > 1"})


# ── 更新算子 ──────────────────────────────────────────────────────────
def test_set_produces_one_step_per_field():
    steps, params = _compile_update({"$set": {"a": 1, "b": 2}})
    assert len(steps) == 2
    assert params == ["1", "2"]


def test_set_dotted_path_wraps_for_deep_merge():
    steps, _ = _compile_update({"$set": {"a.b.c": 1}})
    assert len(steps) == 1
    # 逐层回卷：内层 → 父层 → 收口，共 3 次 jsonb_set
    assert steps[0].count("jsonb_set") == 3
    assert "COALESCE(doc #> '{a,b}', '{}'::jsonb)" in steps[0]


def test_inc_uses_numeric_cast_and_no_param():
    steps, params = _compile_update({"$inc": {"age": 1}})
    assert len(steps) == 1 and params == []
    assert "::numeric" in steps[0] and "jsonb_set" in steps[0]


def test_unset_top_level_and_nested():
    steps, params = _compile_update({"$unset": {"a": ""}})
    assert steps == ["(doc - 'a')"] and params == []

    steps, _ = _compile_update({"$unset": {"a.b.c": ""}})
    # 嵌套删除：A 模式不支持 #-，改用「取出父节点 → 删键 → 写回」
    assert "#-" not in steps[0]
    assert "jsonb_set" in steps[0] and "- 'c'" in steps[0]


def test_push_single_and_each():
    steps, params = _compile_update({"$push": {"tags": "x"}})
    assert params == ['["x"]']  # 单元素数组字面量，不用 jsonb_build_array

    _, params = _compile_update({"$push": {"tags": {"$each": ["x", "y"]}}})
    assert params == ['["x", "y"]']


def test_add_to_set_dedupes_and_counts_placeholders_twice():
    steps, params = _compile_update({"$addToSet": {"tags": "x"}})
    # 占位符在判重与追加两处各出现一次，参数必须也入两次
    assert steps[0].count("%s") == 2
    assert params == ['"x"', '"x"']
    assert "@>" in steps[0]


def test_max_min_current_date():
    steps, params = _compile_update({"$max": {"age": 10}})
    assert "GREATEST" in steps[0] and params == []
    steps, _ = _compile_update({"$min": {"age": 10}})
    assert "LEAST" in steps[0]
    steps, _ = _compile_update({"$currentDate": {"updated_at": True}})
    assert "to_jsonb(now())" in steps[0]


def test_set_on_insert_only_applies_on_insert():
    assert _compile_update({"$setOnInsert": {"a": 1}}, is_insert=False)[0] == []
    assert len(_compile_update({"$setOnInsert": {"a": 1}}, is_insert=True)[0]) == 1


def test_replacement_update_is_rejected():
    with pytest.raises(PgCompatUnsupported):
        _compile_update({"a": 1})


def test_unsupported_update_operators_fail_loudly():
    with pytest.raises(PgCompatUnsupported):
        _compile_update({"$pull": {"tags": "x"}})
    with pytest.raises(PgCompatUnsupported):
        _compile_update({"$rename": {"a": "b"}})


# ── upsert 插入路径的 Python 侧算子 ────────────────────────────────────
def test_apply_update_to_document_deep_merges_without_losing_siblings():
    doc = {"a": {"b": {"keep": 1}}}
    out = apply_update_to_document(doc, {"$set": {"a.b.new": 2}})
    assert out["a"]["b"] == {"keep": 1, "new": 2}


def test_apply_update_to_document_inc_push_addtoset_unset():
    doc = {"n": 1, "tags": ["a"]}
    out = apply_update_to_document(
        doc,
        {"$inc": {"n": 2}, "$push": {"tags": "b"}, "$addToSet": {"tags": "a"}, "$unset": {"gone": ""}},
    )
    assert out["n"] == 3
    assert out["tags"] == ["a", "b"]  # $addToSet 去重，"a" 不重复
    assert "gone" not in out


def test_apply_update_to_document_does_not_mutate_input():
    doc = {"a": {"b": 1}}
    apply_update_to_document(doc, {"$set": {"a.b": 2}})
    assert doc == {"a": {"b": 1}}


# ── 聚合管道编译（R2）──────────────────────────────────────────────────
from app.core.pg_compat import _AggregationCompiler  # noqa: E402


def _compile_pipeline(pipeline):
    compiler = _AggregationCompiler('"s"."t"')
    sql = compiler.compile(pipeline)
    assert sql.count("%s") == len(compiler.params), (
        f"占位符/参数数量不符: {sql!r} vs {compiler.params!r}"
    )
    return sql, compiler.params


def test_aggregation_rejects_empty_and_malformed_pipeline():
    with pytest.raises(PgCompatUnsupported):
        _compile_pipeline([])
    with pytest.raises(PgCompatUnsupported):
        _compile_pipeline("not-a-list")
    with pytest.raises(PgCompatUnsupported):
        _compile_pipeline([{"$match": {}, "$group": {}}])   # 阶段必须是单键


def test_aggregation_unsupported_stage_fails_loudly():
    for stage in ({"$lookup": {}}, {"$facet": {}}, {"$unwind": "$x"}, {"$out": "t"}):
        with pytest.raises(PgCompatUnsupported):
            _compile_pipeline([stage])


def test_aggregation_match_group_sum_one():
    sql, params = _compile_pipeline([
        {"$match": {"tenant_id": "t1"}},
        {"$group": {"_id": "$event", "count": {"$sum": 1}}},
    ])
    assert "GROUP BY 1" in sql          # 用序号分组，避免重复写 key 表达式
    assert "count(*)" in sql
    assert params == ['"t1"']


def test_aggregation_group_uses_two_step_cte():
    """$group 必须拆成两步：先聚合出普通列，再组装文档。

    一步写完会被 PG 9.2 拒（jsonb_set 里引用的 key 表达式与 GROUP BY 的
    被判定为不同表达式 → column must appear in the GROUP BY clause）。
    """
    sql, _ = _compile_pipeline([{"$group": {"_id": "$a", "n": {"$sum": 1}}}])
    assert sql.count("jsonb_set") >= 1
    assert "GROUP BY 1" in sql
    # 组装阶段的来源必须是上一个 CTE，而不是原表
    assert "FROM ag2" in sql


def test_aggregation_min_max_avoid_textual_min_max():
    """$min/$max 不得用 min()/max() 聚合：openGauss 对 jsonb 按文本比较。"""
    sql, _ = _compile_pipeline([{"$group": {"_id": None, "m": {"$min": "$x"}, "M": {"$max": "$x"}}}])
    assert "min((doc #> '{x}'))" not in sql
    assert "max((doc #> '{x}'))" not in sql
    assert "array_agg" in sql and "ORDER BY" in sql


def test_aggregation_last_reverses_sort_direction():
    sql, _ = _compile_pipeline([
        {"$sort": {"created_at": 1}},
        {"$group": {"_id": "$m", "last": {"$last": "$stage"}}},
    ])
    # $last 用反向排序取数组首元素
    assert "DESC" in sql


def test_aggregation_group_key_expression_built_once():
    """key 表达式含字符串字面量时，占位符数量必须与参数一致（不重复构建）。"""
    sql, params = _compile_pipeline([
        {"$group": {"_id": {"$cond": [{"$eq": ["$s", "failed"]}, "failed", "ok"]}, "n": {"$sum": 1}}},
    ])
    assert sql.count("%s") == len(params) == 3


def test_aggregation_count_stage():
    sql, _ = _compile_pipeline([{"$group": {"_id": "$u"}}, {"$count": "count"}])
    assert "'{count}'" in sql           # 不能出现 '{{count}}'
    assert "HAVING count(*) > 0" in sql  # 输入为空时 Mongo 返回空结果集


def test_aggregation_numeric_accumulators_are_wrapped_as_jsonb():
    sql, _ = _compile_pipeline([{"$group": {"_id": None, "s": {"$sum": "$n"}, "a": {"$avg": "$n"}}}])
    assert "to_jsonb(COALESCE(sum(" in sql
    assert "to_jsonb(avg(" in sql


def test_aggregation_string_literals_are_json_encoded():
    """字符串字面量必须编码成 JSON（带引号），否则 ::jsonb 会报 invalid input syntax。"""
    sql, params = _compile_pipeline([
        {"$group": {"_id": {"$cond": [{"$eq": ["$s", "failed"]}, "failed", "ok"]}, "n": {"$sum": 1}}},
    ])
    assert params == ['"failed"', '"failed"', '"ok"']   # 注意带引号
    assert "to_jsonb" not in sql.split("to_jsonb(COALESCE")[0].split("CASE WHEN")[0][-40:]


def test_aggregation_expressions():
    sql, _ = _compile_pipeline([
        {"$group": {
            "_id": None,
            "a": {"$sum": {"$ifNull": ["$x", 0]}},
            # $max 的**数组形式**是表达式（取两值较大者），只有在 $group 字段值位置上
            # 才是累加器；这里嵌在 $sum 里，因此走表达式分支。
            "b": {"$sum": {"$max": [0, {"$subtract": [{"$ifNull": ["$e", 0]}, {"$ifNull": ["$s", 0]}]}]}},
        }},
    ])
    assert "COALESCE(NULLIF(" in sql
    assert "GREATEST(" in sql and " - " in sql


def test_aggregation_group_max_is_accumulator_not_expression():
    """$group 字段值位置上的 $max 是累加器（对数组表达式取最大），不是 GREATEST。"""
    sql, _ = _compile_pipeline([{"$group": {"_id": None, "m": {"$max": [0, "$x"]}}}])
    assert "array_agg" in sql
    assert "GREATEST(" not in sql


def test_aggregation_unsupported_accumulator_and_expression_fail_loudly():
    with pytest.raises(PgCompatUnsupported):
        _compile_pipeline([{"$group": {"_id": None, "x": {"$stdDevPop": "$a"}}}])
    with pytest.raises(PgCompatUnsupported):
        _compile_pipeline([{"$group": {"_id": None, "x": {"$sum": {"$toUpper": "$a"}}}}])


def test_aggregation_percentile_uses_ordered_set_aggregate():
    sql, _ = _compile_pipeline([
        {"$project": {"p": {"$percentile": {"input": "$v", "p": [0.5, 0.95], "method": "approximate"}}}},
    ])
    assert sql.count("percentile_cont(") == 2
    assert "WITHIN GROUP (ORDER BY" in sql


def test_aggregation_project_inclusion_exclusion_rules():
    with pytest.raises(PgCompatUnsupported):
        _compile_pipeline([{"$project": {"a": 1, "b": 0}}])
    sql, _ = _compile_pipeline([{"$project": {"a": 0}}])
    assert "- 'a'" in sql


# ── $regex 方言翻译（PCRE → openGauss ARE）─────────────────────────────
def test_regex_word_boundary_translated_to_are():
    # PG 的 ARE 里 \b 是退格符而非词边界，必须翻成 \y
    assert translate_regex_pattern(r"\badmin\b") == r"\yadmin\y"


def test_regex_non_boundary_translated_to_are():
    assert translate_regex_pattern(r"\Bx") == r"\Yx"


def test_regex_word_class_translated_to_ascii():
    # PG 在 UTF-8 locale 下 \w 含非 ASCII，这里锁成 ASCII 语义
    assert translate_regex_pattern(r"\w+") == r"[A-Za-z0-9_]+"
    assert translate_regex_pattern(r"\W") == r"[^A-Za-z0-9_]"


def test_regex_common_constructs_passthrough():
    # 这些构造在两种方言里语义一致，不应被改动
    for pattern in (r"^a", r"a|b", r"a\.b", r"foo", r"[a-z]+", r"\d", r"café", r"(?i)abc"):
        assert translate_regex_pattern(pattern) == pattern


def test_regex_rejects_unicode_property():
    with pytest.raises(PgCompatUnsupported):
        translate_regex_pattern(r"\p{L}")


def test_regex_rejects_named_group():
    with pytest.raises(PgCompatUnsupported):
        translate_regex_pattern(r"(?P<name>abc)")


def test_regex_rejects_posix_word_class():
    with pytest.raises(PgCompatUnsupported):
        translate_regex_pattern(r"[[:word:]]")


# ── create_index 的 unique / sparse / partial 语义（纯 SQL 生成）─────────
def test_create_index_plain_no_where():
    sql = _build_create_index_sql('"s"."t"', "t_tenant_idx", ["tenant_id"])
    assert "CREATE INDEX IF NOT EXISTS \"t_tenant_idx\"" in sql
    assert "ON \"s\".\"t\" ((doc #> '{tenant_id}'))" in sql
    assert "WHERE" not in sql


def test_create_index_unique_adds_unique_keyword():
    sql = _build_create_index_sql('"s"."t"', "t_code_idx", ["code"], unique=True)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in sql


def test_create_index_sparse_adds_not_null_where():
    sql = _build_create_index_sql('"s"."t"', "t_seq_idx", ["seq"], unique=True, sparse=True)
    assert "CREATE UNIQUE INDEX" in sql
    assert "WHERE (doc #> '{seq}') IS NOT NULL" in sql


def test_create_index_partial_inlines_filter_as_literal():
    sql = _build_create_index_sql(
        '"s"."t"', "t_status_idx", ["status"],
        partialFilterExpression={"status": "active"},
    )
    assert "WHERE" in sql
    # 参数已被内联成字面量，SQL 里不应残留占位符，且值以 JSON 文本形式出现
    assert "'\"active\"'" in sql and "::jsonb" in sql
    assert "%s" not in sql


def test_create_index_partial_and_sparse_conjunction():
    sql = _build_create_index_sql(
        '"s"."t"', "t_idx", ["a", "b"], unique=True, sparse=True,
        partialFilterExpression={"b": 1},
    )
    assert sql.count("AND") == 2  # 两个稀疏字段 + 一个 partial
    assert "IS NOT NULL" in sql
    assert "(doc #> '{b}') = '1'::jsonb" in sql


# ── TTL（expireAfterSeconds）登记与清理 ─────────────────────────────────


class _FakeCursor:
    def __init__(self, log, rowcount):
        self._log = log
        self.rowcount = rowcount

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self._log.append((sql, params))


class _FakeConn:
    def __init__(self, log, rowcount):
        self._log = log
        self._rowcount = rowcount

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self._log, self._rowcount)


class _FakePool:
    def __init__(self, rowcount=0):
        self.log: list = []
        self._rowcount = rowcount

    def connection(self):
        return _FakeConn(self.log, self._rowcount)


@pytest.fixture(autouse=True)
def _clean_ttl_registry():
    from app.core import pg_compat

    pg_compat._TTL_REGISTRY.clear()
    yield
    pg_compat._TTL_REGISTRY.clear()


@pytest.mark.asyncio
async def test_create_index_registers_ttl_declaration():
    from app.core import pg_compat
    from app.core.pg_compat import PgCollection

    coll = PgCollection(_FakePool(), "end_user_sessions", "s")

    async def _noop(sql, params):
        return None

    coll._execute = _noop  # type: ignore[assignment]
    await coll.create_index([("expires_at", 1)], expireAfterSeconds=0)
    assert pg_compat.ttl_registry_snapshot()["end_user_sessions"] == ("expires_at", 0)


@pytest.mark.asyncio
async def test_purge_expired_ttl_builds_delete_and_counts():
    from app.core import pg_compat
    from app.core.pg_compat import purge_expired_ttl

    pg_compat._TTL_REGISTRY["t"] = ("expires_at", 0)
    pool = _FakePool(rowcount=3)
    deleted = await purge_expired_ttl(pool, "s")
    assert deleted == 3
    sql, params = pool.log[0]
    assert 'DELETE FROM "s"."t"' in sql
    assert "doc ->> %s" in sql
    assert params[0] == "expires_at"


@pytest.mark.asyncio
async def test_purge_expired_ttl_applies_offset_for_nonzero_seconds():
    from app.core import pg_compat
    from app.core.pg_compat import purge_expired_ttl

    pg_compat._TTL_REGISTRY["audit"] = ("occurred_at", 86400)
    pool = _FakePool(rowcount=1)
    await purge_expired_ttl(pool, "s")
    _, params = pool.log[0]
    assert params[0] == "occurred_at"


# ── R3 扁平化（027 方案 §5）────────────────────────────────────────────
from app.core.column_map import (  # noqa: E402
    COLUMN_MAP,
    COLUMN_TYPES,
    column_type,
    mapped_columns,
)
from app.core.pg_compat import (  # noqa: E402
    PgCollection,
    _column_param_sql,
    _column_sync_sql,
    _column_value_to_doc,
)


def _flat_filter_compiler(table: str) -> _FilterCompiler:
    """按 COLUMN_MAP 构造编译器（模拟 PgCollection 的用法）。"""
    return _FilterCompiler(mapped_columns(table))


def test_column_map_invariants():
    """单一数据源不变量：44 表、列都有类型、doc_key↔column 1:1、基础列不入表。"""
    assert len(COLUMN_MAP) == 44
    base = {"id", "tenant_id", "created_at", "updated_at"}
    for table, entries in COLUMN_MAP.items():
        seen: dict[str, str] = {}
        for key, col in entries.items():
            assert col in COLUMN_TYPES, f"{table}.{col} 缺少类型"
            assert col not in base, f"{table}: 基础列 {col} 不应入映射"
            assert col not in seen, f"{table}: 列 {col} 被 {seen[col]} 与 {key} 重复映射"
            seen[col] = key
        assert entries, f"{table} 映射为空"
    # 语义别名（doc_key != column）必须在档
    assert COLUMN_MAP["admin_accounts"]["username"] == "login_name"
    assert COLUMN_MAP["admin_accounts"]["display_name"] == "name"
    assert COLUMN_MAP["chat_sessions"]["user_id"] == "owner_user_id"
    assert COLUMN_MAP["organizations"]["org_name"] == "name"
    # 非扁平表无映射
    assert mapped_columns("audit_events") == {}


def test_filter_routes_mapped_keys_to_real_columns():
    # 注意：过滤键是 **doc_key**（业务代码视角），命中后走真实列。
    compiler = _flat_filter_compiler("chat_sessions")
    sql = compiler.compile({"user_id": "u1"})
    assert sql == '("owner_user_id" = %s::text)'
    assert compiler.params == ["u1"]

    compiler = _flat_filter_compiler("knowledge_documents")
    sql = compiler.compile({"status": {"$in": ["ready", "failed"]}})
    assert sql == '(("status" IN (%s::text, %s::text)))'
    assert compiler.params == ["ready", "failed"]

    compiler = _flat_filter_compiler("knowledge_documents")
    sql = compiler.compile({"file_size": {"$gte": 1024}})
    assert sql == '(("file_size" >= %s::numeric))'
    assert compiler.params == [1024]

    # end_users 的别名方向：doc 键 name → 列 display_name
    compiler = _flat_filter_compiler("end_users")
    sql = compiler.compile({"name": {"$regex": "张.*"}})
    assert sql == '((("display_name"::text) ~ %s))'
    assert compiler.params == ["张.*"]

    compiler = _flat_filter_compiler("chat_sessions")
    assert compiler.compile({"deleted_at": None}) == '("deleted_at" IS NULL)'
    assert compiler.compile({"deleted_at": {"$ne": None}}) == '(("deleted_at" IS NOT NULL))'
    assert compiler.compile({"deleted_at": {"$exists": False}}) == (
        '((NOT ("deleted_at" IS NOT NULL)))'
    )


def test_filter_keeps_doc_path_for_unmapped_and_nested_keys():
    compiler = _flat_filter_compiler("chat_sessions")
    sql = compiler.compile({"custom_dynamic": "x", "a.b": 1})
    assert '(doc #> \'{custom_dynamic}\') = %s::jsonb' in sql
    assert "(doc #> '{a,b}') = %s::jsonb" in sql
    # to_json_text 把值统一序列化成 JSON 文本（字符串带引号，数字不带）
    assert compiler.params == ['"x"', '1']


def test_filter_jsonb_mapped_column_uses_jsonb_equality():
    compiler = _flat_filter_compiler("chat_sessions")
    sql = compiler.compile({"participant_ids": ["x"]})
    assert sql == '("participant_ids" = %s::jsonb)'
    assert compiler.params == ['["x"]']


def test_create_index_uses_real_columns_for_mapped_fields():
    # 索引键同样是 doc_key：user_id 命中 owner_user_id 列，title 同名命中。
    sql = _build_create_index_sql(
        '"s"."chat_sessions"',
        "idx_x",
        ["user_id", "title"],
        column_map=mapped_columns("chat_sessions"),
    )
    assert sql == 'CREATE INDEX IF NOT EXISTS "idx_x" ON "s"."chat_sessions" ("owner_user_id", "title")'


def test_create_index_partial_filter_routes_mapped_null():
    sql = _build_create_index_sql(
        '"s"."chat_sessions"',
        "uq_y",
        ["status"],
        unique=True,
        partialFilterExpression={"deleted_at": None},
        column_map=mapped_columns("chat_sessions"),
    )
    # 软删除部分唯一索引：None 必须编译成 IS NULL（不能是 'null'::timestamptz）
    assert sql.endswith('WHERE ("deleted_at" IS NULL)')
    assert "'null'" not in sql


def test_create_index_unmapped_field_keeps_expression_form():
    sql = _build_create_index_sql(
        '"s"."end_user_sessions"',
        "idx_z",
        ["expires_at"],
        column_map=mapped_columns("end_user_sessions"),
    )
    assert "(doc #> '{expires_at}')" in sql


def test_column_sync_sql_guards_json_null():
    # 本库没有 jsonb ->> text[] 运算符：-> / ->> 遇 '{a,b}' 字面量只匹配
    # text 重载（键名变成字面 "{a,b}"），恒为 NULL，列会被静默写空。
    # 因此路径必须用 #> / #>>；JSON null 识别用纯运算符比较（#> = 'null'::jsonb）。
    assert _column_sync_sql("s1.doc", "owner_user_id", "owner_user_id") == (
        "(CASE WHEN (s1.doc #> '{owner_user_id}') = 'null'::jsonb "
        "THEN NULL ELSE (s1.doc #>> '{owner_user_id}')::text END)"
    )
    assert _column_sync_sql("s1.doc", "sort_order", "sort_order") == (
        "(CASE WHEN (s1.doc #> '{sort_order}') = 'null'::jsonb "
        "THEN NULL ELSE (s1.doc #>> '{sort_order}')::integer END)"
    )
    assert _column_sync_sql("s1.doc", "tags", "tags") == "s1.doc #> '{tags}'"
    synced = _column_sync_sql("s1.doc", "deleted_at", "deleted_at")
    assert "jsonb_typeof" not in synced
    # 回归：任何 -> / ->> 花括号路径字面量都不允许出现（真库上静默写 NULL）
    assert "->'" not in synced and "->>'" not in synced


def test_column_param_sql_types():
    assert _column_param_sql("owner_user_id") == "%s::text"
    assert _column_param_sql("sort_order") == "%s::integer"
    assert _column_param_sql("file_size") == "%s::bigint"
    assert _column_param_sql("tags") == "%s::jsonb"


def test_column_value_to_doc_serializes_datetime():
    from datetime import datetime, timezone

    iso = "2026-10-16T08:00:00+00:00"
    assert _column_value_to_doc(datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)) == iso
    assert _column_value_to_doc("plain") == "plain"
    assert _column_value_to_doc(12) == 12


class _RecordingPool(_FakePool):
    """记录 SQL 且可按脚本返回行的连接池。"""

    def __init__(self, rows=None, rowcount=0):
        super().__init__(rowcount=rowcount)
        self._rows = rows or []


class _RowsCursor(_FakeCursor):
    def __init__(self, log, rows):
        super().__init__(log, 0)
        self._rows = rows

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _RowsConn(_FakeConn):
    def __init__(self, log, rows):
        super().__init__(log, 0)
        self._rows = rows

    def cursor(self):
        return _RowsCursor(self._log, self._rows)


class _RowsPool(_FakePool):
    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    def connection(self):
        return _RowsConn(self.log, self._rows)


@pytest.mark.asyncio
async def test_insert_one_dual_writes_mapped_columns():
    coll = PgCollection(_RowsPool(), "chat_sessions", "s")
    captured: list = []

    async def _capture(sql, params):
        captured.append((sql, params))
        return 1

    coll._execute = _capture  # type: ignore[assignment]
    await coll.insert_one({
        "_id": "s1", "tenant_id": "t1", "title": "会话",
        "user_id": "u9",  # doc 键 user_id → owner_user_id 列
        "tags": ["a"],
    })
    sql, params = captured[0]
    assert "INSERT INTO \"s\".\"chat_sessions\" (id, tenant_id, doc," in sql
    assert '"owner_user_id"' in sql and '"title"' in sql and '"participant_ids"' in sql
    # doc 仍是第一份载荷；列值按 doc 键取值（JSONB 列序列化）
    assert params[0] == "s1" and params[1] == "t1"
    assert '"user_id": "u9"' in params[2]
    assert "u9" in params            # owner_user_id 列参数
    assert '"tags": ["a"]' in params[2]  # 未映射键只进 doc


@pytest.mark.asyncio
async def test_insert_one_without_mapping_keeps_original_sql():
    coll = PgCollection(_RowsPool(), "end_user_sessions", "s")
    captured: list = []

    async def _capture(sql, params):
        captured.append((sql, params))
        return 1

    coll._execute = _capture  # type: ignore[assignment]
    await coll.insert_one({"_id": "x", "tenant_id": "t"})
    sql, params = captured[0]
    assert sql == (
        'INSERT INTO "s"."end_user_sessions" (id, tenant_id, doc) '
        "VALUES (%s, %s, %s::jsonb) ON CONFLICT (id) DO NOTHING"
    )
    assert len(params) == 3


@pytest.mark.asyncio
async def test_update_cte_syncs_mapped_columns():
    coll = PgCollection(_RowsPool(), "chat_sessions", "s")
    captured: list = []

    async def _scalar(sql, params):
        return 1

    async def _execute(sql, params):
        captured.append((sql, params))
        return 1

    coll._scalar = _scalar  # type: ignore[assignment]
    coll._execute = _execute  # type: ignore[assignment]
    await coll.update_one({"_id": "s1"}, {"$set": {"user_id": "u7", "title": "新标题"}})
    sql, _params = captured[0]
    # 两个 $set → 步骤链 s0/s1/s2，末段 s2.doc 是最终 doc
    assert "SET" in sql and "doc = s2.doc" in sql
    # JSON null 防护：纯运算符比较；路径一律 #> / #>>（无 ->> text[] 运算符）
    assert "(CASE WHEN (s2.doc #> '{user_id}') = 'null'::jsonb THEN NULL ELSE (s2.doc #>> '{user_id}')::text END)" in sql
    assert "(s2.doc #>> '{title}')::text" in sql
    assert "jsonb_typeof" not in sql
    # 回归：花括号路径字面量禁止走 -> / ->>（真库上静默写 NULL）
    assert "->'" not in sql and "->>'" not in sql


@pytest.mark.asyncio
async def test_find_one_selects_mapped_columns():
    coll = PgCollection(_RowsPool(), "chat_sessions", "s")
    captured: list = []

    async def _merged(sql, params, entries):
        captured.append((sql, entries))
        return []

    coll._fetch_merged = _merged  # type: ignore[assignment]
    await coll.find_one({"_id": "s1"})
    sql, entries = captured[0]
    assert sql.startswith('SELECT doc, "')
    assert '"owner_user_id"' in sql and '"title"' in sql and '"participant_ids"' in sql
    assert ("user_id", "owner_user_id") in entries


@pytest.mark.asyncio
async def test_read_path_merges_columns_over_doc():
    """列值非空覆盖 doc；datetime 序列化回 ISO 字符串保持 doc 形状。"""
    from datetime import datetime, timezone

    doc_json = '{"_id": "s1", "title": "旧标题", "user_id": "u1"}'
    # 行值顺序 = chat_sessions 的 entries 顺序（doc_key 排序，见 COLUMN_MAP）
    rows = [(
        doc_json,
        "creator-1",                                        # created_by
        datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc),  # deleted_at
        None,                                               # last_message_at
        "m-1",                                              # last_message_id
        "预览",                                              # last_message_preview
        ["u1", "u2"],                                       # participant_ids (JSONB)
        "active",                                           # status
        "标题",                                              # title
        "p2p",                                              # type
        None,                                               # updated_by
        "u2",                                               # user_id -> owner_user_id
    )]
    coll = PgCollection(_RowsPool(rows=rows), "chat_sessions", "s")
    # 用真实 _fetch_merged 走一遍
    docs = await coll._fetch_merged("SELECT doc, ...", [], coll._column_entries())
    assert docs[0]["_id"] == "s1"
    assert docs[0]["title"] == "标题"             # 列覆盖 doc 旧值
    assert docs[0]["user_id"] == "u2"             # doc 键被别名列值覆盖（列优先）
    assert docs[0]["deleted_at"] == "2026-10-16T08:00:00+00:00"  # datetime 保形
    assert "last_message_at" not in docs[0]       # 列 NULL 且 doc 无键 → 不新增
    assert docs[0]["participant_ids"] == ["u1", "u2"]
    assert docs[0]["created_by"] == "creator-1"


# ── R3 后续优化：排序 / 去重 / 聚合路由 ──────────────────────────────────
from app.core.pg_compat import (  # noqa: E402
    _AggregationCompiler,
    _order_by,
    _order_expr,
)


def test_order_expr_routes_mapped_keys_to_real_columns():
    columns = mapped_columns("chat_sessions")
    assert _order_expr("user_id", 1, columns) == '"owner_user_id" ASC'
    assert _order_expr("last_message_at", -1, columns) == '"last_message_at" DESC'
    # 未命中 / 嵌套路径维持 doc 路径
    assert _order_expr("custom_dynamic", 1, columns) == "doc #> '{custom_dynamic}' ASC"
    assert _order_expr("a.b", -1, columns) == "doc #> '{a,b}' DESC"
    # 非扁平表：columns 为空 → doc 路径（与改造前一致）
    assert _order_expr("status", 1, {}) == "doc #> '{status}' ASC"


def test_order_by_accepts_optional_column_map():
    sort = [("user_id", 1), ("custom_dynamic", -1)]
    assert _order_by(sort, mapped_columns("chat_sessions")) == (
        ' ORDER BY "owner_user_id" ASC, doc #> \'{custom_dynamic}\' DESC'
    )
    assert _order_by(sort) == (
        " ORDER BY doc #> '{user_id}' ASC, doc #> '{custom_dynamic}' DESC"
    )
    assert _order_by(None, mapped_columns("chat_sessions")) == ""


@pytest.mark.asyncio
async def test_find_one_sort_routes_mapped_keys():
    coll = PgCollection(_RowsPool(), "chat_sessions", "s")
    captured: list = []

    async def _merged(sql, params, entries):
        captured.append(sql)
        return []

    coll._fetch_merged = _merged  # type: ignore[assignment]
    await coll.find_one({"user_id": "u1"}, sort=[("user_id", -1), ("custom_dynamic", 1)])
    sql = captured[0]
    assert 'ORDER BY "owner_user_id" DESC, doc #> \'{custom_dynamic}\' ASC LIMIT 1' in sql


@pytest.mark.asyncio
async def test_cursor_sort_routes_mapped_keys():
    coll = PgCollection(_RowsPool(rows=[("{}",)] + [None] * 11), "chat_sessions", "s")
    captured: list = []

    async def _merged(sql, params, entries):
        captured.append(sql)
        return []

    coll._fetch_merged = _merged  # type: ignore[assignment]
    cursor = coll.find({}).sort("user_id", 1).sort("custom_dynamic", -1).limit(5)
    await cursor.to_list()
    sql = captured[0]
    assert 'ORDER BY "owner_user_id" ASC, doc #> \'{custom_dynamic}\' DESC LIMIT 5' in sql
    assert "->'" not in sql and "->>'" not in sql


@pytest.mark.asyncio
async def test_distinct_routes_mapped_key():
    coll = PgCollection(_RowsPool(), "chat_sessions", "s")
    captured: list = []

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def cursor(self):
            return _CapturingCursor(captured, rows=[("u1",), (None,)])

    coll._pool.connection = lambda: _Conn()  # type: ignore[assignment]
    result = await coll.distinct("user_id", {"tenant_id": "t1"})
    sql = captured[0]
    assert 'SELECT DISTINCT "owner_user_id" AS v' in sql
    assert "->'" not in sql and "->>'" not in sql
    assert result == ["u1"]  # None 被过滤；text 列形状不变


@pytest.mark.asyncio
async def test_distinct_normalizes_column_value_shapes():
    from datetime import datetime, timezone
    from decimal import Decimal

    coll = PgCollection(_RowsPool(), "knowledge_documents", "s")
    captured: list = []

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def cursor(self):
            return _CapturingCursor(
                captured,
                rows=[
                    (datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc), "file_size"),
                    (Decimal("1024"), "file_size"),
                    (Decimal("10.5"), "file_size"),
                ],
            )

    coll._pool.connection = lambda: _Conn()  # type: ignore[assignment]
    result = await coll.distinct("file_size")
    assert result == [
        "2026-10-16T08:00:00+00:00",  # timestamptz → ISO 字符串（doc 路径同形状）
        1024,                          # Decimal 整数 → int
        10.5,                          # Decimal 小数 → float
    ]


@pytest.mark.asyncio
async def test_distinct_keeps_doc_path_for_unmapped_key():
    coll = PgCollection(_RowsPool(), "chat_sessions", "s")
    captured: list = []

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def cursor(self):
            return _CapturingCursor(captured, rows=[("x",)])

    coll._pool.connection = lambda: _Conn()  # type: ignore[assignment]
    await coll.distinct("a.b")
    assert "SELECT DISTINCT doc #> '{a,b}' AS v" in captured[0]


class _CapturingCursor:
    def __init__(self, log, rows):
        self._log = log
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self._log.append(sql)

    async def fetchall(self):
        return self._rows


def _agg_sql(pipeline, table="chat_sessions"):
    compiler = _AggregationCompiler('"s"."chat_sessions"', mapped_columns(table))
    sql = compiler.compile(pipeline)
    assert len(PLACEHOLDER.findall(sql)) == len(compiler.params), (
        f"占位符/参数数量不符: {sql!r} vs {compiler.params!r}"
    )
    return sql, compiler.params


def test_aggregate_first_stage_match_routes_mapped_keys():
    sql, params = _agg_sql([{"$match": {"user_id": "u1", "status": {"$in": ["a"]}}}])
    assert '("owner_user_id" = %s::text)' in sql
    assert '(("status" IN (%s::text)))' in sql
    # 路由到 text 列后 $in 参数是原始值（doc 路径才会 JSON 序列化成 '"a"'）
    assert params == ["u1", "a"]
    assert "->'" not in sql and "->>'" not in sql


def test_aggregate_match_after_group_keeps_doc_path():
    # $group 之后的阶段输入是 (id, doc) CTE，没有真实列 → 必须走 doc 路径
    sql, _params = _agg_sql([
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$match": {"user_id": "u1"}},
    ])
    assert "(doc #> '{user_id}') = %s::jsonb" in sql
    assert '"owner_user_id"' not in sql


def test_aggregate_first_stage_sort_routes_mapped_keys():
    # $sort 首阶段：自身 ORDER BY 走列；存入 _order 的复用表达式保持 doc 路径
    sql, _params = _agg_sql([{"$sort": {"user_id": -1, "custom_dynamic": 1}}])
    assert 'ORDER BY "owner_user_id" DESC, doc #> \'{custom_dynamic}\' ASC' in sql
    assert "->'" not in sql and "->>'" not in sql
    # 后续 $limit 复用 doc 路径（CTE 上才有效）
    sql2, _p2 = _agg_sql([
        {"$sort": {"user_id": -1}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$limit": 5},
    ])
    assert 'ORDER BY "owner_user_id" DESC' in sql2
    assert "(doc #> '{user_id}') DESC" in sql2


def test_aggregate_sort_after_match_keeps_doc_path():
    sql, _params = _agg_sql([
        {"$match": {"status": "ready"}},
        {"$sort": {"user_id": 1}},
    ])
    # 第二个阶段的输入是 CTE（ag1），只有 (id, doc)
    assert "ORDER BY (doc #> '{user_id}') ASC" in sql
    assert '"owner_user_id" ASC' not in sql


def test_aggregate_group_still_uses_doc_path():
    # $group 的 _id 与累加器仍走 doc 路径（本次不改语义）
    sql, _params = _agg_sql([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}])
    assert "GROUP BY 1" in sql
    # _expr_json 自带一层括号，f"({key_sql}) AS k" 再包一层
    assert "((doc #> '{user_id}')) AS k" in sql


def test_column_value_to_doc_normalizes_decimal():
    from decimal import Decimal

    assert _column_value_to_doc(Decimal("5")) == 5
    assert isinstance(_column_value_to_doc(Decimal("5")), int)
    assert _column_value_to_doc(Decimal("5.5")) == 5.5
    assert isinstance(_column_value_to_doc(Decimal("5.5")), float)
