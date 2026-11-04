# Quickstart: 工具凭证加密 (034)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 工具凭证加密（034）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把 022 已实现但零生产调用的加密/KMS 模块接线到工具连接的 config 存取路径：写入加密、读取解密、API 响应掩码回显 `***`，并以一次性幂等脚本迁移存量明文凭证，使 DB 不再有明文凭证。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 在两条写入路径——admin-api `services/admin-api/app/api/routes/tools.py`（`_normalize_payload` 的 config 存取）与 chat-api `services/chat-api/app/services/ex
- FR-002：凭证字段识别 MUST 基于可配置密钥名清单（默认 `authToken`/`token`/`apiKey`/`secret`/`password`/`accessToken`/`refreshToken`，含 `config.headers` 内同名键），清单 MUST 支持经环境变量追加自定义键
- FR-003：加密 MUST 复用 `app/security/encryption.py::encrypt_value`（AES-256-GCM，`purpose="external_tool_credential"`），密文格式为 `v1|nonce|ciphertext||tag`（base64url）；M
- FR-004：读取路径（工具调用注入侧）MUST 复用 `decrypt_optional()` 宽容解密，兼容明文/密文双跑期；注入侧行为 MUST 与现状逐项一致——bearer/api_key header 注入 + `X-MOGO-Main-ID`/`X-MOGO-User-ID` 身份头最后覆盖（`ex
- FR-005：API 响应（admin-api `tools.py::_serialize` 与 chat-api `external_tools.py::_serialize`）MUST 对已设置的凭证字段回显固定串 `***`，MUST NOT 回显明文、长度或任何片段。

关键验收点（Success Criteria）：
- SC-001: DB 中无明文凭证——对 `external_tools` 集合全量 grep 已知测试凭证值（如 `sk-live-abc`）零命中；`config` 中凭证字段 100% 为 `is_encrypted_blob()` 为真的密文。
- SC-002: Agent 侧仍只拿服务端注入——现有注入行为零回退：bearer/api_key 注入 + 身份头不可伪造，既有 `services/chat-api/tests/services/test_external_tools_mcp_transport.py` 及新
- SC-003: 密钥轮换有演练脚本且旧密文可解密迁移——轮换后 100% 密文可用新密钥解密、旧备份可回滚、指纹变更可核对。
- SC-004: API 响应 100% 掩码——列表/详情/获取接口的凭证字段回显 `*`，响应体（含错误响应）无凭证明文片段。

## 3. 如何启用

复用 022 KMS：`MOGO_KMS_MASTER_KEY` / `MOGO_KMS_MASTER_KEY_FILE`（生产）或 `MOGO_ALLOW_INSECURE_DEV_KEY=1`（仅本地开发）；凭证字段识别键名清单可经 `MOGO_TOOL_CREDENTIAL_KEYS`（逗号分隔、大小写敏感精确匹配）追加。存量明文迁移走一次性幂等脚本，**执行前须 `mongodump` 备份**。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_migrate_tool_credentials.py services/admin-api/tests/test_rotate_tool_credentials.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/services/test_external_tools_mcp_transport.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
