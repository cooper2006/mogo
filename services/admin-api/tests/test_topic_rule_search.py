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


def test_search_uses_server_side_filter_and_page(monkeypatch) -> None:
    class Cursor:
        async def to_list(self, *, length):
            assert length == 1
            return [{"items": [_rule("b", "基金")], "count": [{"value": 21}]}]

    class Collection:
        def aggregate(self, pipeline):
            assert pipeline[0] == {"$match": {"tenant_id": "org"}}
            assert pipeline[2]["$match"]["rules.enabled"] is True
            search = pipeline[2]["$match"]["$or"]
            assert search[0]["rules.name"]["$regex"] == r"基金\."
            assert search[1]["rules.terms.keyword"]["$regex"] == r"基金\."
            assert pipeline[3]["$facet"]["items"][1] == {"$skip": 10}
            assert pipeline[3]["$facet"]["items"][2] == {"$limit": 10}
            return Cursor()

    monkeypatch.setattr(topic_rules, "get_db", lambda: {topic_rules.COLLECTION: Collection()})
    result = asyncio.run(topic_rules.search_rules("org", "基金.", "enabled", 2, 10))
    assert result == {"items": [_rule("b", "基金")], "total": 21, "page": 2, "pageSize": 10}


def test_search_supports_offset_for_unsaved_new_rules(monkeypatch) -> None:
    class Cursor:
        async def to_list(self, *, length):
            return [{"items": [], "count": [{"value": 20}]}]

    class Collection:
        def aggregate(self, pipeline):
            assert pipeline[2]["$facet"]["items"][1] == {"$skip": 9}
            return Cursor()

    monkeypatch.setattr(topic_rules, "get_db", lambda: {topic_rules.COLLECTION: Collection()})
    asyncio.run(topic_rules.search_rules("org", "", "all", 2, 10, offset=9))
