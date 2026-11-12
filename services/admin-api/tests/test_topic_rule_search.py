from __future__ import annotations

import asyncio

from app.topic_admission.models import TopicChangesPayload, TopicRule
from app.topic_admission import rules as topic_rules


def _rule(rule_id: str, keyword: str) -> dict:
    return {"id": rule_id, "enabled": True, "terms": [{"keyword": keyword, "synonyms": []}]}


def test_named_rule_keeps_multiple_keyword_groups() -> None:
    rule = TopicRule.model_validate({
        "id": "finance", "name": "  财务专用白名单  ",
        "terms": [
            {"keyword": "报销", "synonyms": ["费用报销"]},
            {"keyword": "预算", "synonyms": ["财务预算"]},
        ],
    })
    assert rule.name == "财务专用白名单"
    assert len(rule.terms) == 2
    assert TopicRule.model_validate(_rule("legacy", "财务")).name == ""


def test_partial_save_keeps_rules_that_were_not_loaded() -> None:
    existing = [_rule("a", "股票"), _rule("b", "基金"), _rule("c", "债券")]
    changes = TopicChangesPayload.model_validate({
        "mode": "denylist",
        "upserts": [_rule("b", "证券"), _rule("d", "黄金")],
        "deletes": ["a"],
    })

    merged = topic_rules.merge_rules(existing, changes)

    assert [rule["id"] for rule in merged] == ["b", "c", "d"]
    assert merged[0]["terms"][0]["keyword"] == "证券"
    assert merged[1] == existing[2]


def _policy(rules: list[dict], monkeypatch) -> None:
    """用 find_one 返回单文档；断言查询条件仍是 tenant_id 精确匹配。"""
    class Collection:
        async def find_one(self, flt):
            assert flt == {"tenant_id": "org"}
            return {"tenant_id": "org", "rules": rules}

    monkeypatch.setattr(topic_rules, "get_db", lambda: {topic_rules.COLLECTION: Collection()})


def test_search_filters_by_keyword_and_status_and_pages(monkeypatch) -> None:
    rules = [
        {"id": f"r{i}", "name": "基金.", "enabled": True,
         "terms": [{"keyword": "基金.", "synonyms": []}]}
        for i in range(21)
    ]
    # 这两条不应进入 enabled + 关键字过滤后的结果集
    rules.append({"id": "off", "name": "基金.", "enabled": False,
                  "terms": [{"keyword": "基金.", "synonyms": []}]})
    rules.append({"id": "other", "name": "无关", "enabled": True,
                  "terms": [{"keyword": "股票", "synonyms": []}]})
    _policy(rules, monkeypatch)

    result = asyncio.run(topic_rules.search_rules("org", "基金.", "enabled", 2, 10))
    assert result["total"] == 21
    assert result["page"] == 2 and result["pageSize"] == 10
    assert [row["id"] for row in result["items"]] == [f"r{i}" for i in range(10, 20)]

    disabled = asyncio.run(topic_rules.search_rules("org", "基金.", "disabled", 1, 10))
    assert [row["id"] for row in disabled["items"]] == ["off"]


def test_search_matches_synonyms_and_regex_is_escaped(monkeypatch) -> None:
    rules = [
        {"id": "a", "name": "", "enabled": True,
         "terms": [{"keyword": "报销", "synonyms": ["费用报销"]}]},
        {"id": "b", "name": "", "enabled": True,
         "terms": [{"keyword": "预算X", "synonyms": []}]},
    ]
    _policy(rules, monkeypatch)
    hit = asyncio.run(topic_rules.search_rules("org", "费用报销", "all", 1, 10))
    assert hit["total"] == 1 and hit["items"][0]["id"] == "a"
    # 正则元字符被转义：字面量 "报销." 不应匹配 "报销"
    escaped = asyncio.run(topic_rules.search_rules("org", "报销.", "all", 1, 10))
    assert escaped["total"] == 0


def test_search_supports_offset_for_unsaved_new_rules(monkeypatch) -> None:
    rules = [{"id": f"r{i}", "enabled": True,
              "terms": [{"keyword": f"k{i}", "synonyms": []}]} for i in range(20)]
    _policy(rules, monkeypatch)
    result = asyncio.run(topic_rules.search_rules("org", "", "all", 2, 10, offset=9))
    assert result["total"] == 20
    assert len(result["items"]) == 10
    assert result["items"][0]["id"] == "r9"


def test_search_without_policy_returns_empty(monkeypatch) -> None:
    class Collection:
        async def find_one(self, flt):
            return None

    monkeypatch.setattr(topic_rules, "get_db", lambda: {topic_rules.COLLECTION: Collection()})
    assert asyncio.run(topic_rules.search_rules("org", "", "all", 1, 10)) == {
        "items": [], "total": 0, "page": 1, "pageSize": 10,
    }
