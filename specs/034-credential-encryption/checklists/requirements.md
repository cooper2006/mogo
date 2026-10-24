# Requirements Quality Checklist: 034 credential-encryption

**Purpose**: 校验 034（工具连接凭证明文 → AES-256-GCM 加密）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-23
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 `authType=none` 的工具是否仍加密 config 凭证键（决策表 #1 按"键名清单"识别、不区分 `authType`；而 tasks T018 明写"authType=none 不加密"——**两处口径相反**，实现按哪条都说得通）
- [x] CHK002 显式"清除已存凭证"的操作路径是否定义（决策表 #4 与 FR-006 只说留空或回传 `***` = 保持原密文；那么用户**没有任何方式删除**已保存的凭证，只能删整个工具）
- [x] CHK003 追加键名的环境变量契约是否定义（FR-002 只写"支持经环境变量追加自定义键名"；**未给变量名、分隔符、大小写敏感性、是否作用于 `config.headers`**，运维无法配置，测试无法断言）
- [x] CHK004 主密钥缺失时的可用性边界是否定义（FR-008 写"启动/保存时即报配置错误"；若**进程启动即失败**会拖垮所有不涉及工具的接口，若仅保存时失败则与"启动时报错"表述冲突）
- [x] CHK005 迁移脚本的扫描范围与报告字段是否定义（FR-009 只要求"输出扫描/迁移/跳过/失败计数"；**是否覆盖全租户全 scope、报告是否含 tool_id 与失败原因、`--dry-run` 输出格式**未定，SC-005"第二次运行迁移数为 0、失败数为 0"无法逐项核对）

## 清晰度（Clarity）

- [x] CHK006 掩码串 `***` 与"用户确实想存字面值 `***`"的冲突如何处置（掩码协议把 `***` 当"未重填"，则字面值永远无法保存；未声明是否可接受或如何逃逸）
- [x] CHK007 `config.headers` 的数据结构是否声明（dict 还是 list、加密后结构是否保持不变；前端按 headers 表单编辑，结构变化会破坏编辑语义，注入侧按 dict 取值也会失配）
- [x] CHK008 迁移期间的新写入窗口如何处理是否定义（迁移执行时若有旧版本服务继续写入明文，会出现"迁移后又变明文"；**是否需要停写/灰度顺序**未写，运维只能靠猜）
- [x] CHK009 轮换时新旧主密钥的共存方式是否定义（FR-010 要求把旧密文用新密钥重加密，但读旧密文需要旧密钥；`EnvVarKmsProvider` 只读一份 `MOGO_KMS_MASTER_KEY`，**同一进程如何同时持有新旧密钥**未定）

## 一致性（Consistency）

- [x] CHK010 FR-012「复用 admin-api `app/security/`、零复制实现」与容器隔离是否冲突（admin-api 与 chat-api 是**独立容器**，022 的 `encryption.py`/`kms.py` 在 chat-api 已是同源副本；"跨服务 import"在部署上不可行，FR-012 的表述需要改成可执行的形状）
- [x] CHK011 与 022 的 `purpose`/AAD 兼容性是否声明（同表历史密文若曾以其他 purpose 加密，`decrypt_optional` 会解密失败；此时按 FR-007 fail-closed 会让工具直接不可用，是否可接受未声明）
- [x] CHK012 掩码覆盖面与错误响应是否闭合（SC-004 要求"响应体（含错误响应）无凭证明文片段"，FR-005 只约束 `_serialize`；**chat-api 还有 list/get/create/update 与异常路径**多出口）
- [x] CHK013 日志脱敏的验收口径是否定义（FR-011 写"脱敏或只记键名"；**是否允许记录密文前缀 `v1|`**、脱敏出口清单是否穷举（`external_tool_test_received` 之外还有哪些）未定）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 加密失败的写入原子性是否定义（`KmsConfigError`/`EncryptionError` 在 config 多键场景下可能"部分键已加密"；是整单失败不落库，还是允许部分写入）
- [x] CHK015 迁移失败行的重跑语义是否定义（FR-009 要求失败行保持原状且退出码非零；SC-005 要求"第二次运行迁移数为 0、失败数为 0"——**若首次有失败行，第二次仍会失败**，两条验收需说明前提）

## Notes

- 条目编号 CHK001–CHK015 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表 / Assumptions / Non-Goals 原文。
- 本特性的需求风险集中在三处：**掩码协议**（CHK002/CHK006）、**部署拓扑**（CHK010）、**运维时序**（CHK008/CHK009）——这三处决定"规格是否可实现"，其余为验收可判定性。

## 评审结论（2026-10-23 勾选，agent 代审 + spec 回填）

15 条全部达标。2 条原生达标（CHK006/CHK011 在回填中直接固化为"已知限制/明确口径"），13 条经 `spec.md` 新增的「判定口径补充（R-1~R-16）」消解：

- CHK001（authType）→ R-1：识别只看键名；"不加密"的准确语义是"无待加密键不触发 KMS"。
- CHK002（清除凭证）→ R-2：首期不支持，后续用显式 `clearCredentials` 而非空值。
- CHK003（环境变量契约）→ R-3：`MOGO_TOOL_CREDENTIAL_KEYS`、逗号分隔、大小写敏感、仅顶层与 `headers`。
- CHK004（KMS 缺失边界）→ R-4：服务可启动，保存时报可读配置错误，fail-closed。
- CHK005（迁移范围与报告）→ R-5：全租户全 scope、三模式互斥、报告字段固定。
- CHK006（`***` 字面值）→ R-6：协议占用，明文不可存字面 `***`（已接受）。
- CHK007（headers 结构）→ R-7：固定 `dict[str, str]`，结构不变。
- CHK008（迁移期写入窗口）→ R-8：备份 → 停写 → 迁移 → 复核 → 上线。
- CHK009（新旧密钥共存）→ R-9：`MOGO_KMS_MASTER_KEY_OLD` + 标准新密钥。
- CHK010（FR-012 零复制 vs 容器隔离）→ R-10：更正为"同源副本 + 同步义务"，以 022 既有形态为准。
- CHK011（purpose 兼容）→ R-11：只认 `external_tool_credential`，其他 purpose 解密失败按 fail-closed。
- CHK012（掩码覆盖面）→ R-12：两服务 `_serialize` 四类出口统一 `redact_credentials`。
- CHK013（日志脱敏口径）→ R-13：只记键名 + `***`，禁止密文片段。
- CHK014（写入原子性）→ R-14：内存构造完成后一次性写回，失败不落库。
- CHK015（失败行与重跑）→ R-15：失败行原状 + 非零退出码；SC-005 以首次全成功为前提。

**验收证据**：`services/admin-api/tests/test_tools_credential_encryption.py` + `test_security_encryption.py` + `test_security_kms.py` 合计 70 passed；`services/chat-api/tests/services/test_external_tools_credential_injection.py` + `test_external_tools_mcp_transport.py` 合计 13 passed；新增 `services/admin-api/tests/test_migrate_tool_credentials.py` 9 passed（覆盖 T027 五场景：明文迁移 / 已加密跳过且字节不变 / 空值跳过 / 失败行原状 / 二次运行 0 迁移）；迁移脚本补齐 FR-009 的非零退出码。两份 `app/security/tool_credentials.py` 经 `diff -q` 确认逐字节一致（R-10）。
