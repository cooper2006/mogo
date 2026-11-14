"""T033 契约验证脚本的行为测试（纯逻辑，不依赖网络/数据库）。

用注入的注册表与临时契约目录验证 `check_structure` / `validate_contract` 的判定规则，
锁定 FR-16/FR-17/FR-18 的契约规则不会被后续改动破坏。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from contract.validate import (  # noqa: E402
    FIELD_TYPES,
    REQUIRED_ITEM_KEYS,
    REQUIRED_TOP_KEYS,
    check_structure,
    load_registry,
    validate_contract,
)

SERVICE = "admin-api"
REG = {SERVICE: {"api.not_found", "api.unauthorized", "api.validation_error"}}


def _base(data: dict | None = None) -> dict:
    payload = {
        "name": "admin-api",
        "version": "1.0.0",
        "provider": "admin-api",
        "consumers": ["admin-web"],
        "base_path": "/api",
        "interactions": [
            {
                "id": "get_thing",
                "method": "GET",
                "path": "/things",
                "responses": [
                    {
                        "status": 200,
                        "fields": {"data": {"type": "object"}, "total": {"type": "int"}},
                    }
                ],
            }
        ],
    }
    if data:
        payload.update(data)
    return payload


def test_valid_contract_passes() -> None:
    assert check_structure(_base(), SERVICE, REG) == []


@pytest.mark.parametrize("key", list(REQUIRED_TOP_KEYS))
def test_missing_top_key_reports(key: str) -> None:
    data = _base()
    del data[key]
    errors = check_structure(data, SERVICE, REG)
    assert any(f"缺少顶层键 {key!r}" in err for err in errors)


def test_missing_consumers_reports() -> None:
    data = _base()
    data["consumers"] = []
    errors = check_structure(data, SERVICE, REG)
    assert any("consumers 必须是非空数组" in err for err in errors)


@pytest.mark.parametrize("key", list(REQUIRED_ITEM_KEYS))
def test_missing_item_key_reports(key: str) -> None:
    data = _base()
    del data["interactions"][0][key]
    errors = check_structure(data, SERVICE, REG)
    assert any(f"缺少 {key!r}" in err for err in errors)


def test_duplicate_interaction_id_reports() -> None:
    data = _base()
    data["interactions"].append(
        {"id": "get_thing", "method": "GET", "path": "/other", "responses": []}
    )
    errors = check_structure(data, SERVICE, REG)
    assert any("重复" in err and "FR-17" in err for err in errors)


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS", "PUT"])
def test_valid_methods_accepted(method: str) -> None:
    data = _base()
    data["interactions"][0]["method"] = method
    data["interactions"][0]["responses"] = [{"status": 200, "fields": {"ok": {"type": "bool"}}}]
    assert check_structure(data, SERVICE, REG) == []


def test_invalid_method_reports() -> None:
    data = _base()
    data["interactions"][0]["method"] = "FETCH"
    errors = check_structure(data, SERVICE, REG)
    assert any("不在" in err for err in errors)


def test_path_must_start_with_slash() -> None:
    data = _base()
    data["interactions"][0]["path"] = "things"
    errors = check_structure(data, SERVICE, REG)
    assert any("必须以 / 开头" in err for err in errors)


def test_path_double_slash_reports() -> None:
    data = _base()
    data["interactions"][0]["path"] = "/things//detail"
    errors = check_structure(data, SERVICE, REG)
    assert any("空段" in err for err in errors)


def test_unknown_error_code_reports() -> None:
    data = _base()
    data["interactions"][0]["responses"] = [
        {"status": 400, "error_codes": ["api.nope"], "fields": {}}
    ]
    errors = check_structure(data, SERVICE, REG)
    assert any("不在 admin-api 注册表" in err for err in errors)


def test_registered_error_code_passes() -> None:
    data = _base()
    data["interactions"][0]["responses"] = [
        {"status": 400, "error_codes": ["api.validation_error"], "fields": {}}
    ]
    assert check_structure(data, SERVICE, REG) == []


def test_non_2xx_requires_error_codes() -> None:
    data = _base()
    data["interactions"][0]["responses"] = [{"status": 500, "fields": {}}]
    errors = check_structure(data, SERVICE, REG)
    assert any("非 2xx 响应应声明 error_codes" in err for err in errors)


@pytest.mark.parametrize("status", [200, 201, 204])
def test_2xx_may_omit_error_codes(status: int) -> None:
    data = _base()
    data["interactions"][0]["responses"] = [{"status": status, "fields": {}}]
    assert check_structure(data, SERVICE, REG) == []


def test_invalid_field_type_reports() -> None:
    data = _base()
    data["interactions"][0]["responses"] = [
        {"status": 200, "fields": {"total": {"type": "decimal"}}}
    ]
    errors = check_structure(data, SERVICE, REG)
    assert any("不在" in err for err in errors)


@pytest.mark.parametrize("ftype", sorted(FIELD_TYPES))
def test_all_field_types_accepted(ftype: str) -> None:
    data = _base()
    data["interactions"][0]["responses"] = [{"status": 200, "fields": {"f": {"type": ftype}}}]
    assert check_structure(data, SERVICE, REG) == []


def test_non_int_status_reports() -> None:
    data = _base()
    data["interactions"][0]["responses"] = [{"status": "200", "fields": {}}]
    errors = check_structure(data, SERVICE, REG)
    assert any("status 必须是合法 HTTP 状态码" in err for err in errors)


def test_injected_registries_win_over_disk() -> None:
    # 注入的注册表优先：即使磁盘没有注册表文件也不会读文件
    assert check_structure(_base(), SERVICE, {SERVICE: {"api.bad_request"}}) == []


def test_load_registry_reads_disk(tmp_path: Path) -> None:
    registry_file = tmp_path / "services" / SERVICE / "app" / "core" / "errors.py"
    registry_file.parent.mkdir(parents=True)
    registry_file.write_text(
        'class ApiErrorCode(Enum):\n    OK = "api.ok"\n    NOPE = "api.nope"\n',
        encoding="utf-8",
    )
    monkey = pytest.MonkeyPatch()
    monkey.setattr("contract.validate.REPO", tmp_path)
    try:
        assert load_registry(SERVICE) == {"api.ok", "api.nope"}
    finally:
        monkey.undo()


def test_validate_contract_missing_file_reports(tmp_path: Path) -> None:
    monkey = pytest.MonkeyPatch()
    monkey.setattr("contract.validate.CONTRACTS_DIR", tmp_path)
    try:
        ok, errors = validate_contract(SERVICE)
    finally:
        monkey.undo()
    assert ok is False
    assert any("契约文件不存在" in err for err in errors)


def test_validate_contract_real_contracts_pass() -> None:
    """三份真实契约必须全部通过（锁定 FR-18 的准入规则）。"""
    for service in ("admin-api", "chat-api", "document-parser"):
        ok, errors = validate_contract(service)
        assert ok, f"{service} 契约校验失败: {errors}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))