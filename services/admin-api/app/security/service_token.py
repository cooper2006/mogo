"""服务间独立凭证（022 FR-12 / T019）。

把「admin-api ↔ chat-api 共用一个 `ADMIN_BACKEND_SERVICE_TOKEN`」收敛为
**每个服务独立签发、独立校验**的凭证：

- **独立密钥**：每个服务持有自己的 primary / previous 两个密钥，互不共享；
- **生命周期 ≤ 24h**：签发时强制夹取，超出的请求被拒（FR-12）；
- **轮换**：``ServiceCredentialVault.rotate()`` 把当前密钥降为 previous，
  生成新 primary。校验期同时接受两个密钥，旧凭证在过期前自然失效，
  无需人工清理；
- **无状态**：令牌是 HMAC-SHA256 签名的自描述 envelope，不需要存储表；
- **可注入时钟**：便于测试，不依赖真实时间。

令牌格式::

    v1|<base64url(json payload)>|<base64url(hmac-sha256)>

Payload 字段：``service_id`` / ``audience`` / ``tenant_id`` / ``iat`` /
``exp`` / ``jti``。签名覆盖 ``v1|payload``，防止 payload 被替换后重签。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: HTTP 头名（与既有 `X-MOVO-Service-Token` 约定保持一致）。
SERVICE_TOKEN_HEADER = "X-MOVO-Service-Token"

#: FR-12：服务间凭证生命周期上限 24h。
SERVICE_TOKEN_MAX_TTL_SECONDS = 24 * 3600

#: 校验时允许的时钟偏移（NTP 漂移兜底）。
DEFAULT_LEEWAY_SECONDS = 300

#: 令牌版本前缀。
_TOKEN_VERSION = "v1"

#: 密钥最小长度（192 bit），低于则拒绝构造，避免弱密钥误配置。
MIN_SECRET_BYTES = 24

#: 环境变量前缀：``{prefix}_SERVICE_ID`` / ``{prefix}_SERVICE_TOKEN`` /
#: ``{prefix}_SERVICE_TOKEN_PREVIOUS``。
ENV_PREFIX_DEFAULT = "MOGO"


class ServiceTokenError(Exception):
    """服务凭证校验失败的基类。"""


class ServiceTokenInvalid(ServiceTokenError):
    """格式错误、签名不符、版本不支持或 audience 不匹配。"""


class ServiceTokenExpired(ServiceTokenError):
    """令牌已过期（超出 leeway）。"""


class ServiceCredentialError(ServiceTokenError):
    """密钥配置不合法（过短 / 为空）。"""


# ---------------------------------------------------------------------------
# 密钥库：每服务独立，支持双密钥轮换
# ---------------------------------------------------------------------------


def _normalize_secret(value: Any, *, minimum: int = MIN_SECRET_BYTES) -> str:
    raw = str(value or "").strip()
    if len(raw) < minimum:
        raise ServiceCredentialError(
            f"service token secret must be at least {minimum} chars, got {len(raw)}"
        )
    return raw


class ServiceCredentialVault:
    """单服务的凭证密钥库。

    持有一对密钥：``primary``（当前签发用）与 ``previous``（轮换窗口内
    仅用于校验旧令牌）。轮换时把 primary 降为 previous 并生成新 primary，
    因此轮换后最多有 2 个密钥同时有效。
    """

    def __init__(self, primary: str, previous: str = "", *, rotate_started_at: float | None = None) -> None:
        self._primary = _normalize_secret(primary)
        self._previous = str(previous or "").strip()
        self._rotate_started_at = rotate_started_at

    @classmethod
    def from_env(
        cls,
        service_id: str,
        *,
        env_prefix: str = ENV_PREFIX_DEFAULT,
        primary_name: str | None = None,
        previous_name: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "ServiceCredentialVault":
        """从环境变量读取密钥。

        命名规则（按顺序取第一个非空值）：

        1. ``{prefix}_{SERVICE_ID}_TOKEN`` —— 服务专属密钥（推荐）；
        2. ``{prefix}_SERVICE_TOKEN`` —— 通用回退（兼容既有部署）。

        previous 取 ``{prefix}_{SERVICE_ID}_TOKEN_PREVIOUS``；未设置时为空串，
        表示当前不处于轮换窗口。

        Args:
            primary_name: 直接指定 primary 变量名（优先于命名规则），
                previous 取 ``{primary_name}_PREVIOUS``。
            environ: 注入环境变量字典，便于测试。
        """
        import os as _os

        env = environ if environ is not None else _os.environ
        sid = str(service_id or "").strip().upper().replace("-", "_").replace(".", "_")

        if primary_name:
            candidates = [primary_name]
            prev_name = previous_name or f"{primary_name}_PREVIOUS"
        else:
            candidates = [f"{env_prefix}_{sid}_TOKEN", f"{env_prefix}_SERVICE_TOKEN"]
            prev_name = previous_name or f"{env_prefix}_{sid}_TOKEN_PREVIOUS"

        primary = ""
        for name in candidates:
            if env.get(name):
                primary = env[name]
                break

        if not primary:
            raise ServiceCredentialError(
                f"no service token configured for service '{service_id}' "
                f"(checked {', '.join(candidates)} + {prev_name})"
            )
        return cls(primary, str(env.get(prev_name) or ""))

    @property
    def primary(self) -> str:
        return self._primary

    @property
    def previous(self) -> str:
        return self._previous

    @property
    def rotate_started_at(self) -> float | None:
        return self._rotate_started_at

    def accepting_keys(self) -> tuple[str, ...]:
        """当前可接受的校验密钥（primary 优先）。"""
        keys = [self._primary]
        if self._previous and self._previous != self._primary:
            keys.append(self._previous)
        return tuple(keys)

    def rotate(self, *, new_secret: str | None = None, now: float | None = None) -> tuple[str, str]:
        """轮换密钥。

        Returns:
            ``(new_primary, demoted_previous)``。旧 primary 降为 previous，
            其签发的令牌在过期前仍可校验，之后自然失效。
        """
        demoted = self._primary
        fresh = _normalize_secret(new_secret if new_secret is not None else secrets.token_urlsafe(48))
        if fresh == demoted:
            raise ServiceCredentialError("rotated secret must differ from the current primary")
        self._previous = demoted
        self._primary = fresh
        self._rotate_started_at = float(now) if now is not None else time.time()
        return fresh, demoted


# ---------------------------------------------------------------------------
# 令牌 claim
# ---------------------------------------------------------------------------


def _normalize_scope(scope: str | Iterable[str] | None) -> list[str]:
    """把 scope 入参归一化成去重、去空白的有序列表。

    接受单个字符串、字符串序列或逗号分隔的字符串（例如从环境变量读取时）。
    """
    if scope is None:
        return []
    if isinstance(scope, str):
        items = [part for part in scope.split(",")]
    else:
        items = list(scope)
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


@dataclass(frozen=True)
class ServiceTokenClaim:
    """校验通过后的凭证声明。"""

    service_id: str
    exp: int
    issued_at: int
    jti: str
    audience: str = ""
    tenant_id: str = ""
    # 022 T028：最小权限。令牌显式携带被授权的权限码集合；接收方据此判定
    # 本次调用是否在授权范围内，而不是"认得出是谁"就全放行。
    scope: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def ttl_seconds(self) -> int:
        return max(0, int(self.exp) - int(self.issued_at))

    def is_expired(self, now: float | None = None, *, leeway: int = 0) -> bool:
        ts = float(now) if now is not None else time.time()
        return int(self.exp) + int(leeway) < int(ts)


# ---------------------------------------------------------------------------
# 编解码
# ---------------------------------------------------------------------------


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(secret: str, unsigned: str) -> str:
    return _b64encode(hmac.new(secret.encode("utf-8"), unsigned.encode("utf-8"), hashlib.sha256).digest())


def _signature_matches(secret: str, unsigned: str, expected: str) -> bool:
    return hmac.compare_digest(_sign(secret, unsigned), expected)


# ---------------------------------------------------------------------------
# 签发 / 校验
# ---------------------------------------------------------------------------


class ServiceTokenIssuer:
    """一个服务自己的签发 + 校验器。"""

    def __init__(
        self,
        vault: ServiceCredentialVault,
        service_id: str,
        *,
        max_ttl_seconds: int = SERVICE_TOKEN_MAX_TTL_SECONDS,
        leeway_seconds: int = DEFAULT_LEEWAY_SECONDS,
    ) -> None:
        sid = str(service_id or "").strip()
        if not sid:
            raise ServiceCredentialError("service_id must not be empty")
        max_ttl = int(max_ttl_seconds)
        if max_ttl <= 0 or max_ttl > SERVICE_TOKEN_MAX_TTL_SECONDS:
            raise ServiceCredentialError(
                f"max_ttl_seconds must be in (0, {SERVICE_TOKEN_MAX_TTL_SECONDS}], got {max_ttl}"
            )
        self._vault = vault
        self._service_id = sid
        self._max_ttl = max_ttl
        self._leeway = int(leeway_seconds)

    @property
    def service_id(self) -> str:
        return self._service_id

    def issue(
        self,
        *,
        audience: str = "",
        tenant_id: str = "",
        ttl_seconds: int | None = None,
        jti: str | None = None,
        now: float | None = None,
        extra: dict | None = None,
        scope: str | Iterable[str] | None = None,
    ) -> str:
        """签发一枚新令牌。

        ``ttl_seconds`` 超出 FR-12 上限会被夹取到上限，而不是报错 ——
        凭证生命周期是本规格的硬约束，不能靠配置放宽。
        """
        ts = int(float(now) if now is not None else time.time())
        ttl = int(self._max_ttl) if ttl_seconds is None else int(ttl_seconds)
        ttl = min(ttl, self._max_ttl)
        if ttl <= 0:
            raise ServiceCredentialError("ttl_seconds must be positive")
        payload = {
            "service_id": self._service_id,
            "audience": str(audience or ""),
            "tenant_id": str(tenant_id or ""),
            "iat": ts,
            "exp": ts + ttl,
            "jti": jti or str(uuid.uuid4()),
            "scope": _normalize_scope(scope),
        }
        # 022 T020：允许调用方把业务上下文（如 user_id）写进 claim，
        # 供接收方做双因子核对。这些键不进白名单结构，保留在 extra 里。
        for key, value in (extra or {}).items():
            if key in payload:
                continue
            payload[str(key)] = value
        unsigned = f"{_TOKEN_VERSION}|{_b64encode(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8'))}"
        return f"{unsigned}|{_sign(self._vault.primary, unsigned)}"

    def verify(self, token: str, *, expected_audience: str = "", now: float | None = None) -> ServiceTokenClaim:
        """校验令牌并返回 claim。

        Raises:
            ServiceTokenInvalid: 格式 / 版本 / 签名 / audience 不匹配。
            ServiceTokenExpired: 已过期（超出 leeway）。
        """
        ts = float(now) if now is not None else time.time()
        if not isinstance(token, str):
            raise ServiceTokenInvalid("token must be a string")
        parts = token.strip().split("|")
        if len(parts) != 3 or parts[0] != _TOKEN_VERSION:
            raise ServiceTokenInvalid("malformed service token")
        _, payload_b64, sig = parts
        unsigned = f"{parts[0]}|{payload_b64}"

        if not any(_signature_matches(key, unsigned, sig) for key in self._vault.accepting_keys()):
            raise ServiceTokenInvalid("signature mismatch")

        try:
            payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceTokenInvalid("payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ServiceTokenInvalid("payload is not an object")

        service_id = str(payload.get("service_id") or "")
        if service_id != self._service_id:
            raise ServiceTokenInvalid("token was issued for a different service")

        audience = str(payload.get("audience") or "")
        if expected_audience and audience and audience != expected_audience:
            raise ServiceTokenInvalid("audience mismatch")

        try:
            issued_at = int(payload.get("iat") or 0)
            exp = int(payload.get("exp") or 0)
        except (TypeError, ValueError) as exc:
            raise ServiceTokenInvalid("iat/exp must be integers") from exc
        if exp <= issued_at:
            raise ServiceTokenInvalid("exp must be greater than iat")
        if exp - issued_at > self._max_ttl:
            raise ServiceTokenInvalid("token ttl exceeds the allowed maximum")

        if exp + self._leeway < ts:
            raise ServiceTokenExpired(f"token expired at {exp}, now={int(ts)}")

        extra = {k: v for k, v in payload.items() if k not in {"service_id", "audience", "tenant_id", "iat", "exp", "jti", "scope"}}
        try:
            scope = tuple(str(item) for item in _normalize_scope(payload.get("scope")))
        except ServiceTokenInvalid:
            raise
        return ServiceTokenClaim(
            service_id=service_id,
            exp=exp,
            issued_at=issued_at,
            jti=str(payload.get("jti") or ""),
            audience=audience,
            tenant_id=str(payload.get("tenant_id") or ""),
            scope=scope,
            extra=extra,
        )


__all__ = [
    "DEFAULT_LEEWAY_SECONDS",
    "ENV_PREFIX_DEFAULT",
    "MIN_SECRET_BYTES",
    "SERVICE_TOKEN_HEADER",
    "SERVICE_TOKEN_MAX_TTL_SECONDS",
    "ServiceCredentialError",
    "ServiceCredentialVault",
    "ServiceTokenClaim",
    "ServiceTokenExpired",
    "ServiceTokenError",
    "ServiceTokenInvalid",
    "ServiceTokenIssuer",
]
