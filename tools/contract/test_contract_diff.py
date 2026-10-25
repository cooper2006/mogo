"""T034 契约兼容性 diff 的行为测试（FR-18/FR-20/FR-21/FR-22）。

锁定破坏性变更判定规则，确保契约演进不会被误放行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "contract"))

from diff import (  # noqa: E402
    BREAKING_TYPES,
    COMPAT_TYPES,
    diff_contracts,
    diff_interaction,
    index_interactions,
    is_deprecated_past_observation,
    norm_fields,
    responses_by_status,
)
from validate import FIELD_TYPES  # noqa: E402


def _item(iid="a", method="GET", path="/a", responses=None, **extra) -> dict:
    item = {
        "id": iid,
        "method": method,
        "path": path,
        "responses": responses or [{"status": 200, "fields": {"x": {"type": "int"}}}],
    }
    item.update(extra)
    return item


def _r200(fields, **kw) -> dict:
    return {"status": 200, "fields": fields, **kw}


def test_no_change_no_problems() -> None:
    old = {"interactions": [_item()]}
    assert diff_contracts(old, dict(old)) == []


def test_removed_interaction_is_breaking() -> None:
    problems = diff_contracts({"interactions": [_item(iid="a"), _item(iid="b")]},
                              {"interactions": [_item(iid="a")]})
    assert any(p["type"] == "removed_interaction" and p["id"] == "b" for p in problems)


def test_added_interaction_is_compat() -> None:
    problems = diff_contracts({"interactions": [_item(iid="a")]},
                              {"interactions": [_item(iid="a"), _item(iid="b")]})
    assert any(p["type"] == "added_interaction" and p["id"] == "b" for p in problems)


def test_changed_method_is_breaking() -> None:
    problems = diff_interaction(_item(method="GET"), _item(method="POST"))
    assert any(p["type"] == "changed_method" for p in problems)


def test_changed_path_is_breaking() -> None:
    problems = diff_interaction(_item(path="/a"), _item(path="/b"))
    assert any(p["type"] == "changed_path" for p in problems)


def test_removed_field_is_breaking() -> None:
    problems = diff_interaction(_item(responses=[_r200({"x": {"type": "int"}, "old": {"type": "str"}})]),
                                _item(responses=[_r200({"x": {"type": "int"}})]))
    assert any(p["type"] == "removed_field" and p["field"] == "old" for p in problems)


def test_changed_field_type_is_breaking() -> None:
    problems = diff_interaction(_item(responses=[_r200({"x": {"type": "int"}})]),
                                _item(responses=[_r200({"x": {"type": "str"}})]))
    assert any(p["type"] == "changed_field_type" and p["detail"] == "int -> str" for p in problems)


def test_optional_to_required_is_breaking() -> None:
    problems = diff_interaction(_item(responses=[_r200({"x": {"type": "int", "required": False}})]),
                                _item(responses=[_r200({"x": {"type": "int", "required": True}})]))
    assert any(p["type"] == "field_turned_required" for p in problems)


def test_new_required_field_is_breaking() -> None:
    problems = diff_interaction(_item(responses=[_r200({"x": {"type": "int"}})]),
                                _item(responses=[_r200({"x": {"type": "int"}, "y": {"type": "str", "required": True}})]))
    assert any(p["type"] == "new_required_field" and p["field"] == "y" for p in problems)


def test_new_optional_field_is_compat_fr21() -> None:
    problems = diff_interaction(_item(responses=[_r200({"x": {"type": "int"}})]),
                                _item(responses=[_r200({"x": {"type": "int"}, "y": {"type": "str"}})]))
    assert any(p["type"] == "new_optional_field" and p["field"] == "y" for p in problems)


def test_added_success_status_is_compat_fr21() -> None:
    problems = diff_interaction(
        _item(responses=[_r200({"x": {"type": "int"}})]),
        _item(responses=[_r200({"x": {"type": "int"}}), _r200({"x": {"type": "int"}}, status=201)]),
    )
    assert any(p["type"] == "new_success_status" and p["status"] == 201 for p in problems)


def test_removed_error_status_is_breaking() -> None:
    problems = diff_interaction(
        _item(responses=[{"status": 401, "error_codes": ["api.unauthorized"]}, _r200({})]),
        _item(responses=[_r200({})]),
    )
    assert any(p["type"] == "removed_error_status" and p["status"] == 401 for p in problems)


def test_removed_error_code_is_breaking() -> None:
    problems = diff_interaction(
        _item(responses=[{"status": 400, "error_codes": ["api.bad_request", "api.validation_error"]}]),
        _item(responses=[{"status": 400, "error_codes": ["api.bad_request"]}]),
    )
    assert any(p["type"] == "removed_error_code" and p["code"] == "api.validation_error" for p in problems)


def test_deprecated_removal_after_observation_period() -> None:
    problems = diff_contracts(
        {"interactions": [_item(iid="old", deprecated=True, deprecated_since="2020-01-01")]},
        {"interactions": []},
    )
    assert any(p["type"] == "removed_interaction_deprecated" for p in problems)
    assert all(p["type"] in COMPAT_TYPES for p in problems)


def test_deprecated_removal_within_observation_period_is_breaking() -> None:
    problems = diff_contracts(
        {"interactions": [_item(iid="old", deprecated=True, deprecated_since="2026-10-01")]},
        {"interactions": []},
    )
    assert any(p["type"] == "removed_interaction" for p in problems)


def test_is_deprecated_past_observation_window() -> None:
    assert is_deprecated_past_observation({"deprecated_since": "2020-01-01"}, now="2024-06-01") is True
    assert is_deprecated_past_observation({"deprecated_since": "2024-06-01"}, now="2024-06-01") is False
    assert is_deprecated_past_observation({}) is False


def test_index_and_responses_by_status() -> None:
    items = [_item(iid="a"), _item(iid="b")]
    assert set(index_interactions({"interactions": items})) == {"a", "b"}
    resp = responses_by_status(_item(responses=[_r200({"x": {"type": "int"}})]))
    assert 200 in resp and resp[200]["status"] == 200


def test_norm_fields_flags_required() -> None:
    fields = norm_fields({"x": {"type": "int"}, "y": {"type": "str", "required": True}})
    assert fields["x"]["required"] is False
    assert fields["y"]["required"] is True


def test_all_problem_types_are_classified() -> None:
    """每个 diff 类型都必须被归类为破坏性或兼容，不允许漏分。"""
    from diff import diff_interaction as _di

    samples = [
        _di(_item(), _item(method="POST")),
        _di(_item(responses=[_r200({"x": {"type": "int"}})]), _item(responses=[_r200({})])),
    ]
    for problems in samples:
        for p in problems:
            assert p["type"] in BREAKING_TYPES or p["type"] in COMPAT_TYPES, p


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))