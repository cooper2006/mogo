"""T038 序列化一致性检查工具测试（FR-23）。"""

from __future__ import annotations

import yaml

from tools.contract.serialization_check import (
    check_contract,
    collect_camel,
    is_snake,
    iter_response_fields,
    load_known,
    main,
    seed,
)


# ---------- is_snake ----------


def test_snake_names() -> None:
    assert is_snake("id")
    assert is_snake("tenant_id")
    assert is_snake("a_b_c_d")
    assert is_snake("x2y3")


def test_non_snake_names() -> None:
    assert not is_snake("tenantId")
    assert not is_snake("Tenant_id")
    assert not is_snake("_tenant_id")
    assert not is_snake("tenant_id_")
    assert not is_snake("tenant__id")
    assert not is_snake("1tenant_id")
    assert not is_snake("display-name")
    assert not is_snake("data[].id")  # 容器前缀，不属 snake_case 字段名


# ---------- iter_response_fields ----------


def test_iter_response_fields_nested() -> None:
    item = {
        "responses": [
            {
                "status": 200,
                "fields": {
                    "tenant_id": {"type": "str"},
                    "profile": {
                        "type": "obj",
                        "fields": {"org_name": {"type": "str"}, "displayName": {"type": "str"}},
                    },
                },
            },
            {"status": 400, "fields": {"error_code": {"type": "str"}}},
        ]
    }
    got = [(n, st) for n, _m, st in iter_response_fields(item)]
    assert got == [
        ("tenant_id", 200),
        ("profile", 200),
        ("org_name", 200),
        ("displayName", 200),
        ("error_code", 400),
    ]


# ---------- collect_camel ----------


def test_collect_camel_counts() -> None:
    contract = {
        "interactions": [
            {
                "id": "a",
                "responses": [
                    {
                        "status": 200,
                        "fields": {"ok": {"type": "bool"}, "updatedAt": {"type": "str"}},
                    }
                ],
            },
            {
                "id": "b",
                "responses": [
                    {"status": 200, "fields": {"updatedAt": {"type": "str"}, "id": {"type": "str"}}}
                ],
            },
        ]
    }
    camel = collect_camel(contract)
    assert camel == {"a": {"updatedAt": 1}, "b": {"updatedAt": 1}}


# ---------- check_contract ----------


def _contract_with_fields(fields: dict) -> dict:
    return {
        "name": "demo",
        "version": "1.0.0",
        "provider": "demo",
        "consumers": ["web"],
        "base_path": "/api",
        "interactions": [
            {
                "id": "only_one",
                "method": "GET",
                "path": "/things",
                "responses": [{"status": 200, "fields": fields}],
            }
        ],
    }


def test_all_snake_ok() -> None:
    ok, report = check_contract(_contract_with_fields({"id": {}, "tenant_id": {}}), "demo", {})
    assert ok
    assert not any("[error]" in r for r in report)
    assert any("snake_case 覆盖率 2/2 = 100.0%" in r for r in report)


def test_unregistered_camel_is_error() -> None:
    ok, report = check_contract(_contract_with_fields({"tenantId": {}}), "demo", {})
    assert not ok
    assert any("[error] only_one.tenantId" in r for r in report)


def test_unregistered_camel_is_warn_when_not_strict() -> None:
    ok, report = check_contract(_contract_with_fields({"tenantId": {}}), "demo", {}, strict=False)
    assert ok
    assert not any("[error]" in r for r in report)


def test_registered_camel_is_info() -> None:
    known = {"demo": {"only_one": {"tenantId"}}}
    ok, report = check_contract(_contract_with_fields({"tenantId": {}}), "demo", known)
    assert ok
    assert any("已在 FR-23 白名单登记" in r for r in report)


# ---------- seed / load_known ----------


def test_seed_writes_file(tmp_path) -> None:
    out = tmp_path / "known.yaml"
    affected, path = seed(output_path=out)
    assert path == out
    assert out.exists()
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    # 三份契约均已登记
    assert set(data) >= {"admin-api", "chat-api", "document-parser"}
    assert affected > 0


def test_load_known_missing_file_is_empty(tmp_path) -> None:
    assert load_known(tmp_path / "nope.yaml") == {}


# ---------- CLI ----------


def test_main_all_real_contracts_ok() -> None:
    assert main(["--all"]) == 0


def test_main_service_ok() -> None:
    for svc in ["admin-api", "chat-api", "document-parser"]:
        assert main(["--service", svc]) == 0


def test_main_seed_ok() -> None:
    assert main(["--seed"]) == 0
