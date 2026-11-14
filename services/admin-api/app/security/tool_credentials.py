"""034-credential-encryption：工具连接凭证字段的加密/解密/掩码接线.

把 022 已实现但零生产调用方的 :mod:`app.security.encryption` 与
:mod:`app.security.kms` 接到 ``external_tools`` 的 ``config`` 存取路径上：

- **写入**（``tools.py::_normalize_payload``）：只对识别出的凭证字段加密落库，
  其余 config 键（``endpoint``/``authType``/``apiKeyHeader``/``timeoutSeconds``/…）保持明文；
- **读取/注入**：用 ``decrypt_optional`` 宽容解密，兼容明文/密文双跑期；
- **响应**：对已设置的凭证键回显固定掩码 ``***``（不反映原值长度，防长度侧信道）。

凭证键名清单默认覆盖现网全部已知键，可用环境变量
``MOGO_TOOL_CREDENTIAL_KEYS``（逗号分隔）追加自定义键名。

密文 ``purpose`` 固定为 :data:`CREDENTIAL_PURPOSE`，同时作 AAD——
与 022 其他用途（``mfa_secret``/``api_key``）的密文不可互换。

> 同源副本：chat-api ``app/security/tool_credentials.py`` 与本文件逐字节一致
> （admin-api 与 chat-api 为独立容器，无法跨服务 import；022 的
> ``encryption.py``/``kms.py`` 亦为同源副本）。**修改任一份须两边同步**，
> 否则键名清单与密钥语义会漂移。
"""

from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any, Iterator

from .encryption import encrypt_value, decrypt_optional, is_encrypted_blob
from .kms import EnvVarKmsProvider

if TYPE_CHECKING:  # pragma: no cover
    from .kms import KMSProvider

# 加密用途标识（同时作为 AES-GCM AAD，不同用途密文不可互换）。
CREDENTIAL_PURPOSE = "external_tool_credential"

# 默认凭证键名清单（覆盖现网全部已知凭证键）。
DEFAULT_CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "authToken",
        "token",
        "apiKey",
        "secret",
        "password",
        "accessToken",
        "refreshToken",
    }
)

# 凭证清单追加环境变量：逗号分隔的自定义键名。
CREDENTIAL_KEYS_ENV = "MOGO_TOOL_CREDENTIAL_KEYS"

# 响应掩码固定串（协议常量，不随原值长度变化）。
MASK = "***"

_cache_kms: "KMSProvider | None" = None


def credential_keys(env: dict[str, str] | None = None) -> frozenset[str]:
    """返回生效的凭证键名清单（默认清单 + 环境变量追加）。"""
    source = os.environ if env is None else env
    extra = source.get(CREDENTIAL_KEYS_ENV, "")
    if not str(extra).strip():
        return DEFAULT_CREDENTIAL_KEYS
    added = {str(item).strip() for item in str(extra).split(",") if str(item).strip()}
    return DEFAULT_CREDENTIAL_KEYS | frozenset(added)


def iter_credential_key_paths(
    config: dict[str, Any],
    *,
    keys: frozenset[str] | None = None,
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """迭代 config 中命中凭证清单的键路径（顶层键 + ``headers`` 内同名键）。

    Yields:
        ``((key_path...), value)``；值可为非字符串（调用方自行跳过）。
    """
    active_keys = credential_keys() if keys is None else keys
    if not isinstance(config, dict):
        return
    for key, value in config.items():
        if str(key) in active_keys:
            yield ((key,), value)
    headers = config.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key) in active_keys:
                yield (("headers", key), value)


def _set_by_path(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if len(path) == 1:
        config[path[0]] = value
    elif len(path) == 2:
        headers = config.get("headers")
        if not isinstance(headers, dict):
            headers = {}
            config["headers"] = headers
        headers[path[1]] = value


def encrypt_credentials(
    config: dict[str, Any],
    kms: "KMSProvider | None" = None,
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """加密 config 中识别出的凭证字段，返回新 config（不改原对象）。

    - 空串 / 非字符串值跳过（``encrypt_value`` 拒绝空明文）；
    - 已是密文的键保持不动（幂等，供迁移脚本与重复写入复用）；
    - 无待加密凭证时**不触发 KMS**（``authType=none`` 的工具在密钥未配置时
      也不会报错，行为与现状逐字节一致）。

    Raises:
        KmsConfigError: 主密钥未配置/过短（fail-closed，不落明文兜底）。
        EncryptionError: 明文超长等输入错误。
    """
    result = copy.deepcopy(config) if isinstance(config, dict) else {}
    if not isinstance(config, dict):
        return result
    targets = [
        (path, value)
        for path, value in iter_credential_key_paths(config, keys=keys)
        if isinstance(value, str) and value.strip() and not is_encrypted_blob(value)
    ]
    if not targets:
        return result
    active_kms = kms if kms is not None else get_tool_credential_kms()
    for path, value in targets:
        _set_by_path(result, path, encrypt_value(value, active_kms, purpose=CREDENTIAL_PURPOSE))
    return result


def decrypt_credentials(
    config: dict[str, Any],
    kms: "KMSProvider | None" = None,
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """宽容解密 config 中识别出的凭证字段（非密文原样返回），供注入/读取路径。

    兼容明文/密文双跑期：迁移窗口库中两种形态并存时，工具调用不中断。
    """
    result = copy.deepcopy(config) if isinstance(config, dict) else {}
    if not isinstance(config, dict):
        return result
    targets = [
        (path, value)
        for path, value in iter_credential_key_paths(config, keys=keys)
        if is_encrypted_blob(value)
    ]
    if not targets:
        return result
    active_kms = kms if kms is not None else get_tool_credential_kms()
    for path, value in targets:
        _set_by_path(result, path, decrypt_optional(value, active_kms, purpose=CREDENTIAL_PURPOSE))
    return result


def redact_credentials(
    config: dict[str, Any],
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """响应掩码：已设置的凭证键回显固定 ``***``；空串/缺失键不注入。

    掩码串不反映原值长度，防长度侧信道；返回新 config，不改原对象。
    """
    result = copy.deepcopy(config) if isinstance(config, dict) else {}
    if not isinstance(config, dict):
        return result
    for path, value in iter_credential_key_paths(config, keys=keys):
        if not isinstance(value, str) or not value.strip():
            # 空串/空值按「未设置」处理：不注入掩码键，保持响应结构稳定。
            if len(path) == 1:
                result.pop(path[0], None)
            else:
                headers = result.get("headers")
                if isinstance(headers, dict):
                    headers.pop(path[1], None)
            continue
        _set_by_path(result, path, MASK)
    return result


def merge_credential_preserve(
    incoming_config: dict[str, Any],
    existing_config: dict[str, Any],
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """「保留缺失凭证键」合并语义（FR-006）。

    全量更新（PUT）或携带 config 的 PATCH 时，payload config 中**缺失或为空**的
    凭证键，从 existing config 的既有值（密文）继承——避免前端按掩码约定
    不回传凭证导致凭证被打成空。
    """
    incoming = copy.deepcopy(incoming_config) if isinstance(incoming_config, dict) else {}
    existing = existing_config if isinstance(existing_config, dict) else {}
    for path, value in iter_credential_key_paths(existing, keys=keys):
        current = incoming
        if len(path) == 2:
            current = incoming.get("headers") if isinstance(incoming.get("headers"), dict) else None
            if not isinstance(current, dict):
                continue
        holder = current.get(path[-1])
        # 空值 / 回显掩码串 ``***`` 都视为「未重新填写」——继承既有密文；
        # 若既有也为空则删除该键（保持「未设置」语义）。
        masked = isinstance(holder, str) and holder == MASK
        if holder is None or masked or (isinstance(holder, str) and not holder.strip()):
            if isinstance(value, str) and value.strip():
                _set_by_path(incoming, path, value)
            elif masked:
                if len(path) == 1:
                    incoming.pop(path[0], None)
                else:
                    headers = incoming.get("headers")
                    if isinstance(headers, dict):
                        headers.pop(path[1], None)
    return incoming


def get_tool_credential_kms() -> "KMSProvider":
    """返回进程级缓存的工具凭证 KMSProvider（避免热路径重复构造/派生）。"""
    global _cache_kms
    if _cache_kms is None:
        _cache_kms = EnvVarKmsProvider()
    return _cache_kms


def reset_tool_credential_kms_cache() -> None:
    """清空 KMSProvider 进程缓存（测试或切换密钥场景使用）。"""
    global _cache_kms
    _cache_kms = None


__all__ = [
    "CREDENTIAL_KEYS_ENV",
    "CREDENTIAL_PURPOSE",
    "DEFAULT_CREDENTIAL_KEYS",
    "MASK",
    "credential_keys",
    "decrypt_credentials",
    "encrypt_credentials",
    "get_tool_credential_kms",
    "iter_credential_key_paths",
    "merge_credential_preserve",
    "redact_credentials",
    "reset_tool_credential_kms_cache",
]