"""T020 单测：服务间调用双因子校验（FR-12）。

覆盖 :mod:`app.security.gatekeeper`：

- 新式签名令牌通过 + 双因子（service_id / tenant_id / user_id）核对；
- 未配置新式凭据时 ``verify_service_call`` 返回 ``None``（调用方回退静态）；
- 各失败路径 fail-closed。

不触库、不发 HTTP；全部内存构造。
"""

from __future__ import annotations

import time as _time_mod
from typing import Any

import pytest

from app.security import gatekeeper as gk
from app.security.service_token import (
    ServiceCredentialVault,
    ServiceTokenExpired,
    ServiceTokenInvalid,
    ServiceTokenIssuer,
    _normalize_secret,
)

NOW = 1_700_000_000.0
SECRET = "a" * 32
STRONG = "b" * 32
TENANT = "tenant-0001"
CHAT = "chat-api"
ADMIN = "admin-api"


class _FrozenTime:
    """可推进的冻结时钟（service_token 内部调用 time.time()）。"""

    def __init__(self) -> None:
        self.value = NOW

    def time(self) -> float:
        return self.value


@pytest.fixture
def frozen_clock(monkeypatch) -> _FrozenTime:
    """让所有签发/校验都相对同一基准 NOW，避免 300s leeway 与现实时钟错位。"""
    import app.security.service_token as st_module

    clock = _FrozenTime()
    monkeypatch.setattr(st_module, "time", clock)
    return clock


def _vault() -> ServiceCredentialVault:
    return ServiceCredentialVault(SECRET, previous="")


def _issuer(
    service_id: str = CHAT,
    *,
    vault: ServiceCredentialVault | None = None,
) -> ServiceTokenIssuer:
    return ServiceTokenIssuer(vault or _vault(), service_id)


# ---------------------------------------------------------------------------
# build_issuer_from_env
# ---------------------------------------------------------------------------


def test_build_issuer_from_env_builds_when_configured(monkeypatch) -> None:
    environ = {"MOGO_CHAT_API_TOKEN": SECRET}
    issuer = gk.build_issuer_from_env(CHAT, environ=environ)
    assert issuer is not None
    token = issuer.issue()
    claim = issuer.verify(token)
    assert claim.service_id == CHAT


def test_build_issuer_from_env_returns_none_when_unset(monkeypatch) -> None:
    assert gk.build_issuer_from_env(CHAT, environ={}) is None


def test_build_issuer_from_env_returns_none_on_weak_secret(monkeypatch) -> None:
    """密钥过弱（<24 字节）视为未配置，回退静态比对。"""
    assert gk.build_issuer_from_env(CHAT, environ={"MOGO_CHAT_API_TOKEN": "short"}) is None


def test_build_issuer_from_env_extra_names_fallback(monkeypatch) -> None:
    """历史命名 ADMIN_BACKEND_SERVICE_TOKEN 作为回退主密钥。"""
    environ = {"ADMIN_BACKEND_SERVICE_TOKEN": SECRET}
    issuer = gk.build_issuer_from_env(
        CHAT, environ=environ, extra_primary_names=("ADMIN_BACKEND_SERVICE_TOKEN",)
    )
    assert issuer is not None


def test_build_issuer_from_env_prefers_canonical_over_extra(monkeypatch) -> None:
    environ = {"MOGO_CHAT_API_TOKEN": SECRET, "ADMIN_BACKEND_SERVICE_TOKEN": STRONG}
    issuer = gk.build_issuer_from_env(
        CHAT, environ=environ, extra_primary_names=("ADMIN_BACKEND_SERVICE_TOKEN",)
    )
    assert issuer is not None
    # 用新式密钥签的令牌能通过验证
    claim = issuer.verify(issuer.issue())
    assert claim.service_id == CHAT


# ---------------------------------------------------------------------------
# verify_service_call：通过路径
# ---------------------------------------------------------------------------


def test_verify_passes_with_matching_service_id() -> None:
    issuer = _issuer(CHAT)
    token = issuer.issue()
    claim = gk.verify_service_call(
        token, expected_service_id=CHAT, issuer=issuer
    )
    assert claim is not None
    assert claim.service_id == CHAT


def test_verify_passes_with_matching_tenant() -> None:
    issuer = _issuer(CHAT)
    token = issuer.issue(tenant_id=TENANT)
    claim = gk.verify_service_call(
        token, expected_service_id=CHAT, tenant_id=TENANT, issuer=issuer
    )
    assert claim is not None
    assert claim.tenant_id == TENANT


def test_verify_passes_with_matching_user_id() -> None:
    issuer = _issuer(CHAT)
    token = issuer.issue(extra={"user_id": "user-1"})
    claim = gk.verify_service_call(
        token, expected_service_id=CHAT, user_id="user-1", issuer=issuer
    )
    assert claim is not None


def test_verify_passes_when_claim_tenant_is_empty() -> None:
    """令牌未携带租户（兼容既有调用方）→ 租户核对跳过。"""
    issuer = _issuer(CHAT)
    token = issuer.issue()
    claim = gk.verify_service_call(
        token, expected_service_id=CHAT, tenant_id=TENANT, issuer=issuer
    )
    assert claim is not None


def test_verify_passes_when_claim_user_is_empty() -> None:
    issuer = _issuer(CHAT)
    token = issuer.issue()
    claim = gk.verify_service_call(
        token, expected_service_id=CHAT, user_id="user-1", issuer=issuer
    )
    assert claim is not None


# ---------------------------------------------------------------------------
# verify_service_call：失败路径（fail-closed）
# ---------------------------------------------------------------------------


def test_verify_returns_none_when_issuer_not_configured() -> None:
    """未启用新式凭据 → 返回 None，调用方回退静态比对。"""
    assert (
        gk.verify_service_call(
            "whatever", expected_service_id=CHAT, issuer=None
        )
        is None
    )


def test_verify_rejects_empty_token() -> None:
    with pytest.raises(gk.GatekeeperDenied) as exc_info:
        gk.verify_service_call("", expected_service_id=CHAT, issuer=_issuer())
    assert exc_info.value.reason == "missing_service_token"


def test_verify_rejects_signature_mismatch() -> None:
    issuer = _issuer(CHAT)
    token = issuer.issue()
    other = _issuer(CHAT, vault=ServiceCredentialVault(STRONG, previous=""))
    with pytest.raises(gk.GatekeeperDenied) as exc_info:
        gk.verify_service_call(
            token, expected_service_id=CHAT, issuer=other
        )
    assert exc_info.value.reason == "invalid_service_token"


def test_verify_rejects_expired_token(frozen_clock: _FrozenTime) -> None:
    """越过 leeway 的过期令牌 → GatekeeperDenied(expired_service_token)。"""
    issuer = _issuer(CHAT)
    token = issuer.issue(ttl_seconds=1, now=NOW)
    frozen_clock.value = NOW + 2  # exp=NOW+1 已过期，且 leeway=0
    strict = ServiceTokenIssuer(_vault(), CHAT, leeway_seconds=0)
    with pytest.raises(gk.GatekeeperDenied) as exc_info:
        gk.verify_service_call(
            token, expected_service_id=CHAT, issuer=strict
        )
    assert exc_info.value.reason == "expired_service_token"


def test_verify_allows_within_leeway(frozen_clock: _FrozenTime) -> None:
    """在 leeway 窗口内的过期令牌仍可通过（网络抖动容忍）。"""
    issuer = _issuer(CHAT)
    token = issuer.issue(ttl_seconds=1, now=NOW)
    claim = gk.verify_service_call(
        token, expected_service_id=CHAT, issuer=issuer
    )
    assert claim is not None


def test_verify_rejects_service_identity_mismatch() -> None:
    """双因子 #1：chat-api 的令牌不能访问 admin-api 的身份。"""
    issuer = _issuer(CHAT)
    token = issuer.issue()
    with pytest.raises(gk.GatekeeperDenied) as exc_info:
        gk.verify_service_call(token, expected_service_id=ADMIN, issuer=issuer)
    assert exc_info.value.reason == "service_identity_mismatch"
    assert "expected=admin-api" in exc_info.value.detail


def test_verify_rejects_tenant_mismatch() -> None:
    """双因子 #2：租户 A 签发的令牌不能访问租户 B。"""
    issuer = _issuer(CHAT)
    token = issuer.issue(tenant_id="tenant-A")
    with pytest.raises(gk.GatekeeperDenied) as exc_info:
        gk.verify_service_call(
            token, expected_service_id=CHAT, tenant_id="tenant-B", issuer=issuer
        )
    assert exc_info.value.reason == "tenant_mismatch"


def test_verify_rejects_user_mismatch() -> None:
    """双因子 #3：用户绑定不一致。"""
    issuer = _issuer(CHAT)
    token = issuer.issue(extra={"user_id": "user-A"})
    with pytest.raises(gk.GatekeeperDenied) as exc_info:
        gk.verify_service_call(
            token, expected_service_id=CHAT, user_id="user-B", issuer=issuer
        )
    assert exc_info.value.reason == "user_mismatch"


def test_gatekeeper_denied_carries_reason_and_detail() -> None:
    err = gk.GatekeeperDenied("tenant_mismatch", detail="expected=A got=B")
    assert str(err) == "tenant_mismatch"
    assert err.reason == "tenant_mismatch"
    assert err.detail == "expected=A got=B"
    assert isinstance(err, PermissionError)


# ---------------------------------------------------------------------------
# bind_context_to_claim
# ---------------------------------------------------------------------------


def test_bind_context_backfills_tenant_and_user() -> None:
    issuer = _issuer(CHAT)
    claim = issuer.verify(issuer.issue())
    bound = gk.bind_context_to_claim(claim, tenant_id=TENANT, user_id="user-1")
    assert bound.tenant_id == TENANT
    assert bound.extra["user_id"] == "user-1"
    assert bound.service_id == CHAT  # 身份不变


def test_bind_context_preserves_existing_tenant() -> None:
    issuer = _issuer(CHAT)
    claim = issuer.verify(issuer.issue(tenant_id="tenant-orig"))
    bound = gk.bind_context_to_claim(claim, tenant_id=TENANT)
    assert bound.tenant_id == "tenant-orig"


def test_constants_match_spec() -> None:
    assert gk.DEFAULT_ENV_PREFIX == "MOGO"
    assert gk.DEFAULT_LEEWAY_SECONDS == 300


# ---------------------------------------------------------------------------
# 022 T028：服务身份权限最小化（scope 权限码）
# ---------------------------------------------------------------------------


def test_scope_claim_roundtrips_through_token() -> None:
    """scope 必须写进 payload 并在 verify 后还原。"""
    issuer = _issuer()
    token = issuer.issue(scope=["gatekeeper.evaluate", "gatekeeper.decide"])
    claim = issuer.verify(token)
    assert claim.scope == ("gatekeeper.evaluate", "gatekeeper.decide")


def test_scope_accepts_comma_separated_string() -> None:
    """从环境变量读取时 scope 常是逗号分隔字符串，必须能归一化。"""
    issuer = _issuer()
    claim = issuer.verify(issuer.issue(scope="a,b,a,c"))
    assert claim.scope == ("a", "b", "c")


def test_scope_defaults_to_empty_tuple() -> None:
    issuer = _issuer()
    assert issuer.verify(issuer.issue()).scope == ()


def test_scope_verifies_against_tampered_payload() -> None:
    """攻击者改 payload 里的 scope 必须因签名失效被拒。"""
    issuer = _issuer()
    token = issuer.issue(scope=["gatekeeper.evaluate"])
    parts = token.split("|")
    import base64, json

    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "==").decode())
    payload["scope"] = ["gatekeeper.decide", "admin.*"]
    forged = f"{parts[0]}|{base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')}|{parts[2]}"
    with pytest.raises(ServiceTokenInvalid):
        issuer.verify(forged)


def test_verify_requires_scope_when_endpoint_demands_it() -> None:
    """端点要求 scope 时，令牌未携带即拒绝。"""
    issuer = _issuer()
    token = issuer.issue()  # 无 scope
    with pytest.raises(gk.GatekeeperDenied) as excinfo:
        gk.verify_service_call(
            token,
            expected_service_id=CHAT,
            issuer=issuer,
            required_scope=gk.SCOPE_GATEKEEPER_EVALUATE,
        )
    assert excinfo.value.reason == "insufficient_scope"


def test_verify_passes_when_scope_granted() -> None:
    issuer = _issuer()
    token = issuer.issue(scope=["gatekeeper.evaluate"])
    claim = gk.verify_service_call(
        token,
        expected_service_id=CHAT,
        issuer=issuer,
        required_scope=gk.SCOPE_GATEKEEPER_EVALUATE,
    )
    assert claim is not None
    assert gk.SCOPE_GATEKEEPER_EVALUATE in claim.scope


def test_verify_rejects_out_of_scope() -> None:
    """令牌只有 evaluate 权限，不能调用 decide 端点。"""
    issuer = _issuer()
    token = issuer.issue(scope=["gatekeeper.evaluate"])
    with pytest.raises(gk.GatekeeperDenied) as excinfo:
        gk.verify_service_call(
            token,
            expected_service_id=CHAT,
            issuer=issuer,
            required_scope=gk.SCOPE_GATEKEEPER_DECIDE,
        )
    assert excinfo.value.reason == "insufficient_scope"


def test_verify_rejects_unregistered_scope() -> None:
    """接收端不能接受随手编造的 scope 名，防止配置漂移。"""
    issuer = _issuer()
    token = issuer.issue(scope=["admin.*"])
    with pytest.raises(gk.GatekeeperDenied) as excinfo:
        gk.verify_service_call(
            token,
            expected_service_id=CHAT,
            issuer=issuer,
            required_scope="admin.*",
        )
    assert excinfo.value.reason == "unknown_scope"


def test_verify_skips_scope_check_when_endpoint_does_not_demand_it() -> None:
    """兼容既有调用方：required_scope 为空时不做 scope 校验。"""
    issuer = _issuer()
    token = issuer.issue()  # 无 scope
    claim = gk.verify_service_call(
        token,
        expected_service_id=CHAT,
        issuer=issuer,
        required_scope="",
    )
    assert claim is not None


def test_verify_scope_does_not_bypass_tenant_binding() -> None:
    """scope 通过也不能豁免双因子核对（fail-closed 语义不变）。"""
    issuer = _issuer()
    token = issuer.issue(
        scope=["gatekeeper.evaluate"], tenant_id="tenant-A"
    )
    with pytest.raises(gk.GatekeeperDenied) as excinfo:
        gk.verify_service_call(
            token,
            expected_service_id=CHAT,
            tenant_id="tenant-B",
            issuer=issuer,
            required_scope=gk.SCOPE_GATEKEEPER_EVALUATE,
        )
    assert excinfo.value.reason == "tenant_mismatch"


def test_bind_context_preserves_scope() -> None:
    issuer = _issuer()
    token = issuer.issue(scope=["gatekeeper.evaluate"], tenant_id=TENANT)
    claim = gk.bind_context_to_claim(
        issuer.verify(token), tenant_id=TENANT, user_id="user-1"
    )
    assert claim.scope == ("gatekeeper.evaluate",)


def test_all_service_scopes_are_registered_and_unique() -> None:
    assert gk.ALL_SERVICE_SCOPES == frozenset(gk.GATEKEEPER_ENDPOINT_SCOPES.values())
    assert len(gk.GATEKEEPER_ENDPOINT_SCOPES) == 4
    assert len(gk.ALL_SERVICE_SCOPES) == 4
