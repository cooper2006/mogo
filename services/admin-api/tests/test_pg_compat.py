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
    apply_update_to_document,
    path_literal,
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
