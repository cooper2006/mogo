# 工具凭证主密钥轮换演练手册（Feature 034）

本手册描述如何演练并执行 `external_tools` 集合中凭证密文的主密钥轮换。
凭证加密复用 022 已实现的 AES-GCM（`app/security/encryption.py`）与 KMS 抽象
（`app/security/kms.py`），加密 `purpose` 固定为 `external_tool_credential`
（同时作为 AES-GCM AAD，不同用途密文不可互换）。

## 1. 前提条件

- 已完成 022 密钥配置：`MOGO_KMS_MASTER_KEY`（或 `MOGO_KMS_MASTER_KEY_FILE`，
  本地开发可用 `MOGO_ALLOW_INSECURE_DEV_KEY=1`）。
- 已完成 [Feature 034 凭证加密迁移](migrate_tool_credentials_encryption.py)：
  存量明文凭证已加密。若尚未迁移，轮换脚本会顺带把明文加密，但建议先跑迁移。
- 轮换前对 MongoDB 做一次 `mongodump` 备份。
- 新主密钥已生成并写入部署环境（生产环境建议通过 Vault / KMS 注入，
  见 `app/security/kms.py` 的 `VaultKmsProvider` 预留接口）。

## 2. 演练路径（不改变密钥，验证链路）

当**未**设置 `MOGO_KMS_MASTER_KEY_OLD` 时，`rotate_tool_credentials_key.py`
退化为「重加密演练」：用当前新密钥把密文解一遍再加密一遍，密文内容不变。

```bash
# 1) 统计（不写库）
python scripts/rotate_tool_credentials_key.py --dry-run

# 2) 实际重加密演练
python scripts/rotate_tool_credentials_key.py --apply

# 3) 复核：新密钥能否解密所有密文
python scripts/rotate_tool_credentials_key.py --verify
```

预期输出：`含凭证文档=N 旧密钥存在=False 已轮换=N`，`verify` 显示
`校验密文数=M 不可读=0`。

## 3. 真实轮换（更换主密钥）

```bash
# 1) 部署新主密钥，并把旧主密钥注入到（仅本次轮换期间）：
export MOGO_KMS_MASTER_KEY_OLD="<旧主密钥>"
export MOGO_KMS_MASTER_KEY="<新主密钥>"

# 2) 演练/预览
python scripts/rotate_tool_credentials_key.py --dry-run

# 3) 实际轮换
python scripts/rotate_tool_credentials_key.py --apply

# 4) 复核
python scripts/rotate_tool_credentials_key.py --verify

# 5) 轮换完成、验证通过后，清除旧密钥环境变量
unset MOGO_KMS_MASTER_KEY_OLD
```

轮换是**逐文档就地更新**：脚本对每个含凭证字段的文档，用旧密钥解密后用
新密钥加密写回 `config`。任何单文档失败都会记录在 `errors` 里，不中断整轮，
可重复执行直至 `errors` 为空。

## 4. 回滚

轮换脚本是幂等的；若新密钥出现问题，可在**仍持有旧密钥**的前提下把环境
变量互换（旧→`MOGO_KMS_MASTER_KEY`，新→`MOGO_KMS_MASTER_KEY_OLD`）后再次
`--apply`，把密文换回原密钥。前提是旧密钥仍然可用，因此务必保留备份。

## 5. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `KmsConfigError: MOGO_KMS_MASTER_KEY ... not set` | 新/旧密钥环境变量缺失或过短（<16 字节） | 检查部署环境的密钥注入 |
| `decrypt_value` 抛 `EncryptionError: authentication failed` | 旧密钥环境变量未设置或值错误 | 确认 `MOGO_KMS_MASTER_KEY_OLD` 为轮换前的原值 |
| `verify` 报 `不可读` | 个别文档仍由旧密钥加密且旧密钥不可用 | 用 `--dry-run` 定位该文档，恢复旧密钥后重跑 |
| 密钥来自文件/外部 KMS | `EnvVarKmsProvider` 支持 `MOGO_KMS_MASTER_KEY_FILE` | 在运行脚本的环境设置该变量 |

## 6. 集成 KMS / Vault（预留）

`app/security/kms.py` 的 `VaultKmsProvider` 已定义构造参数（address、secret_path、
key_field、token），当前 `get_master_key()` 抛 `KmsProviderUnavailable`。接入云 KMS
或 Vault 时，只需实现该方法返回主密钥字节，上层 `encrypt_credentials` /
`rotate_tool_credentials_key.py` 无需改动——它们只依赖 `KMSProvider` 接口。

## 7. 安全约束

- 脚本**不会打印任何凭证明文**，只输出字段路径、密文标记与统计数。
- 轮换应在低峰执行；工具凭证注入侧读路径已 fail-closed：解密失败会返回可读
  错误，**不会**回退到明文或把掩码 `***` 注入上游。
- 日志不得输出 `config` 整包内容（服务层已对响应与测试日志做掩码处理）。