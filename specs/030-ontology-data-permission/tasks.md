# Tasks: 本体数据权限（ontology data-scope permission）

**Feature**: `030-ontology-data-permission` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Input**: 设计闭环于 `docs/ontology-permission-merge-plan.md`（5 项决策已拍板）+ `docs/MOGO-Web应用集成方案.md` §5.4–§5.9

> **说明**：本特性为**回溯补规格**（代码先于 spec 落地，与 027 同处理方式）。已完成的项标 `[x]`，
> 未完成项标 `[ ]` 并注明阻塞原因。用户确认的落地范围为四项：**后端 API / 前端页面 / 建表入库 / 权限管理写入侧**。

## Clarify Decisions（2026-10-16 用户确认）

| # | 待澄清项 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | `sys_config` 新建还是复用 | **新建**通用配置表 `sys_config(key text primary key, value jsonb)` | FR-001 / T001 |
| 2 | 两层 AND 串联还是本体层独立可选 | **本体层独立可选**，不强制先过 `kg:read` | FR-004 |
| 3 | `defaultMode` 默认 deny 还是 allow | **`enforce=true` 时缺省固定 deny**；`defaultMode` 仅预演口径 | FR-012 / T13 |
| 4 | 后端走 `pg_compat` 门面还是原生 repository | **(A) 原生 repository** | FR-002 / T8 |
| 5 | 权限判定键用 `entity_type` 还是 `ontology_id` | **`ontology_id`**；`entity_type` 仅类型标签 | FR-014 / T6 |
| 6 | 索引写入方是否现在填 `ontology_id` | **不填**，业务系统集成后再接入 | 见 T7 备注 |

---

## Phase 0：建表入库（双后端）

- [x] **T001** 产出 PanWeiDB 建表段 `deploy/pg/ontology_permission.sql`：`sys_config` + 3 张 `mesc_*`（结构化列、复合主键、CHECK、jsonb 子列、索引）。文件头记录 3 项决策与 pg_compat caveat。
- [x] **T002** 产出 MongoDB 集合结构 `deploy/mongo/ontology_permission.js`：同构字段 + `$jsonSchema` 校验器（幂等 `createCollection`/`collMod`）+ 索引 + `sys_config` 种子。字段与 PG 一一对应（jsonb↔数组/对象、timestamptz↔Date、CHECK↔enum、复合主键↔确定性 `_id`）。
- [x] **T003** **执行入库**：PanWeiDB 侧 `mogo_dev` 建出 `sys_config` + 3 张 `mesc_*`（`sys_config` 种子 `{"enforce": false, "defaultMode": "allow"}`）；MongoDB 侧 `mogo_dev` 建出 4 个集合 + 9 个索引 + 同值种子。

## Phase 1：chat-api 运行时解析（核心）

- [x] **T004** 新增 `services/chat-api/app/services/ontology_permission.py`：`visible_ontology_ids` / `ontology_scope_snapshot` / `resolve_visible_ontologies`（纯函数）/ `SubjectSet` / `invalidate` / `clear_cache` / `set_cache_ttl` / `configure`。
- [x] **T005** 实现 fail-closed 语义：空 `tenant_id`/`user_id` 不查库返回空集；异常→空集且**不写缓存**并落 `deny` 审计；进程内 60s TTL 缓存。
- [x] **T006** 实现四态主体展开 `NativeSubjectProvider`：`tenant` 兜底 + `org`（含下级，按 `org_units.path_ids` 祖先链）+ `role`（`end_user_position_roles`）+ `user` 自身。
- [x] **T007** 接生效点 `business_semantic_index.py`：`SemanticHit.ontology_id`、`EntityRecord.ontology_id`（含 `as_document()` 与 `entity.indexed` 审计事件）、`semantic_search(..., visible_ontology_ids=None)` 按 `ontology_id` 过滤（缺键即隐藏；空集提前返回 `[]`；`None` 保持不过滤）。
  > **备注（用户明确要求）**：`EntityRecord.ontology_id` 已具备字段与透传，但**索引写入方暂不填充真实 `ontology_id`**（014 脚本 / business_index 端点不动）—— 待业务系统集成后再接入。
- [x] **T008** 测试：`tests/services/test_ontology_permission.py`（11 条，含 priority/同优先级取更严格/enabled/主体过滤/异常 fail-closed/缓存）+ `tests/services/test_semantic_search_ontology_filter.py`（6 条，含 `entity_type` 不授予权限、缺 `ontology_id` 被隐藏、`EntityRecord` 携带 `ontology_id`）。33 条通过。

## Phase 2：admin-api 原生 repository + 服务层

- [x] **T009** 新增包 `services/admin-api/app/ontology_permission/`：`constants.py`（表名/枚举/复合键）、`repository.py`（原生双后端）、`service.py`（配置/清单/可见集/授权写入侧）、`subjects.py`（四态主体展开）。
- [x] **T010** repository 覆盖 `list_grants` / `list_grants_for_subjects`（判权热路径批量查询）/ `upsert_grant` / `delete_grant` / `list_details` / `upsert_detail` / `delete_detail` / `write_audit` / `list_audit` / `get_sys_config` / `set_sys_config` / `list_catalog`。
- [x] **T011** 规避 PanWeiDB A 模式坑：upsert 走「先 UPDATE、`rowcount=0` 再 INSERT」；jsonb 路径用 `#>>`；不对 jsonb 文本做 `<> ''` 比较；占位符参数顺序与文本出现顺序一致。
- [x] **T012** 服务层：`resolve_visible_ontologies`（与 chat-api 镜像，注释声明两处必须同步）、`visible_ontologies`（当前账号）、`resolve_for_user`（四态展开，供内部接口）、`batch_grant`（去重 + 422 校验）、`revoke`（级联删类明细）、`bump_revision`、`get_config` / `set_enforce`、`list_catalog`、`list_audit`。
- [x] **T013** 测试：`services/admin-api/tests/test_ontology_permission_service.py` 20 条（含 `enforce=true → effectiveDefault=deny`、跨租户不泄漏、fail-closed 空用户、批量去重、撤销级联、清单含未索引本体）。全部通过。

## Phase 3：admin-api 路由（管理端 + 内部接口）

- [x] **T014** 新增 `app/api/routes/ontologies.py`（13 条路由）：`GET /mine`、`GET /`、`POST /sync`、`GET|PUT /config`、`GET /audit`、`GET|POST /users/{uid}/permissions`、`DELETE /users/{uid}/permissions/{oid}`、以及四态通用形态 `GET|POST|DELETE /subjects/{type}/{id}/permissions`。
- [x] **T015** 新增 `app/api/routes/ontology_permission_internal.py`：`GET /internal/ontology-permissions?tenantId=&userId=`，服务凭证鉴权（`hmac.compare_digest`，fail-closed 401）。
- [x] **T016** `app/api/router.py` 注册两个 router（`/ontologies`、`/internal/ontology-permissions`）。已验证 OpenAPI 中出现 13 条本体路由。
- [x] **T017** `/sync` 诚实降级：业务系统未接入时按 MOGO 侧业务实体索引聚合，响应中 `source` / `note` 明确标注来源，**不伪造**业务系统数据。

## Phase 4：admin-web 前端

- [x] **T018** `src/api/ontologies.ts`：类型 + 13 个 API 函数（用户级 + 四态通用 + 配置 + 审计 + 同步）。
- [x] **T019** `src/icons/OntologyIcon.ts`（照 `PositionRolesIcon` 写法）+ `src/router/routes.ts` 加 `/ontologies` 顶级菜单项。
- [x] **T020** `src/views/ontologies/OntologyCatalogPage.vue`：`enforce` 状态横幅（预演/拦截）+ 「我的可见本体」/「全量清单」双 Tab + 同步清单 + 开启/关闭拦截（带二次确认）。
- [x] **T021** `src/views/ontologies/UserOntologyPermissionDialog.vue`：照 `EmployeeCapabilityOverrideDialog` 写；批量勾选本体 + 访问模式 + 优先级 + 备注 + 已授予列表逐条撤销。
- [x] **T022** `OrganizationUsersPage.vue`：用户行新增「本体数据权限」按钮 + 弹窗挂载。

## Phase 5：集成验证与部署收口

- [x] **T023** 重建 `admin-api` / `chat-api` 镜像并滚动重启，跑通端到端冒烟：
      `GET /api/ontologies` → `POST /api/ontologies/users/{uid}/permissions` → `GET` 回读 → `DELETE` 撤销 → `GET /api/ontologies/audit` 出现两条记录。
      **已固化**为 `deploy/tests/test_ontology_permission_smoke.py`（容器内 stdin 直跑，缺 `ASKAI_ADMIN_JWT_SECRET` /
      active 账号时自动 skip，自建数据用完即删）。**实测 12/12 通过**，含 4 条加固项：
      批量去重、四态通用 role 授权、enforce 开+复原、未认证与内部接口无凭证 401。
      另实测网关链路：`/admin-api/api/internal/ontology-permissions` → 401（已放行，见 T024）。
      **镜像同步**：`admin-api:v0.2.2-30-gb5a1963` 与 `chat-api:v0.2.2-30-gb5a1963` 已重建并滚动替换
      （各 `up -d --no-deps` 后 `restart gateway`）；已验证新 chat-api 容器内
      `app.services.ontology_permission` 可导入、`business_semantic_index` 含 `visible_ontology_ids` 参数。
      admin-web 未重建（其内容是静态资源，需 `vite build` 后才能进镜像，见 T025）。
- [x] **T024** 网关放行内部接口——**已天然放行，无需改 nginx**（此前的 `[ ]` 是误判，已更正）。
      `deploy/nginx/nginx.conf:119` 的 `location /admin-api/` 前缀代理到 `admin-api:8100/`，
      因此 `/admin-api/api/internal/ontology-permissions` 会自动转成服务的
      `/api/internal/ontology-permissions`。实测（宿主机 → 网关 3000）：
      带 `/admin-api/` 前缀 → **401**（已打到服务且 token 鉴权生效）；不带前缀 → **404**（不会误暴露）；
      `/admin-api/api/ontologies` → 401。
      > **遗留（不入本期）**：设计 §6 约束 6 的「限制内部接口来源网段」**未做**。当前任何能到网关的
      > 客户端都能触达该端点（有服务 token 兜底）。若要加固，需先确认服务间调用的**实际**来源网段，
      > 否则有把合法调用拦错的风险 —— 属部署侧决策，不在代码落地范围。
- [x] **T025** `vue-tsc --noEmit` + `vite build` 通过（admin-web 类型检查与构建）。
      **已完成的验证**：① 静态接口一致性 —— icon 导出/import 对齐、路由 `component()` 路径与实际文件对齐、
      弹窗组件 import/使用对齐；② naive-ui 依赖闭合 —— template 用到的组件全部在 `bootstrap.ts` 的
      46 个全局注册项内，唯一例外 `NAlert`（未全局注册）已在两个新文件中**显式 import**；
      ③ 前后端字段契约 —— 批量授予用扁平 `{ontologyIds[], accessMode, priority, remark}`，回读用
      `{subjectType, subjectId, grants[], details[]}`，前端 `api/ontologies.ts` 与弹窗读取处均已核对一致，
      并在真实容器冒烟（T023）中走通。
      **2026-10-16 收口**：`pnpm install` 后以 `NODE_OPTIONS="--max-old-space-size=8192"` 分别跑通——
      `vue-tsc --noEmit` **exit 0、零错误**（此前误把 `--max-old-space-size` 当 vue-tsc 参数导致
      `TS5023: Unknown compiler option`，已改为 NODE_OPTIONS 环境变量）；
      `vite build` **exit 0、6.81s 构建完成**，`dist/assets/` 含
      `OntologyCatalogPage-*.js` + `ontologies-*.js` + `OntologyCatalogPage-*.css`。
- [ ] **T026** 前端联调复核：`/ontologies` 菜单可见、弹窗选项来自全量清单、撤销后列表即时刷新。
      **需用户在 dev / 部署环境目视执行**（agent 无法点击浏览器）。已就绪的部分：路由与菜单项已注册
      （`routes.ts:178`，顶级菜单「本体清单」+ `OntologyIcon`），弹窗从 `fetchOntologyCatalog()` 取选项，
      撤销后 `loadGrants()` 刷新。

## Phase 6：文档与日志

- [x] **T027** 补 `specs/030-ontology-data-permission/`（spec.md / plan.md / tasks.md）—— 本次补录。
- [x] **T028** 同步 `docs/ontology-permission-merge-plan.md`：状态改「已落地」并新增落地状态表；§3.2 补「已落库」、§3.8 补「已实现原生 repository」、§6 风险补「跨进程缓存传播窗口 = 60s TTL」与「类明细尚未接进检索生效点」、§7 落地阶段已执行。
- [x] **T029** 更新 `specs/INDEX.md` 增补 030 条目与 SDD 路径。
- [x] **T030** 更新 `docs/WORK_LOG.md`（建表入库 / 后端 / 前端 / spec 补录各一条），并写工作区记忆。
      **2026-10-16 收口**：WORK_LOG 已有 落地（一）建表入库 /（二）后端 /（三）前端 / 补录 spec /（四）端到端收口 /（五）mongo 等价冒烟，共 6 条，无需新增；
      工作区记忆（obsidian-mem，本会话 bind）已写 4 条：
      - `Decisions/ADR-1-030 本体数据权限：6 条澄清决策.md`
      - `Pitfalls/mongo upsert 的 enabled 归一化陷阱（bool(None)=False 静默禁用授权）.md`
      - `Pitfalls/PanWeiDB A 模式：占位符顺序 + psycopg3 jsonb 适配两个坑.md`
      - `Conventions/回溯补规格（代码先于 spec）的处理约定.md`

---

## 未闭环项（明确记录，不隐瞒）

| # | 项 | 原因 | 归属 |
| --- | --- | --- | --- |
| 1 | 索引写入方未填真实 `ontology_id` | 用户明确要求：业务系统集成后再接入 | 业务系统集成阶段 |
| 1b | SC-004 mongo 后端等价冒烟 | ~~未跑通~~ **已闭环**：`deploy/tests/test_ontology_permission_mongo_parity.py`（8/8），并因此抓到 enabled 归一化高危 bug | 已完成 |
| 2 | `sourceEntity` / `keyField` 返回空串 | 设计 §5.4 的独立副本集合属阶段 4 | 业务系统集成阶段 |
| 3 | 类明细的列投影 / 行过滤未接进检索生效点 | 表与仓储已就绪，但**阻塞链查清后确认无法在不动索引写入侧的前提下诚实实现**：除已登记的「索引未填 `ontology_id`」外，还要求命中携带 `class_name` 与行条件判定用的**结构化属性**，两者同样只存在于索引写入侧。强行在 resolver 侧写 detail 合并只会产出无调用方的死代码，故本轮**有意不实现** | 业务系统集成 + 索引补 `ontology_id`/`class_name`/属性后，按 §5.6.2 接入 |
| 4 | 跨进程缓存传播窗口 = 60s TTL | 两服务均未引入 Redis 客户端，无推送通道 | **本轮评估后决定不做**：收益（秒级生效）低于成本（双服务新增 redis 依赖 + 广播通道 + 失败降级）。队列 `mogo-redis-1` 虽在，但 60s 对「改配置」是可接受上界；若业务要求秒级，应作为独立特性立项 |
| 5 | ~~无独立 checklist 文件~~ | **已补**：`specs/030-ontology-data-permission/checklists/requirements.md`（照 028 五段式），如实标注 2 项未达标（spec 有实现细节泄漏、双后端等价未被自动化守护） | 已闭环 |
| 6 | `/internal/*` 网关未放行 | 需按部署环境显式配置 | T024 |
| 7 | 内部接口来源网段未限制（设计 §6 约束 6） | 需先确认服务间调用的实际来源网段，避免拦错 | 部署侧决策，见 T024 备注 |
| 8 | 冒烟用的 `admin-api` 镜像未纳入版本管理 | 本地构建 tag `admin-api:v0.2.2-30-gb5a1963`，需推 GHCR 才能在别处复现 | 发版流程 |
