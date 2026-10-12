"""FR-19 (QF-650/651–656) KMS 集成接口.

设计要点（见 OQ-2 clarify 决策）：
1. **接口先行**——所有加密调用只依赖 :class:`KMSProvider` 抽象，不感知密钥来源。
2. **主密钥与数据密钥分离**——``get_master_key(purpose)`` 返回的是用 HKDF-SHA256
   从主密钥派生的**数据密钥**（32 字节），主密钥本身从不参与 AES 运算。
   轮换主密钥时，不同 ``purpose`` 的数据密钥彼此独立，互不影响。
3. **首期用环境变量**——:class:`EnvVarKmsProvider`；Vault 作为可选集成
   （:class:`VaultKmsProvider` 实现同一接口，本期仅预留）。
4. **fail-closed**——主密钥缺失或过短直接抛 :class:`KmsConfigError`，
   绝不退回一个可预测的默认密钥。

环境变量约定：
- ``MOGO_KMS_PROVIDER`` — ``env``（默认）或 ``vault``。
- ``MOGO_KMS_MASTER_KEY`` — 主密钥（任意长度 ≥ 16 字节的字符串；会被 HKDF 扩展为 32 字节数据密钥）。
- ``MOGO_KMS_MASTER_KEY_FILE`` — 可选，从文件读取主密钥（优先于上面的环境变量）。
- ``MOGO_ALLOW_INSECURE_DEV_KEY=1`` — 本地开发用：允许使用内置弱主密钥（**仅限本地**）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

MASTER_KEY_ENV = "MOGO_KMS_MASTER_KEY"
MASTER_KEY_FILE_ENV = "MOGO_KMS_MASTER_KEY_FILE"
PROVIDER_ENV = "MOGO_KMS_PROVIDER"
ALLOW_DEV_KEY_ENV = "MOGO_ALLOW_INSECURE_DEV_KEY"

DATA_KEY_SIZE = 32  # AES-256
MIN_MASTER_KEY_BYTES = 16
HKDF_SALT_B = b"mogo/kms/v1"
DEV_MASTER_KEY = b"mogo-dev-master-key-DO-NOT-USE-IN-PROD"

KMS_PROVIDER_ENV = "env"
KMS_PROVIDER_VAULT = "vault"
SUPPORTED_PROVIDERS: tuple[str, ...] = (KMS_PROVIDER_ENV, KMS_PROVIDER_VAULT)


class KmsError(RuntimeError):
    """KMS 基础错误。"""


class KmsConfigError(KmsError):
    """主密钥缺失/过短/提供方未知——启动期即应视为配置错误。"""


class KmsProviderUnavailable(KmsError):
    """可选提供方（如 Vault）未接入或调用失败。"""


def hkdf_sha256(ikm: bytes, *, salt: bytes = HKDF_SALT_B, info: str = "", length: int = DATA_KEY_SIZE) -> bytes:
    """RFC 5869 HKDF-SHA256。不引入外部依赖，仅用 stdlib。"""
    if length <= 0 or length > 255 * 32:
        raise ValueError("invalid HKDF output length")
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    t = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info.encode("utf-8") + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def derive_data_key(master_key: bytes, *, purpose: str) -> bytes:
    """从主密钥派生一个 32 字节数据密钥（主密钥与数据密钥分离，QF-653）。"""
    if not isinstance(master_key, (bytes, bytearray)) or len(master_key) < 1:
        raise KmsConfigError("master key must be a non-empty byte string")
    return hkdf_sha256(bytes(master_key), info=f"mogo/data-key/{purpose}")


def fingerprint(key: bytes, *, length: int = 8) -> str:
    """密钥指纹（用于轮换校验与排障，不含密钥本身）。"""
    return hmac.new(b"mogo/fingerprint/v1", bytes(key), hashlib.sha256).hexdigest()[:length]


class KMSProvider(ABC):
    """密钥管理服务抽象接口（OQ-2）。

    实现约定：
    - ``get_master_key`` 必须返回 ≥ 16 字节的原始主密钥（尚未派生）。
    - 实现必须是可并发调用且无副作用。
    - 失败时抛 :class:`KmsError` 子类，**不得**返回空字节。
    """

    name: str = "abstract"

    @abstractmethod
    def get_master_key(self) -> bytes:
        """返回原始主密钥。"""

    @abstractmethod
    def describe(self) -> dict[str, object]:
        """返回不含密钥本身的描述信息（供诊断端点使用）。"""

    def data_key_for(self, purpose: str) -> bytes:
        """派生指定用途的数据密钥（32 字节）。"""
        return derive_data_key(self.get_master_key(), purpose=purpose)

    def rotate_master_key(self, purpose: str) -> bytes:  # pragma: no cover - 接口保留
        """轮换：返回新数据密钥。默认不实现（首期无轮换需求）。"""
        raise NotImplementedError(f"{self.name} does not support rotation yet")


@dataclass(frozen=True)
class EnvVarKmsProviderConfig:
    master_key_env: str = MASTER_KEY_ENV
    master_key_file_env: str = MASTER_KEY_FILE_ENV
    allow_insecure_dev_key_env: str = ALLOW_DEV_KEY_ENV
    min_master_key_bytes: int = MIN_MASTER_KEY_BYTES


class EnvVarKmsProvider(KMSProvider):
    """首期实现：主密钥来自环境变量（或文件）。"""

    name = KMS_PROVIDER_ENV

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        config: EnvVarKmsProviderConfig | None = None,
    ) -> None:
        self._env = os.environ if env is None else env
        self._config = config or EnvVarKmsProviderConfig()

    def get_master_key(self) -> bytes:
        cfg = self._config
        from_file = self._env.get(cfg.master_key_file_env, "").strip()
        if from_file:
            try:
                raw = Path(from_file).read_bytes()
            except OSError as exc:
                raise KmsConfigError(f"cannot read master key file {from_file!r}: {exc}") from exc
            raw = raw.strip()
            if len(raw) < cfg.min_master_key_bytes:
                raise KmsConfigError(
                    f"master key file {from_file!r} is too short "
                    f"({len(raw)} bytes < {cfg.min_master_key_bytes})"
                )
            return raw

        secret = self._env.get(cfg.master_key_env, "").strip()
        if not secret:
            if self._env.get(cfg.allow_insecure_dev_key_env, "").strip().lower() in {"1", "true", "yes"}:
                logger.warning(
                    "MOGO_ALLOW_INSECURE_DEV_KEY is set: using the built-in "
                    "weak master key. This MUST NOT be used outside local development."
                )
                return DEV_MASTER_KEY
            raise KmsConfigError(
                f"{cfg.master_key_env} (or {cfg.master_key_file_env}) is not set. "
                "Set the master key before encrypting sensitive fields, or set "
                f"{cfg.allow_insecure_dev_key_env}=1 for local development only."
            )
        if len(secret.encode("utf-8")) < cfg.min_master_key_bytes:
            raise KmsConfigError(
                f"{cfg.master_key_env} is too short "
                f"({len(secret.encode('utf-8'))} bytes < {cfg.min_master_key_bytes})"
            )
        return secret.encode("utf-8")

    def describe(self) -> dict[str, object]:
        try:
            key = self.get_master_key()
        except KmsError:
            return {"provider": self.name, "configured": False}
        return {
            "provider": self.name,
            "configured": True,
            "master_key_bytes": len(key),
            "master_key_fingerprint": fingerprint(key),
        }


class VaultKmsProvider(KMSProvider):
    """Vault / 其他 KMS 的可选项预留实现（OQ-2）。

    本期**不实现网络调用**：构造器接受与 Vault KV v2 对齐的参数，
    但 :meth:`get_master_key` 抛 :class:`KmsProviderUnavailable`，
    提示后续实现只需补齐这一处即可完成集成。
    """

    name = KMS_PROVIDER_VAULT

    def __init__(
        self,
        *,
        address: str = "",
        secret_path: str = "secret/data/mogo/kms/master",
        key_field: str = "value",
        token: str = "",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._address = address.rstrip("/") if address else ""
        self._secret_path = secret_path.strip("/")
        self._key_field = key_field
        self._token = token
        self._timeout_seconds = timeout_seconds

    def get_master_key(self) -> bytes:
        raise KmsProviderUnavailable(
            "Vault integration is reserved but not implemented in this release "
            "(022 OQ-2). Implement get_master_key() against "
            f"{self._address or '<vault address>'}/{self._secret_path} to enable it."
        )

    def describe(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "configured": bool(self._address),
            "address": self._address or None,
            "secret_path": self._secret_path,
            "key_field": self._key_field,
            "token_configured": bool(self._token),
        }


def load_master_key_from_env(env: dict[str, str] | None = None) -> bytes:
    """便捷函数：按环境变量约定加载主密钥（供脚本/迁移工具使用）。"""
    return EnvVarKmsProvider(env=env).get_master_key()


def _get_provider() -> KMSProvider:
    """按 ``MOGO_KMS_PROVIDER`` 选择实现（供后续登录/加密链路接线使用）。"""
    provider_name = get_provider_name()
    if provider_name == KMS_PROVIDER_VAULT:
        return VaultKmsProvider(
            address=os.environ.get("MOGO_KMS_VAULT_ADDRESS", ""),
            secret_path=os.environ.get("MOGO_KMS_VAULT_SECRET_PATH", "secret/data/mogo/kms/master"),
            token=os.environ.get("MOGO_KMS_VAULT_TOKEN", ""),
        )
    if provider_name not in SUPPORTED_PROVIDERS:
        raise KmsConfigError(
            f"unsupported MOGO_KMS_PROVIDER={provider_name!r}; supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return EnvVarKmsProvider()


def get_provider_name() -> str:
    return os.environ.get(PROVIDER_ENV, KMS_PROVIDER_ENV).strip().lower()


def iter_providers() -> Iterable[type[KMSProvider]]:
    """返回全部已注册实现，用于自检与文档生成。"""
    return (EnvVarKmsProvider, VaultKmsProvider)


def describe_all_providers() -> dict[str, object]:
    return {
        "selected": get_provider_name(),
        "supported": list(SUPPORTED_PROVIDERS),
        "env": EnvVarKmsProvider().describe(),
        "vault": VaultKmsProvider().describe(),
    }


__all__ = [
    "ALLOW_DEV_KEY_ENV",
    "DATA_KEY_SIZE",
    "DEV_MASTER_KEY",
    "EnvVarKmsProvider",
    "EnvVarKmsProviderConfig",
    "HKDF_SALT_B",
    "KMS_PROVIDER_ENV",
    "KMS_PROVIDER_VAULT",
    "KMSProvider",
    "KmsConfigError",
    "KmsError",
    "KmsProviderUnavailable",
    "MASTER_KEY_ENV",
    "MASTER_KEY_FILE_ENV",
    "MIN_MASTER_KEY_BYTES",
    "PROVIDER_ENV",
    "SUPPORTED_PROVIDERS",
    "VaultKmsProvider",
    "derive_data_key",
    "describe_all_providers",
    "fingerprint",
    "hkdf_sha256",
    "iter_providers",
    "load_master_key_from_env",
    "get_provider_name",
]
