"""FR-20 / FR-21 (QF-659–666) 日志脱敏与响应裁剪测试."""

from __future__ import annotations

import pytest

from app.security import redaction as rd


# ---------------------------------------------------------------------------
# 键名判定
# ---------------------------------------------------------------------------


def test_is_sensitive_key_matches_common_variants():
    for name in (
        "password",
        "passwd",
        "pwd",
        "newPassword",
        "TOKEN",
        "access_token",
        "api-key",
        "API_KEY",
        "client_secret",
        "Authorization",
        "sso_token",
        "mfa_secret",
        "client_secret_x",
        "refreshToken",
        "privateKey",
        "session_id",
        "credential",
    ):
        assert rd.is_sensitive_key(name), f"{name!r} should be sensitive"


def test_is_sensitive_key_accepts_non_sensitive_names():
    for name in (
        "user_id",
        "username",
        "tenant_id",
        "display_name",
        "role",
        "created_at",
        "count",
        "status",
    ):
        assert not rd.is_sensitive_key(name), f"{name!r} should be non-sensitive"


def test_substring_matching_is_deliberately_conservative():
    # 键名按子串匹配 → 会连带命中 password_policy_enabled 这类非凭据字段。
    # 这是有意的取舍：mask 一个布尔开关无害，漏脱一个真实口令是安全事故。
    assert rd.is_sensitive_key("password_policy_enabled")
    # 确需保留时显式配置豁免
    cfg = rd.RedactionConfig(exempt_keys=("password_policy_enabled",))
    assert rd.is_sensitive_key("password_policy_enabled", cfg) is False


def test_redact_masks_the_credentials_container_key_itself():
    # `credentials` 命中 credential 模式 → 整个容器被 mask（保守策略）
    out = rd.redact({"credentials": {"password": "x"}, "role": "admin"})
    assert out == {"credentials": rd.MASK, "role": "admin"}


def test_non_string_and_empty_keys_are_not_sensitive():
    assert rd.is_sensitive_key(None) is False
    assert rd.is_sensitive_key("") is False
    assert rd.is_sensitive_key(12345) is False


def test_extra_sensitive_keys_and_exemptions():
    cfg = rd.RedactionConfig(extra_sensitive_keys=("internal_note",), exempt_keys=("token_count",))
    assert rd.is_sensitive_key("internal_note", cfg)
    assert rd.is_sensitive_key("token_count", cfg) is False
    assert rd.is_sensitive_key("token_count", rd.DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# 递归脱敏（dict / list / tuple / 深度）
# ---------------------------------------------------------------------------


def test_redact_masks_sensitive_dict_values():
    out = rd.redact({"username": "alice", "password": "hunter2", "role": "admin"})
    assert out == {"username": "alice", "password": rd.MASK, "role": "admin"}


def test_redact_remove_mode_drops_keys():
    out = rd.redact({"password": "x", "role": "admin"}, config=rd.RedactionConfig(mode=rd.MODE_REMOVE))
    assert out == {"role": "admin"}


def test_redact_is_recursive():
    payload = {
        "user": {
            "username": "alice",
            "auth_info": {"password": "secret", "token": "tok-1"},
            "tags": ["a", {"api_key": "k-1"}],
            "meta": {"nested": {"token": "tok-2"}},
        }
    }
    out = rd.redact(payload)
    assert out["user"]["auth_info"] == {"password": rd.MASK, "token": rd.MASK}
    assert out["user"]["tags"][1]["api_key"] == rd.MASK
    assert out["user"]["meta"]["nested"]["token"] == rd.MASK
    assert out["user"]["username"] == "alice"


def test_redact_masks_scalar_sensitive_values_in_dicts_only():
    # 标量本身不做内容级脱敏（避免误伤），只在键名层面处理
    out = rd.redact({"note": "the password is hunter2"})
    assert out == {"note": "the password is hunter2"}


def test_redact_masks_deeply_nested_payloads():
    deep = {"a": {"b": {"c": {"d": {"token": "deep"}}}}}
    out = rd.redact(deep)
    assert out["a"]["b"]["c"]["d"]["token"] == rd.MASK


def test_redact_applies_depth_limit():
    deep = {"a": {"b": {"c": {"d": {"e": {"token": "deep"}}}}}}
    out = rd.redact(deep, config=rd.RedactionConfig(max_depth=3))
    # 超过深度上限的子树被整体 mask
    assert out["a"]["b"]["c"] == {"d": rd.MASK}


def test_redact_config_validation():
    with pytest.raises(rd.RedactionError):
        rd.RedactionConfig(mode="explode")
    with pytest.raises(rd.RedactionError):
        rd.RedactionConfig(max_depth=0)
    with pytest.raises(rd.RedactionError):
        rd.RedactionConfig(mask="")


def test_redact_mapping_keyword_form():
    out = rd.redact_mapping({"password": "x", "ok": 1}, mode=rd.MODE_REMOVE)
    assert out == {"ok": 1}


def test_redact_json_serializes_after_masking():
    payload = {"username": "alice", "password": "hunter2"}
    text = rd.redact_json(payload)
    assert rd.MASK in text
    assert "hunter2" not in text


# ---------------------------------------------------------------------------
# 文本脱敏（已拼接的日志行 / 错误消息）
# ---------------------------------------------------------------------------


def test_redact_text_masks_json_style_pairs():
    text = '{"username": "alice", "password": "hunter2"}'
    out = rd.redact_text(text)
    assert "hunter2" not in out
    assert rd.MASK in out


def test_redact_text_masks_key_value_pairs():
    text = "login failed for user=alice password=hunter2 role=admin"
    out = rd.redact_text(text)
    assert "hunter2" not in out
    assert rd.MASK in out


def test_redact_text_masks_bearer_tokens_in_authorization_header():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig-part"
    out = rd.redact_text(f"Authorization: Bearer {jwt}")
    assert jwt not in out
    assert rd.MASK in out
    # 整个 header 值（含 Bearer scheme）被 mask
    assert out.strip().endswith(rd.MASK)


def test_redact_text_masks_bare_bearer_tokens():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig-part"
    out = rd.redact_text(f"retry with Bearer {jwt}")
    assert jwt not in out
    assert f"Bearer {rd.MASK}" in out


def test_redact_text_masks_basic_auth_header():
    out = rd.redact_text("Authorization: Basic dXNlcjpwYXNz")
    assert "dXNlcjpwYXNz" not in out
    assert rd.MASK in out


def test_redact_text_masks_url_query_tokens():
    text = "GET /sso/callback?sso_token=abc123&tenant_id=t1"
    out = rd.redact_text(text)
    assert "abc123" not in out
    assert "sso_token=***REDACTED***" in out
    assert "tenant_id=t1" in out


def test_redact_text_handles_quoted_values():
    text = "POST /login body: {'password': 'p@ss-123'}"
    out = rd.redact_text(text)
    assert "p@ss-123" not in out


def test_redact_text_is_idempotent():
    text = "password=hunter2 token=tok-1"
    once = rd.redact_text(text)
    twice = rd.redact_text(once)
    assert once == twice


def test_redact_text_passes_through_non_sensitive_input():
    text = "login succeeded for user=alice role=admin tenant_id=t1"
    assert rd.redact_text(text) == text


def test_redact_text_handles_empty_and_non_string():
    assert rd.redact_text("") == ""
    assert rd.redact_text(None) is None  # type: ignore[arg-type]
    assert rd.redact_text(12345) == 12345  # type: ignore[arg-type]


def test_redact_text_supports_extra_sensitive_keys():
    out = rd.redact_text("internal_note=some-note", extra_sensitive_keys=("internal_note",))
    assert "some-note" not in out


# ---------------------------------------------------------------------------
# 响应裁剪（FR-21）
# ---------------------------------------------------------------------------


def test_filter_response_keeps_only_allowed_fields():
    payload = {"id": 1, "name": "alice", "email": "a@b.c", "password_hash": "h", "role": "admin"}
    out = rd.filter_response(payload, {"id", "name", "role"})
    assert out == {"id": 1, "name": "alice", "role": "admin"}


def test_filter_response_without_allowlist_returns_payload_unchanged():
    payload = {"id": 1, "name": "alice"}
    assert rd.filter_response(payload, None) == payload
    assert rd.filter_response(payload, set()) == payload


def test_filter_response_deny_all_without_allowlist_returns_empty():
    assert rd.filter_response({"id": 1, "name": "alice"}, None, deny_all=True) == {}


def test_filter_response_is_shallow():
    payload = {"id": 1, "profile": {"secret": "x"}}
    out = rd.filter_response(payload, {"id", "profile"})
    # 裁剪是浅层的：保留下来的嵌套结构不动（由 redact 负责其内部敏感值）
    assert out == payload


def test_filter_response_ignores_non_dict_payload():
    assert rd.filter_response(["a", "b"], {"a"}) == ["a", "b"]
    assert rd.filter_response("text", {"a"}) == "text"


def test_redact_response_combines_trimming_and_masking():
    payload = {"id": 1, "password": "hunter2", "role": "admin"}
    out = rd.redact_response(payload, {"id", "password", "role"})
    assert out == {"id": 1, "password": rd.MASK, "role": "admin"}


# ---------------------------------------------------------------------------
# 断言与审计报告
# ---------------------------------------------------------------------------


def test_assert_no_sensitive_passes_for_clean_output():
    rd.assert_no_sensitive({"username": "alice", "role": "admin"})
    rd.assert_no_sensitive("login ok for alice")


def test_assert_no_sensitive_fails_on_sensitive_key():
    with pytest.raises(AssertionError):
        rd.assert_no_sensitive({"username": "alice", "password": "x"})


def test_assert_no_sensitive_fails_on_known_secret_value():
    with pytest.raises(AssertionError):
        rd.assert_no_sensitive("the value is hunter2", known_secrets=("hunter2",))


def test_leak_report_lists_sensitive_paths():
    payload = {
        "user": {"username": "alice", "password": "x"},
        "items": [{"token": "t"}],
        "ok": 1,
    }
    report = rd.leak_report(payload)
    assert report["count"] == 2
    assert "user.password" in report["sensitive_keys"]
    assert "items[0].token" in report["sensitive_keys"]
    assert "user.username" not in report["sensitive_keys"]


def test_leak_report_respects_depth_limit():
    deep = {"a": {"b": {"c": {"token": "x"}}}}
    assert rd.leak_report(deep, config=rd.RedactionConfig(max_depth=2))["count"] == 0


def test_constants():
    assert rd.MASK == "***REDACTED***"
    assert rd.SUPPORTED_MODES == (rd.MODE_MASK, rd.MODE_REMOVE)
    assert rd.DEFAULT_CONFIG.mode == rd.MODE_MASK
    assert len(rd.SENSITIVE_KEY_PATTERNS) >= 10
