# Implementation Plan: 凭证存储加密接线（034-credential-encryption）

**Branch**: `034-credential-encryption` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/034-credential-encryption/spec.md`

**Note**: 本计划为**全新特性的接线实施**（非回溯补规格）——加密模块已由 022 实现，代码尚未开工；本文件固化接线口径与任务边界。设计来源：《MOGO × 企业 Agent OS 整合方案》§4.3。

## Summary

把 022 已实现但零生产调用方的 `app/security/encryption.py`（AES-256-GCM）与 `app/security/kms.py`（KMSProvider + EnvVarKmsProvider）接线到工具连接（`external_tools`）的 config 存取：两条写入路径（admin-api `tools.py`、chat-api `external_tools.py`）对识别出的凭证字段加密落库；读取/注入路径用 `decrypt_optional()` 宽容解密（兼容明文/密文双跑期），注入语义逐项不回退；两条 `_serialize` 响应路径回显 `***` 掩码；提供一次性幂等迁移脚本（存量明文→密文）与密钥轮换演练脚本/文档。KMS 首期环境变量（与 022 OQ-2 一致），不引入 Vault。

## Technical Context

**Language/Version**: Python 3.11+（admin-api 与 chat-api，FastAPI + pydantic v2；chat-api 服务层为 asyncio + motor）

**Primary Dependencies**: 复用既有——`cryptography`（AESGCM，022 已依赖）、`app/security/encryption.py`、`app/security/kms.py`、`pymongo/motor`（`db.external_tools`）；迁移脚本为仓库根 `scripts/` 下的独立 asyncio 脚本（参照 `scripts/migrate_main_id_to_tenant_id.py` 的 argparse + `--dry-run`/`--apply` 惯例）。**不引入任何新第三方依赖。**

**Storage**: MongoDB 集合 `external_tools`（已存在，admin-api `tools.py` 与 chat-api `external_tools.py` 双写路径共用）；本特性不改集合结构，只改 `config` 内凭证字段的存取形态（明文→密文）。密文为自描述 base64url 串（`v1|nonce|ciphertext||tag`），无需 schema 迁移。

**Testing**: pytest——admin-api `services/admin-api/tests/test_security_encryption.py` / `services/admin-api/tests/test_security_kms.py`（复用回归）、新增工具 CRUD 加解密/掩码测试（fake DB）；chat-api `services/chat-api/tests/services/test_external_tools_mcp_transport.py`（注入侧回归）+ 新增解密注入断言；迁移脚本用 fake collection 做单测（幂等/双跑/失败行原状）。

**Target Platform**: Docker Compose（admin-api + chat-api + MongoDB）；自托管 Linux/Docker。迁移脚本在维护窗口由运维执行（先 `mongodump`）。

**Project Type**: web-service 后端双服务（admin-api 管理面 + chat-api 运行面），monorepo。

**Performance Goals**: 凭证字段为小字符串（<1KB），AES-256-GCM 加解密为微秒级；`data_key_for` 的 HKDF 派生 MUST 按进程缓存（每次请求重复派生同一 purpose 数据密钥无意义），避免工具调用热路径上的重复派生开销。工具调用延迟预算不变（加密不成为瓶颈）。

**Constraints**:
- 不得修改 `app/security/encryption.py` / `kms.py` 的任何既有语义（022 测试必须保持全绿作为护栏）。
- 注入侧行为（`external_tools.py:947-977` 的 bearer/api_key 注入 + 身份头最后覆盖）逐项不回退。
- 密文 format/version 沿用 `v1`；不得引入 v2 或改 AAD 约定。
- 环境变量密钥约定沿用 022：`MOGO_KMS_MASTER_KEY` / `MOGO_KMS_MASTER_KEY_FILE` / `MOGO_KMS_PROVIDER` / `MOGO_ALLOW_INSECURE_DEV_KEY`，不发明新变量（凭证清单追加变量除外）。
- 日志脱敏纪律（022 FR-20）：任何日志/错误/审计不得含凭证明文。

**Scale/Scope**: 2 个写入路径 + 2 个序列化路径 + 2 个注入点（HTTP/MCP）接线；1 个迁移脚本 + 1 个轮换演练脚本 + 1 份演练文档；约 3–5 个测试文件新增/扩展。预估改动集中在 4 个既有文件 + 2 个新脚本 + 1 个新文档，零新依赖、零新集合、零 schema 变更。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本 spec/plan/tasks 三件套先行，代码未开工；决策表（7 项）在 Phase 0 前拍板，实现按 FR 收敛。
- **II. Enterprise Production Readiness**: ✅ 修复的是"已实现能力零生产调用方"的接线缺口，失败路径全部 fail-closed 且错误可读（密钥缺失→配置错误；解密失败→调用失败不出站）；迁移脚本遵循仓库既有"先备份、评审后执行、dry-run 先行"惯例（`migrate_main_id_to_tenant_id.py`），不引入未验证的自动写入。
- **III. Security and Data Protection**: ✅ 本特性即 022 FR-19/QF-650–656 的存储侧落地：密文存储（AES-256-GCM）、主密钥/数据密钥分离（HKDF）、purpose 作 AAD 防互换、响应掩码、日志脱敏、轮换可演练；不新增攻击面（不新建密码学实现，直接复用经 022 测试覆盖的模块）。
- **IV. Cross-Platform and i18n**: ✅ 纯后端存储/序列化改动，无新增用户可见文案（掩码串 `***` 为协议常量，前端已有 password 输入框）；迁移/演练输出为运维向中文说明，不涉及前端 i18n 键。
- **V. Observability and Simplicity**: ✅ 不新增架构复杂度：凭证字段识别是一个小 pure 函数 + 两个调用点；加解密是既有模块的既有函数；迁移脚本是仓库惯例的延伸。YAGNI——不做自动轮换调度、不做 Vault、不扩展到其他集合。

## Project Structure

### Documentation (this feature)

```text
specs/034-credential-encryption/
├── spec.md              # 特性规约（本计划引用的 spec）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（全新特性，全部未勾选）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/api/routes/tools.py            # 【改动】config 存取路径接线：_normalize_payload 写入加密（保留缺失凭证键语义）、_serialize 掩码回显 ***
├── app/security/encryption.py         # 【复用，022】encrypt_value / decrypt_optional / is_encrypted_blob / reencrypt——零改动
├── app/security/kms.py                # 【复用，022】KMSProvider / EnvVarKmsProvider / derive_data_key——零改动
└── tests/test_tools_credential_encryption.py   # 【新增】CRUD 加解密 + 掩码 + 保留语义（fake DB）

services/chat-api/
├── app/services/external_tools.py     # 【改动】_normalize_payload 写入加密、_serialize 掩码、注入点（L736-741 / L958-964）decrypt_optional 解密、L309-317 测试日志脱敏
└── tests/test_external_tools_credential_injection.py  # 【新增】密文凭证注入回归（bearer/api_key + 身份头覆盖 + fail-closed）

scripts/
├── migrate_tool_credentials_encryption.py  # 【新增】一次性存量迁移：幂等 + --dry-run + 双跑校验 + 报告
└── rotate_tool_credentials_key.py          # 【新增】密钥轮换演练：reencrypt + 指纹对比 + 回滚步骤提示

docs/
└── credential-key-rotation-drill.md        # 【新增】密钥轮换演练文档（步骤 + 回滚 + 核对清单）

specs/INDEX.md                        # 【不在本特性更新】按任务约束保持原状
```

**Structure Decision**: 复用既有 monorepo 布局与 `scripts/` 迁移脚本惯例，不新增子项目、不新增依赖、不改集合结构。加密能力复用 admin-api `app/security/`（022 落地处），chat-api 经同仓引用导入——不为 chat-api 复制第二份实现，避免双份密钥语义漂移（spec 决策 7）。迁移/轮换脚本放仓库根 `scripts/`，与 `migrate_main_id_to_tenant_id.py` 的运维脚本惯例一致（不放 `deploy/`——那里是部署编排物，迁移是数据操作）。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
