# Tasks: 凭证存储加密接线（034-credential-encryption）

**Input**: Design documents from `/specs/034-credential-encryption/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**——加密模块（022 已实现）零生产调用方，本特性负责接线；任务清单全部未勾选。

**Tests**: admin-api pytest（`services/admin-api/tests/test_security_encryption.py` / `services/admin-api/tests/test_security_kms.py` 复用回归 + 新增工具凭证测试）；chat-api pytest（`services/chat-api/tests/services/test_external_tools_mcp_transport.py` 注入回归 + 新增密文注入断言）；迁移脚本 fake-collection 单测。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；任务按 user story 标注 `[USn]`，`[P]` 表示可并行。

---

## Phase 0: 研究与澄清

- [ ] T001 [P] 代码级核实 022 加密模块现状：`services/admin-api/app/security/encryption.py`（`encrypt_value`/`decrypt_optional`/`is_encrypted_blob`/`reencrypt` 签名与 `purpose` 约定）与 `services/admin-api/app/security/kms.py`（`EnvVarKmsProvider` 环境变量约定、`KmsConfigError` 触发条件），确认零生产调用方的结论并记录既有测试清单
- [ ] T002 [P] 代码级核实两条写入路径与凭证键名：`services/admin-api/app/api/routes/tools.py:113-114`（`_normalize_payload` config 存取 + `_serialize` L65-75）、`services/chat-api/app/services/external_tools.py:141-142`（同构 `_normalize_payload` + `_serialize` L100）；与 admin-web `apps/admin-web/src/views/tools/ToolEditPage.vue:111-117` 对齐确认现网凭证键 = `authToken` / `apiKeyHeader` / `headers`
- [ ] T003 [P] 代码级核实注入侧现状：`services/chat-api/app/services/external_tools.py:736-741`（HTTP 注入）与 `958-964`（MCP 注入）、`965-973`（身份头最后覆盖语义）；确认改存取形态不改注入语义的边界
- [ ] T004 [P] 核实日志泄漏点：`external_tools.py:309-317` `external_tool_test_received` 对 config 整包落盘（含明文 authToken）；列出全部需脱敏的日志/错误出口
- [ ] T005 澄清 chat-api 引用 admin-api `app/security/` 的导入方式（同仓相对导入 / sys.path / 共享包），确认部署态两服务同版本；记录结论到 plan.md Technical Context
- [ ] T006 [P] 核实迁移脚本惯例：`scripts/migrate_main_id_to_tenant_id.py` 的 argparse 结构、`--dry-run`/`--apply`、备份前置声明、退出码约定；确认 034 脚本遵循同惯例

**Checkpoint**: 加密模块、双写路径、注入点、日志出口、脚本惯例全部有代码级结论；无未决澄清项。

---

## Phase 1: 设计

- [ ] T007 定义凭证字段识别 pure 函数契约：输入 config dict，输出需加密的键路径列表（顶层键 + `headers` 内同名键）；默认清单 `authToken`/`token`/`apiKey`/`secret`/`password`/`accessToken`/`refreshToken`，环境变量（如 `MOGO_TOOL_CREDENTIAL_KEYS`，逗号分隔）追加；空值/非字符串值跳过
- [ ] T008 定义加解密调用约定：`purpose="external_tool_credential"` 固定；写入 = `encrypt_value(plaintext, kms, purpose=...)`；读取 = `decrypt_optional(ciphertext, kms, purpose=...)`；识别 = `is_encrypted_blob(value)`；明确 `decrypt_optional` 宽容语义正是双跑期的兼容机制（非密文原样返回）
- [ ] T009 定义"保留缺失凭证键"合并语义：全量 `PUT`（非 partial）时 payload config 中缺失的凭证键，从 existing config 的密文继承后参与加密流程；`PATCH`（partial=True）未携带 config 时不触碰凭证；写成两条路径共用的合并函数
- [ ] T010 定义掩码约定：`_serialize` 对已设置凭证键回显 `"***"`；未设置（键不存在）不注入；空串值按"未设置"处理；前端编辑语义 = 留空保持（由保留语义保证）
- [ ] T011 定义 fail-closed 错误口径：`KmsConfigError`（密钥未配置）→ 保存请求返回可读配置错误；`EncryptionError`（解密失败）→ 工具调用失败不出站；两类错误的 HTTP 状态码与 detail 文案（不泄漏密钥/密文细节）
- [ ] T012 设计迁移脚本结构：扫描 `external_tools`（全租户全 scope）→ 逐行识别明文凭证键 → `is_encrypted_blob` 跳过已加密 → 加密后立即 `decrypt_optional` 校验原文一致 → 写回 → 汇总报告（扫描/迁移/跳过/失败）；`--dry-run` 零写入；失败行保持原状；非零退出码
- [ ] T013 设计轮换演练脚本结构：加载新主密钥 → 逐行 `reencrypt()` → 解密抽验 → 输出 `fingerprint` 前后对比（不含密钥本身）→ 提示备份回滚步骤；演练文档 `docs/credential-key-rotation-drill.md` 章节（前置备份/执行/核对/回滚）
- [ ] T014 梳理回归保护面：既有 `services/admin-api/tests/test_security_encryption.py`、`services/admin-api/tests/test_security_kms.py`、`services/chat-api/tests/services/test_external_tools_mcp_transport.py` 必须保持全绿；新增 US3 注入回归断言清单（bearer/api_key/身份头覆盖/fail-closed 四场景）

**Checkpoint**: 识别/加解密/合并/掩码/错误/迁移/轮换七类契约全部成文，可进入实现。

---

## Phase 2: 实现

### User Story 1 - 工具连接保存时凭证字段加密落库（P1）

- [ ] T015 [P] [US1] `services/admin-api/app/api/routes/tools.py`：新增凭证字段识别 + 加密调用（复用 `app/security/`），接入 `_normalize_payload` config 存取路径；`KmsConfigError` → 可读配置错误
- [ ] T016 [P] [US1] `services/chat-api/app/services/external_tools.py`：同构接入 `_normalize_payload` config 存取路径（T015 的识别/加密逻辑经共享模块或同构实现，按 T005 结论落地）
- [ ] T017 [US1] 两条路径实现"保留缺失凭证键"合并语义（T009）：全量更新不丢已存凭证密文；补单测（US1 场景 1/2/3/4）
- [ ] T018 [US1] `services/admin-api/tests/test_tools_credential_encryption.py`：fake DB 覆盖 admin-api 写入加密——密文落库、非凭证字段明文、authType=none 不加密、headers 内凭证键加密

### User Story 2 - API 响应掩码回显（P1）

- [ ] T019 [P] [US2] `services/admin-api/app/api/routes/tools.py::_serialize`：已设置凭证键回显 `"***"`（T010 约定），未设置不注入键
- [ ] T020 [P] [US2] `services/chat-api/app/services/external_tools.py::_serialize`：同构掩码（含 `list`/`get`/`create`/`update` 全部出口）
- [ ] T021 [US2] 前端编辑语义核对：`apps/admin-web/src/views/tools/ToolEditPage.vue` 的 authToken 输入框在"已设置"时展示 `***`（后端回显即 `***`，输入框为 password 类型，无需改组件结构）；补"留空 PATCH 保持原值"链路测试（US2 场景 1/2/3/4）

### User Story 3 - Agent 侧服务端注入行为不回退（P1）

- [ ] T022 [US3] `services/chat-api/app/services/external_tools.py`：注入点（L736-741 HTTP、L958-964 MCP）改用 `decrypt_optional()` 读取凭证；身份头最后覆盖语义（L965-973）逐字保持
- [ ] T023 [US3] fail-closed：解密失败（`EncryptionError`）→ 工具调用返回可读错误、不出站、不回退明文（T011 口径）
- [ ] T024 [US3] 日志脱敏：`external_tools.py:309-317` 测试路径 config 整包日志改为脱敏输出（只记键名/掩码值）；排查其余出口（T004 清单）确保无明文
- [ ] T025 [US3] `services/chat-api/tests/test_external_tools_credential_injection.py`：密文凭证注入回归四场景——bearer 注入、api_key 注入、身份头伪造被覆盖、解密失败 fail-closed；LLM 侧消息/工具描述无 token 断言

### User Story 4 - 存量明文凭证一次性迁移（P2）

- [ ] T026 [US4] `scripts/migrate_tool_credentials_encryption.py`：按 T012 结构实现（幂等 + `--dry-run` + 双跑校验 + 报告 + 失败行原状 + 非零退出码）；文件头注明"先 `mongodump` 备份、评审后执行"（沿用 `migrate_main_id_to_tenant_id.py` 声明范式）
- [ ] T027 [US4] 迁移脚本单测：fake collection 覆盖——明文行迁移、已加密行跳过（密文字节不变）、空值跳过、中途失败行保持原状、二次运行迁移数为 0
- [ ] T028 [US4] 演练数据准备与干跑记录：构造含明文/密文/无凭证/多 scope 的样本集合，`--dry-run` 输出零写入的证据

### User Story 5 - 密钥轮换演练（P2）

- [ ] T029 [US5] `scripts/rotate_tool_credentials_key.py`：按 T013 结构实现（`reencrypt` + 指纹前后对比 + 解密抽验 + 回滚提示）
- [ ] T030 [US5] `docs/credential-key-rotation-drill.md`：演练文档——前置备份、新旧主密钥配置、执行步骤、核对清单（指纹变更/调用正常/旧备份可回滚）、回滚操作
- [ ] T031 [US5] 轮换脚本单测：旧密钥加密样本 → 轮换 → 新密钥解密全成功、旧密钥解密失败、回滚路径可走通

---

## Phase 3: 验证与接线

- [ ] T032 回归护栏：`services/admin-api/tests/test_security_encryption.py`、`test_security_kms.py`、`services/chat-api/tests/services/test_external_tools_mcp_transport.py` 全绿（证明复用未破坏 022 语义、注入未回退）
- [ ] T033 [P] 全链路验证（staging）：真实保存工具→查库无明文（SC-001 grep）→ 列表/详情掩码（SC-004）→ Agent 触发工具调用注入正常（SC-002）→ 日志无明文（FR-011）
- [ ] T034 [P] 迁移演练（staging）：备份→`--dry-run`→`--apply`→二次运行幂等证据→对账报告（SC-005）
- [ ] T035 [P] 轮换演练（staging）：按 T030 文档走一遍——轮换后调用正常、旧密钥失效、备份可回滚（SC-003）
- [ ] T036 验收口径逐项打勾：SC-001（DB 无明文）/SC-002（注入不回退）/SC-003（轮换可演练可回滚）/SC-004（响应 100% 掩码）/SC-005（迁移双跑一致）/SC-006（022 测试全绿）
- [ ] T037 更新 `specs/034-credential-encryption/tasks.md` 勾选状态；按任务约束**不**创建 checklists/ 与 quickstart.md、**不**更新 `specs/INDEX.md`（索引更新由仓库维护流程另行处理）

---

## Dependencies & Execution Order

- Phase 0（T001–T006）全部先行，无代码依赖，可并行。
- Phase 1（T007–T014）依赖 Phase 0 结论；T007–T010 是 Phase 2 所有 US 的前置契约。
- Phase 2 内：US1（T015–T018）是 US2/US3 的前置（掩码与解密读取都建立在写入加密之上）；US2 与 US3 可并行（T019–T021 ∥ T022–T025）；US4/US5（T026–T031）依赖 US1 的加密函数，可与 US2/US3 并行。
- Phase 3（T032–T037）依赖 Phase 2 完成；T033–T035 可并行（staging 三类演练）。
- 关键路径：T005（导入方式澄清）→ T015/T016（双写路径接线）→ T033（staging 全链路）。

## Notes

- 022 的 `decrypt_optional()` 宽容解密（非密文原样返回）是双跑期的**设计机制**而非权宜——迁移窗口期库中明文/密文并存，读路径不中断；迁移完成后仍保持宽容，防个别漏网明文导致全站工具不可用。
- 掩码串 `"***"` 是协议常量，不随原值长度变化（防长度侧信道）；admin-web 输入框已是 password 类型（`ToolEditPage.vue:117`），前端零组件改动。
- 凭证键名清单可配置但默认覆盖现网全部已知键（`authToken` 为主）——YAGNI：不为假想的未来键名预建结构，环境变量追加机制已足够。
- 迁移脚本放 `scripts/` 而非 `deploy/`：迁移是数据操作，`deploy/` 是部署编排物；参照物是 `scripts/migrate_main_id_to_tenant_id.py`。
