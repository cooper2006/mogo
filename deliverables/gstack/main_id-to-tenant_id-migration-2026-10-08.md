# main_id → tenant_id 统一迁移方案（审批稿）

> **文档类型**：迁移方案（待审批，未落地任何代码）
> **日期**：2026-10-08
> **背景**：用户确认代码里租户 ID 叫 `main_id`，与治理层既有的 `tenant_id` 指同一概念，要求统一为 `tenant_id`，且**连持久化字段一起改 + 写迁移脚本**。
> **本方案不改动任何代码**，仅给出策略、分阶段、兼容与回滚，供审批。

## 1. 现状事实（已全量 grep 核实）

### 1.1 `tenant_id` 已是代码层主流
- 治理层（admin-api `governance`）、DSH 运行层（`gateway.py`/`runtime_coordinator.py`/`chat_service.py`/`bindings/repository.py`/`conversation/repository.py`）、`context_space`、`token_usage`、`a2a` 等均已用 `tenant_id`/`tenantId`。
- 这些是新代码，**无需改**。

### 1.2 `main_id` 仍是数据层既有租户主键（必须迁移）
- **MongoDB 存储字段** `main_id`：覆盖约 60+ 集合/代码路径，关键有
  - `end_users.main_id`（注册/登录鉴权主键）
  - `tenants.main_id`（`core/tenant.py` 的 `add_main_scope`/`resolve_main_id`/`DEFAULT_MAIN_ID` 全基于此）
  - `configured_models.main_id`、`billing`(ORGANIZATION)、`quota_policy`(ORG_QUOTA_POLICY)、`org_units`、`scheduled_tasks`、`token_usage`、`context_space`、`knowledge_graph`、`memory`、`a2a`、`personal_knowledge`、`org_user`(admin)、`directory`(admin)、`model_*`(admin)、`setup`(admin)、`tenant_registry`/`tenant_provisioning`/`tenant_purge` 等。
- **Weaviate schema 字段** `mainId`：`document-parser` 的 `vector_store.py` 定义为 schema 属性 `"name":"mainId","dataType":["text"]`，并在 `job_repository`/`retrieval_service`/`retrieval_access_policy`/`model_center_runtime` 大量读写过滤。

### 1.3 规模
- 命中点约 **190 个文件**（chat-api / admin-api / document-parser 各大量），含测试与文档。

## 2. 核心约束与风险

| 风险 | 说明 |
|---|---|
| **数据契约破坏** | 只改代码不改数据 → 现有文档仍是 `main_id` 字段，所有 `find({"tenant_id":...})` 立刻查不到 → 线上崩溃。必须"代码+迁移脚本+数据"三者同步。 |
| **Weaviate schema 不可变** | Weaviate 属性改名需重建 class 或 `tenantId`/`mainId` 双写期。 |
| **不可逆** | MongoDB 字段改名 + 文档改写一旦出错，需备份回滚。 |
| **测试漂移** | 大量 `main_id=` 入参的测试与契约（含多 host 契约测试、registration 测试）需同步改，否则 CI 失败。 |

## 3. 推荐策略：双写过渡 + 全量回填 + 旧字段退役

为避免一次性大爆炸，采用**三阶段兼容迁移**（与既有 schema 演进习惯一致）：

### Phase 1：双写兼容（代码可部署，零数据风险）
- 所有**写入**点同时写 `main_id` 与 `tenant_id`（同值）。
- 所有**读取/查询**点改为优先 `tenant_id`，回退 `main_id`（兼容旧文档）。
- 新增文档带 `tenant_id`；存量文档仅含 `main_id`，读取时回退仍可用。
- Weaviate：`mainId` 字段保留，新增 `tenantId` 字段并双写；查询优先 `tenantId` 回退 `mainId`。
- 此阶段**不删除任何旧字段**，纯增量，可随时回退代码。

### Phase 2：数据回填（一次性迁移脚本，可独立运行/重跑）
- 脚本 `scripts/migrate_main_id_to_tenant_id.py`（或仓库既有迁移目录）：
  - 遍历所有已知含 `main_id` 的集合，对每条文档 `$set: {"tenant_id": <main_id>}`（已存在则跳过）。
  - Weaviate：对每类对象 `$set {tenantId: mainId}`（已有则跳过）。
  - 幂等：重跑安全。
  - 输出受影响文档数，落迁移日志集合（便于回滚核对）。
  - **强制要求**：运行前 `mongodump` + Weaviate 快照备份；脚本仅 `git` 提交、不自动执行。

### Phase 3：旧字段退役（确认 Phase 1/2 全绿后，单独评审）
- 删除所有 `main_id` 回退读取逻辑、`tenantId` 回退逻辑、`mainId` 双写。
- 删除 MongoDB `main_id` 字段（脚本 `$unset`）；Weaviate 删除 `mainId` 属性。
- 同步清理测试与文档中的 `main_id`/`mainId`。
- 此阶段**破坏性**，需独立审批 + 备份回滚预案。

## 4. 涉及集合/范围清单（Phase 1/2 必须覆盖的写入点）

| 模块 | 关键文件/集合 | 字段 |
|---|---|---|
| 鉴权 | `chat-api/app/api/endpoints/auth.py`、`core/tenant.py`、`services/end_user_tenant_access.py` | `end_users.main_id`、`tenants.main_id` |
| 模型 | `chat-api/app/llm/configured_models.py`、`configured_image_models.py`、`document-parser/model_center_runtime.py` | `CONFIGURED_MODEL_COLLECTION.main_id` |
| 计费/配额 | `chat-api/app/core/billing.py`、`core/quota_policy.py`、`admin-api/app/core/quota_policy.py` | ORG/QUOTA 集合 `main_id` |
| 组织/目录 | `admin-api/.../org_user_repository.py`、`directory.py`、`tenant_registry.py` 等 | 多集合 `main_id` |
| 知识/检索 | `chat-api/app/.../personal_knowledge/*`、`knowledge_graph`、`context_space/*` | 多集合 `main_id` |
| Weaviate | `document-parser/app/services/vector_store.py`、`job_repository.py`、`retrieval_*` | schema `mainId` |
| 其他 | `scheduled_tasks`、`token_usage`、`a2a`、`memory`、`skill_sharing`、`setup_*`(admin) 等 | `main_id` |

> 完整文件清单约 190 个，迁移脚本枚举集合名（而非逐文件）执行，写入点改造在 Phase 1 按模块逐文件改。

## 5. 验证方式（每 Phase 后）
- **Phase 1**：`./mogo build && ./mogo up --build`；容器内验证注册/登录、租户切换、DSH 多实例 `/health`、`/ready` 仍正常；存量 `main_id` 文档可正常读取（回退路径）。
- **Phase 2**：迁移脚本 dry-run + 实跑，核对 `tenant_id` 填充数与 `main_id` 文档数一致；抽样读验证。
- **Phase 3**：全量测试（含 DSH 多 host 契约测试、registration 测试）绿；存量/增量数据均仅含 `tenant_id`。

## 6. 回滚
- Phase 1：代码 `git revert`，旧字段仍在，零数据损失。
- Phase 2：备份恢复 `mongorestore` / Weaviate 快照。
- Phase 3：依赖 Phase 2 备份 + 字段 `$set` 反向脚本（仅审批后提供）。

## 7. 建议审批内容
1. 确认采用**三阶段双写过渡**策略（而非一次性全局替换）。
2. 确认 Phase 1 先行（代码双写+回退读取，零数据风险、可部署）。
3. 确认 Phase 2 迁移脚本**提交但不自动执行**，先 dry-run + 备份。
4. Phase 3 退役旧字段单独评审，不在本轮自动执行。
5. 治理层（admin-api `governance`）已用 `tenant_id`，**不动**（符合你"治理层指同一概念、不需要改"的说明）。

## 8. 待拍板
- 是否接受"双写过渡"带来的约 190 文件改动量（Phase 1 实际是一次大 PR，但零停机风险）？
- 是否先行 Phase 1（可部署、可回退），Phase 2/3 后续单独排期？
