"""T037 弃用观察期检查工具测试（FR-22）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.contract.deprecation_check import (
    DEFAULT_OBSERVATION_MINORS,
    bump_minor,
    check_contract,
    collect_deprecated,
    main,
    parse_version,
)


# ---------- 版本号工具 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.0.0", (1, 0, 0)),
        ("1.2.0", (1, 2, 0)),
        ("2.10.3", (2, 10, 3)),
        ("0.1", (0, 1, 0)),
    ],
)
def test_parse_version_ok(text: str, expected: tuple[int, int, int]) -> None:
    assert parse_version(text) == expected


@pytest.mark.parametrize("bad", ["", "1", "1.0.0-beta", "v1.2.3", "1.0.0.0", "abc", "1.x"])
def test_parse_version_invalid_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_version(bad)


def test_bump_minor() -> None:
    assert bump_minor("1.0.0", 2) == "1.2.0"
    assert bump_minor("1.1.0", 2) == "1.3.0"
    assert bump_minor("1.2.3", 2) == "1.4.0"  # patch 归零


def test_bump_minor_rolls_major() -> None:
    # 9.9 + 2 minor → 10.1
    assert bump_minor("9.9.0", 2) == "10.1.0"


def test_default_observation_minors_is_two() -> None:
    assert DEFAULT_OBSERVATION_MINORS == 2


# ---------- 收集 deprecated ----------


def _contract(version: str = "1.0.0") -> dict:
    return {
        "name": "demo",
        "version": version,
        "provider": "demo",
        "consumers": ["web"],
        "base_path": "/api",
        "interactions": [
            {
                "id": "normal",
                "method": "GET",
                "path": "/normal",
                "responses": [{"status": 200, "fields": {"id": {"type": "str"}}}],
            },
            {
                "id": "legacy",
                "method": "POST",
                "path": "/legacy",
                "deprecated": True,
                "deprecated_since": "0.9.0",
                "responses": [
                    {
                        "status": 200,
                        "fields": {
                            "id": {"type": "str"},
                            "old_name": {"type": "str", "deprecated": True, "deprecated_since": "0.9.0"},
                        },
                    }
                ],
            },
        ],
    }


def test_collect_deprecated_finds_interaction_and_field() -> None:
    items = collect_deprecated(_contract(), "demo", "1.0.0")
    kinds = {(item.kind, item.interaction_id, item.field) for item in items}
    assert ("interaction", "legacy", "") in kinds
    assert ("field", "legacy", "old_name") in kinds
    assert len(items) == 2


def test_collect_deprecated_empty() -> None:
    assert collect_deprecated({"interactions": []}, "demo", "1.0.0") == []


# ---------- check_contract 分支 ----------


def test_no_deprecated_ok() -> None:
    ok, report = check_contract({"version": "1.0.0", "interactions": []}, "demo")
    assert ok
    assert any("无 deprecated" in line for line in report)


def test_deprecated_without_since_is_error() -> None:
    contract = _contract()
    contract["interactions"][1].pop("deprecated_since")
    ok, report = check_contract(contract, "demo")
    assert not ok
    assert any("缺少 deprecated_since" in line for line in report)


def test_field_deprecated_without_since_is_error() -> None:
    contract = _contract()
    fields = contract["interactions"][1]["responses"][0]["fields"]
    fields["old_name"].pop("deprecated_since")
    ok, report = check_contract(contract, "demo")
    assert not ok
    assert any("缺少 deprecated_since" in line for line in report)


def test_deprecated_since_in_future_is_error() -> None:
    contract = _contract(version="1.0.0")
    contract["interactions"][1]["deprecated_since"] = "1.5.0"
    ok, report = check_contract(contract, "demo")
    assert not ok
    assert any("晚于当前版本" in line for line in report)


def test_invalid_deprecated_since_is_error() -> None:
    contract = _contract()
    contract["interactions"][1]["deprecated_since"] = "not-a-version"
    ok, report = check_contract(contract, "demo")
    assert not ok
    assert any("deprecated_since 非法" in line for line in report)


def test_invalid_contract_version_is_error() -> None:
    ok, report = check_contract({"version": "bad", "interactions": []}, "demo")
    assert not ok
    assert any("version 非法" in line for line in report)


def test_observation_window_not_elapsed_is_ok() -> None:
    # deprecated_since 1.0.0，观察期 2 minor → 需 1.2.0；当前 1.1.0 仍在观察期内
    contract = _contract(version="1.1.0")
    contract["interactions"][1]["deprecated_since"] = "1.0.0"
    contract["interactions"][1]["responses"][0]["fields"]["old_name"]["deprecated_since"] = "1.0.0"
    ok, report = check_contract(contract, "demo")
    assert ok
    assert any("观察中（不可移除）" in line for line in report)


def test_observation_window_elapsed_is_ok_warn() -> None:
    # 当前 1.3.0 >= 1.2.0，已过观察期，允许移除
    contract = _contract(version="1.3.0")
    contract["interactions"][1]["deprecated_since"] = "1.0.0"
    ok, report = check_contract(contract, "demo")
    assert ok
    assert any("已过观察期（可移除）" in line for line in report)


# ---------- CLI ----------

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "specs" / "025-api-contract-hardening" / "contracts"


def test_main_all_real_contracts_pass(tmp_path) -> None:
    rc = main(["--all"])
    assert rc == 0, "三份真实契约的弃用声明应全部合规"


def test_main_service_ok() -> None:
    rc = main(["--service", "admin-api"])
    assert rc == 0


def test_main_bad_contract_exits_one(tmp_path) -> None:
    # 构造缺 deprecated_since 的坏契约
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml_text := "name: bad\nversion: \"1.0.0\"\nprovider: bad\nconsumers: [web]\n"
        "base_path: /api\ninteractions:\n"
        "  - id: x\n    method: GET\n    path: /x\n    deprecated: true\n"
        "    responses:\n      - status: 200\n        fields: {}\n",
        encoding="utf-8",
    )
    assert "deprecated: true" in yaml_text
    rc = main(["--contract", str(bad)])
    assert rc == 1


def test_main_missing_contract_file_exits_one() -> None:
    rc = main(["--contract", str(REPO / "nope.yaml")])
    assert rc == 1
