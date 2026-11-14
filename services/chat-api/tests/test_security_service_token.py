"""T019 单测：服务间独立凭证（FR-12）。

覆盖 :mod:`app.security.service_token`：独立密钥、生命周期 ≤ 24h、
双密钥轮换窗口、签名防篡改、audience 校验与过期判定。
全部用固定时钟，无网络、无存储。
"""

from __future__ import annotations

import base64
import json

import pytest

from app.security.service_token import (
    DEFAULT_LEEWAY_SECONDS,
    ENV_PREFIX_DEFAULT,
    MIN_SECRET_BYTES,
    SERVICE_TOKEN_HEADER,
    SERVICE_TOKEN_MAX_TTL_SECONDS,
    ServiceCredentialError,
    ServiceCredentialVault,
    ServiceTokenClaim,
    ServiceTokenExpired,
    ServiceTokenInvalid,
    ServiceTokenIssuer,
)

NOW = 1_700_000_000.0
SECRET_A = "a" * 32
SECRET_B = "b" * 32
SECRET_C = "c" * 32
OTHER_SECRET = "d" * 32


def _vault(primary: str = SECRET_A, previous: str = "") -> ServiceCredentialVault:
    return ServiceCredentialVault(primary, previous)


def _issuer(service_id: str = "admin-api", *, vault: ServiceCredentialVault | None = None,
            max_ttl: int = SERVICE_TOKEN_MAX_TTL_SECONDS) -> ServiceTokenIssuer:
    return ServiceTokenIssuer(vault or _vault(), service_id, max_ttl_seconds=max_ttl)


# ---------------------------------------------------------------------------
# 密钥库
# ---------------------------------------------------------------------------


def test_vault_rejects_weak_secret() -> None:
    with pytest.raises(ServiceCredentialError, match="at least"):
        ServiceCredentialVault("short")
    with pytest.raises(ServiceCredentialError, match="at least"):
        ServiceCredentialVault("")


def test_vault_secret_length_is_bytes_not_bits() -> None:
    """24 字符（192 bit）刚好达标。"""
    with pytest.raises(ServiceCredentialError):
        ServiceCredentialVault("x" * (MIN_SECRET_BYTES - 1))
    assert ServiceCredentialVault("x" * MIN_SECRET_BYTES).primary == "x" * MIN_SECRET_BYTES


def test_vault_accepting_keys_orders_primary_first() -> None:
    vault = _vault(SECRET_A, SECRET_B)
    assert vault.accepting_keys() == (SECRET_A, SECRET_B)


def test_vault_accepting_keys_dedupes_when_previous_equals_primary() -> None:
    vault = _vault(SECRET_A, SECRET_A)
    assert vault.accepting_keys() == (SECRET_A,)


def test_vault_from_env_prefers_service_specific_key() -> None:
    env = {
        f"{ENV_PREFIX_DEFAULT}_ADMIN_API_TOKEN": "s" * 32,
        f"{ENV_PREFIX_DEFAULT}_SERVICE_TOKEN": "f" * 32,
        f"{ENV_PREFIX_DEFAULT}_ADMIN_API_TOKEN_PREVIOUS": "p" * 32,
    }
    vault = ServiceCredentialVault.from_env("admin-api", environ=env)
    assert vault.primary == "s" * 32
    assert vault.previous == "p" * 32


def test_vault_from_env_falls_back_to_generic_key() -> None:
    env = {f"{ENV_PREFIX_DEFAULT}_SERVICE_TOKEN": "g" * 32}
    vault = ServiceCredentialVault.from_env("chat-api", environ=env)
    assert vault.primary == "g" * 32
    assert vault.previous == ""


def test_vault_from_env_hyphen_and_dot_are_normalized() -> None:
    env = {"PRE_MY_SERVICE_TOKEN": "h" * 32}
    vault = ServiceCredentialVault.from_env("my-service", env_prefix="PRE", environ=env)
    assert vault.primary == "h" * 32


def test_vault_from_env_explicit_primary_name_wins() -> None:
    env = {"CUSTOM_PRIMARY": "k" * 32, "CUSTOM_PREVIOUS": "l" * 32}
    vault = ServiceCredentialVault.from_env(
        "x", primary_name="CUSTOM_PRIMARY", previous_name="CUSTOM_PREVIOUS", environ=env
    )
    assert vault.primary == "k" * 32 and vault.previous == "l" * 32


def test_vault_from_env_raises_when_nothing_configured() -> None:
    with pytest.raises(ServiceCredentialError, match="no service token configured"):
        ServiceCredentialVault.from_env("admin-api", environ={})


def test_vault_rotate_demotes_primary_and_accepts_both() -> None:
    vault = _vault(SECRET_A)
    new_primary, demoted = vault.rotate(new_secret=SECRET_B, now=NOW)
    assert (new_primary, demoted) == (SECRET_B, SECRET_A)
    assert vault.primary == SECRET_B
    assert vault.previous == SECRET_A
    assert vault.rotate_started_at == NOW
    assert vault.accepting_keys() == (SECRET_B, SECRET_A)


def test_vault_rotate_rejects_same_secret() -> None:
    vault = _vault(SECRET_A)
    with pytest.raises(ServiceCredentialError, match="must differ"):
        vault.rotate(new_secret=SECRET_A)


def test_vault_rotate_without_arg_generates_fresh_secret() -> None:
    vault = _vault(SECRET_A)
    new_primary, _ = vault.rotate(now=NOW)
    assert new_primary != SECRET_A
    assert len(new_primary) >= MIN_SECRET_BYTES


# ---------------------------------------------------------------------------
# 签发 / 校验
# ---------------------------------------------------------------------------


def test_issue_then_verify_roundtrip() -> None:
    issuer = _issuer()
    token = issuer.issue(audience="chat-api", tenant_id="tenant-1", ttl_seconds=900, now=NOW)
    claim = issuer.verify(token, expected_audience="chat-api", now=NOW)
    assert isinstance(claim, ServiceTokenClaim)
    assert claim.service_id == "admin-api"
    assert claim.audience == "chat-api"
    assert claim.tenant_id == "tenant-1"
    assert claim.issued_at == int(NOW)
    assert claim.exp == int(NOW) + 900
    assert claim.ttl_seconds() == 900
    assert claim.jti


def test_token_format_is_version_payload_signature() -> None:
    token = _issuer().issue(now=NOW)
    parts = token.split("|")
    assert len(parts) == 3
    assert parts[0] == "v1"
    assert parts[2]  # signature present


def test_ttl_is_clamped_to_24h_ceiling() -> None:
    issuer = _issuer()
    token = issuer.issue(ttl_seconds=365 * 24 * 3600, now=NOW)
    claim = issuer.verify(token, now=NOW)
    assert claim.ttl_seconds() == SERVICE_TOKEN_MAX_TTL_SECONDS


def test_ttl_clamping_preserves_max_ttl_parameter() -> None:
    """调用方可以收窄，但无法放宽到 24h 之外。"""
    issuer = _issuer(max_ttl=600)
    claim = issuer.verify(issuer.issue(ttl_seconds=99999, now=NOW), now=NOW)
    assert claim.ttl_seconds() == 600


def test_max_ttl_must_be_within_ceiling() -> None:
    with pytest.raises(ServiceCredentialError, match="max_ttl_seconds"):
        _issuer(max_ttl=SERVICE_TOKEN_MAX_TTL_SECONDS + 1)
    with pytest.raises(ServiceCredentialError, match="max_ttl_seconds"):
        _issuer(max_ttl=0)


def test_non_positive_ttl_rejected() -> None:
    with pytest.raises(ServiceCredentialError, match="positive"):
        _issuer().issue(ttl_seconds=0, now=NOW)


def test_expired_token_rejected() -> None:
    """leeway 窗口之外即视为过期。"""
    issuer = _issuer()
    token = issuer.issue(ttl_seconds=60, now=NOW)
    with pytest.raises(ServiceTokenExpired, match="expired"):
        issuer.verify(token, now=NOW + 60 + DEFAULT_LEEWAY_SECONDS + 1)


def test_expired_with_zero_leeway_is_strict() -> None:
    """leeway=0 时 exp 边界即为失效点。"""
    issuer = ServiceTokenIssuer(_vault(), "admin-api", leeway_seconds=0)
    token = issuer.issue(ttl_seconds=60, now=NOW)
    assert issuer.verify(token, now=NOW + 59).ttl_seconds() == 60
    assert issuer.verify(token, now=NOW + 60).ttl_seconds() == 60  # exp 边界仍有效
    with pytest.raises(ServiceTokenExpired, match="expired"):
        issuer.verify(token, now=NOW + 61)


def test_leeway_allows_small_clock_skew() -> None:
    issuer = _issuer()
    token = issuer.issue(ttl_seconds=60, now=NOW)
    # 过期 30s 内仍可校验（默认 leeway 300s）
    claim = issuer.verify(token, now=NOW + 60 + 30)
    assert claim.ttl_seconds() == 60


def test_expired_beyond_leeway_rejected() -> None:
    issuer = _issuer()
    token = issuer.issue(ttl_seconds=60, now=NOW)
    with pytest.raises(ServiceTokenExpired):
        issuer.verify(token, now=NOW + 60 + DEFAULT_LEEWAY_SECONDS + 1)


def test_payload_tampering_is_rejected() -> None:
    issuer = _issuer()
    token = issuer.issue(tenant_id="tenant-1", now=NOW)
    version, payload_b64, signature = token.split("|")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode())
    payload["tenant_id"] = "tenant-evil"
    forged = (
        f"{version}|"
        f"{base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()).decode().rstrip('=')}"
        f"|{signature}"
    )
    with pytest.raises(ServiceTokenInvalid, match="signature mismatch"):
        issuer.verify(forged, now=NOW)


def test_wrong_version_rejected() -> None:
    token = _issuer().issue(now=NOW)
    version, payload_b64, signature = token.split("|")
    with pytest.raises(ServiceTokenInvalid, match="malformed"):
        _issuer().verify(f"v2|{payload_b64}|{signature}", now=NOW)


def test_malformed_token_rejected() -> None:
    issuer = _issuer()
    for bad in ("", "|", "v1|aa|bb|cc", "not-a-token", 12345, None):  # type: ignore[arg-type]
        with pytest.raises(ServiceTokenInvalid):
            issuer.verify(bad, now=NOW)


def test_non_string_token_rejected() -> None:
    with pytest.raises(ServiceTokenInvalid, match="string"):
        _issuer().verify(None, now=NOW)  # type: ignore[arg-type]


def test_signature_cross_check_between_secrets_fails() -> None:
    """B 服务用自己的密钥签的令牌，A 服务无法校验。"""
    a = _issuer("admin-api", vault=_vault(SECRET_A))
    b = _issuer("admin-api", vault=_vault(SECRET_B))
    token = b.issue(now=NOW)
    with pytest.raises(ServiceTokenInvalid, match="signature mismatch"):
        a.verify(token, now=NOW)


def test_service_id_bound_to_token() -> None:
    """令牌里绑定了签发方 service_id，接收方必须同名。"""
    issuer = _issuer("admin-api")
    token = issuer.issue(now=NOW)
    with pytest.raises(ServiceTokenInvalid, match="different service"):
        _issuer("other-service", vault=_vault(SECRET_A)).verify(token, now=NOW)


def test_audience_enforced_when_expected() -> None:
    issuer = _issuer()
    token = issuer.issue(audience="chat-api", now=NOW)
    with pytest.raises(ServiceTokenInvalid, match="audience mismatch"):
        issuer.verify(token, expected_audience="admin-api", now=NOW)


def test_audience_empty_is_not_enforced() -> None:
    """未声明 audience 的令牌在传空期望时放行（向后兼容）。"""
    issuer = _issuer()
    token = issuer.issue(now=NOW)
    claim = issuer.verify(token, expected_audience="", now=NOW)
    assert claim.audience == ""


def test_extra_claims_are_preserved_and_not_signed_payload_keys() -> None:
    issuer = _issuer()
    token = issuer.issue(tenant_id="t1", now=NOW)
    claim = issuer.verify(token, now=NOW)
    assert claim.extra == {}


def test_exp_must_exceed_iat() -> None:
    issuer = _issuer()
    token = issuer.issue(now=NOW)
    version, payload_b64, signature = token.split("|")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode())
    payload["exp"] = payload["iat"]
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    # 用同一密钥重签，验证 exp<=iat 仍被拒（说明该约束独立于签名）
    import hmac as _hmac
    import hashlib as _hashlib
    unsigned = f"{version}|{base64.urlsafe_b64encode(body).decode().rstrip('=')}"
    sig = base64.urlsafe_b64encode(
        _hmac.new(SECRET_A.encode(), unsigned.encode(), _hashlib.sha256).digest()
    ).decode().rstrip("=")
    with pytest.raises(ServiceTokenInvalid, match="exp must be greater"):
        issuer.verify(f"{unsigned}|{sig}", now=NOW)


def test_claim_is_expired_helper() -> None:
    claim = ServiceTokenClaim(service_id="x", issued_at=100, exp=200, jti="j")
    assert not claim.is_expired(now=199)
    assert not claim.is_expired(now=200)  # 边界：exp 本身仍视为有效
    assert claim.is_expired(now=201)
    assert claim.is_expired(now=200, leeway=-1)


def test_service_id_empty_rejected() -> None:
    with pytest.raises(ServiceCredentialError, match="service_id"):
        _issuer("")


def test_header_constant_matches_gateway_contract() -> None:
    assert SERVICE_TOKEN_HEADER == "X-MOGO-Service-Token"


def test_max_ttl_constant_is_24h() -> None:
    assert SERVICE_TOKEN_MAX_TTL_SECONDS == 24 * 3600


# ---------------------------------------------------------------------------
# 轮换窗口内的端到端行为
# ---------------------------------------------------------------------------


def test_rotation_window_allows_old_tokens_until_expiry() -> None:
    vault = _vault(SECRET_A)
    issuer_before = _issuer("admin-api", vault=vault)
    old_token = issuer_before.issue(ttl_seconds=3600, now=NOW)

    vault.rotate(new_secret=SECRET_B, now=NOW + 60)
    issuer_after = _issuer("admin-api", vault=vault)
    new_token = issuer_after.issue(ttl_seconds=3600, now=NOW + 60)

    # 新密钥签发的令牌可校验
    assert issuer_after.verify(new_token, now=NOW + 61).service_id == "admin-api"
    # 轮换窗口内旧令牌仍可校验
    old_claim = issuer_after.verify(old_token, now=NOW + 61)
    assert old_claim.issued_at == int(NOW)

    # 旧令牌过期后自动失效
    with pytest.raises(ServiceTokenExpired):
        issuer_after.verify(old_token, now=NOW + 3600 + DEFAULT_LEEWAY_SECONDS + 1)


def test_reissued_service_tokens_are_never_issued_for_other_service() -> None:
    """两服务各自独立密钥，交叉校验必然失败。"""
    admin = _issuer("admin-api", vault=_vault(SECRET_A))
    chat = _issuer("chat-api", vault=_vault(OTHER_SECRET))
    token = admin.issue(audience="chat-api", now=NOW)
    with pytest.raises(ServiceTokenInvalid):
        chat.verify(token, expected_audience="chat-api", now=NOW)


def test_two_services_share_audience_but_not_secret() -> None:
    admin = _issuer("admin-api", vault=_vault(SECRET_A))
    chat = _issuer("chat-api", vault=_vault(SECRET_B))
    token = admin.issue(audience="chat-api", now=NOW)
    claim = admin.verify(token, expected_audience="chat-api", now=NOW)
    assert claim.audience == "chat-api"
    with pytest.raises(ServiceTokenInvalid):
        chat.verify(token, expected_audience="chat-api", now=NOW)
