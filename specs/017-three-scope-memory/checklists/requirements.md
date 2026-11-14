# Requirements Gate Checklist: 017 three-scope-memory（v3 验收口径）

> **本轮 Gate（T039 / T044，2026-11-06）**：本清单按 `spec.md` v3（§7 A–J FR、§8 SC-1~SC-15）重写，逐项核对**目标态落地状态**。
> **旧版 100% `[x]` 是「需求质量自评」，不能作为本轮 Gate**（`tasks.md` 第 9 行）；落地审计 `LANDING_AUDIT_2026-10-03.md` 曾判本特性 `hollow`。旧版第 48 行「超限拒绝写入」与改写后 **FR D-4** 不符，修正见文末「D-4 口径修正」。
> **状态口径（保守）**：`tasks.md` **B0 / B1 已落地并有测试证据**（新增 `app/memory/viewer.py` + P0 身份解析修复；`tests/memory` 等 171 passed、交叉回归 81 passed、`compileall` 通过）；**B2–B7 正在落地、尚未全部验收**；D4 改名与数据迁移必须在同一维护窗口原子切换。
> **标记语义**：本清单**不以 `[x]` 表示落地**，每行只标 `已落地（B1，有测试证据）` / `部分（B1 基础，目标态待 B2）` / `待 B2–B7 验收` / `进行中（T044）` 四态，**不伪造已勾选**。
> **权威口径**：[`spec.md`](../spec.md) §7/§8、[`design-2026-11-05-project-department-scopes.md`](../design-2026-11-05-project-department-scopes.md)（v3）、`contracts/memory-context-contract.md`、[`tasks.md`](../tasks.md)（B0–B7）。

## A. 身份与上下文（P0）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| A-1 | 唯一不可变 `MemoryViewerContext`，目标态字段含 `visible_department_ids` / `visible_project_keys` / `active_project_id` / `session_participants` | 部分（B1 已落地 frozen `MemoryViewerContext` + `build_viewer_context()` + 三个 fail-closed 查询，但字段为过渡版 `viewer_org_id` / `visible_workspace_ids`；目标态字段待 B2/T016） |
| A-2 | 所有入口只接受服务端构造上下文；禁止从 auth 字典取 `user_id` / `role` / `is_workspace_member`、禁止客户端自报身份 | 已落地（B1：四个 memory 端点、context_space 两端点、RAG `adapters.py` 全改走统一上下文） |
| A-3 | `role_keys` 从 006 `end_user_position_roles` → `position_roles.system_key` 解析；`is_full_access_admin` 由 `role_keys` 推导 | 已落地（B1） |
| A-4 | 部门集合：`end_user_org_relations` 不带 `status` 过滤（N3）∪ `primary_org_id` → `path_ids` 展开后代（D3）；跨租户 fail-closed | 待 B2 验收（T015） |
| A-5 | 项目集合 `visible_project_keys = {(project_id, project_owner_id)}`，显式排除 `"default"` 与 `archived` | 待 B2 验收（T014） |
| A-6 | 空 / 不完整上下文、任一解析失败 → fail-closed（401 或空集合），绝不回落宽松默认值 | 已落地（B1：身份解析修复 + `visible_to` 空 `viewer_id` / 空 `owner_id` fail-closed 防御） |

## B. 范围模型与可见性（P0/P1）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| B-1 | 范围轴封闭 `personal / project / department`，`Memory.__post_init__` 拒绝其它值 | 待 B2–B7 验收（D4/T011） |
| B-2 | `project` 绑定 `projects._id`；可见性 = 创建者 ∪ `member_user_ids`【049】 | 待 B2 验收（T013/T014） |
| B-3 | `department` 绑定 `org_units._id`；可见性 = 所在部门 + 全部后代、不含祖先（D3） | 待 B2 验收（T015） |
| B-4 | `visible_to` 是唯一判据、021 只委托、判定基于存储记录而非请求参数 | 部分（B1 已有 `visible_to` 框架与空身份防御；D4 后按 `visible_to(memory, MemoryViewerContext)` 重写待 B2/T013） |
| B-5 | 范围与上下文标签分离（tag 不参与鉴权） | 待 B2–B7 验收 |
| B-6 | （D4）写入 / 列表筛选 / 地址解析三处拒绝旧值 `workspace` / `org` / `workspace_id` / `org_id`；无别名、`normalize_scope`、双写、三级回退 | 待 B2 验收（T011/T012） |
| B-7 | 跨租户 / 空归属 id / 未知 scope / 已归档一律不可见，统一 404 | 部分（B1 已加空 `viewer_id` / `owner_id` fail-closed；完整口径待 B2） |
| B-8 | （N1 / D8）`project` 记忆必带 `project_owner_id`，按 `(tenant_id, project_id, project_owner_id)` 判定；缺字段 fail-closed | 待 B2 验收（T014，安全必项不得裁剪） |
| B-9 | （N2 / D7）`"default"` 不得承载 `project` 记忆：显式写 400、沉淀回落 `personal`、历史归档、地址解析 404 | 待 B2/B3 验收（T014/T021，安全必项不得裁剪） |

## C. 对 049 的消费契约（P0/P1）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| C-1 | 【049】`visible_project_keys` 按 `projects.find(...)` 构造，排除 `_id:"default"` | 待 B2 验收 |
| C-2 | 【049】成员新增 / 移除 / 归档后立即生效（动态解析），017 不监听、不缓存、不写 `projects` | 待 B2/B5 验收 |
| C-3 | 【049】成员写权限与候选端点部门子树过滤，017 不重复实现、不绕过 | 待 B2 验收 |
| C-4 | 【049】user-web 成员弹窗与 admin 项目列表保持原样，017 仅回归不破坏 | 待 B7 验收（T043/SC-9） |
| C-5 | 【049】admin `memberCount = len(member_user_ids)`，017 展示共享成员数不得改写 | 待 B4 验收 |
| C-6 | 017 详情 / 列表按 `project_id + project_owner_id` 消歧回显项目名；查不到显示「已归档/已删除」 | 待 B3/B4 验收 |
| **C-7** | **（v3 必做）** 049 `PATCH` 按 diff 落 `project.member.granted` / `project.member.revoked`（`feature="049"` → 001），admin `/audit`「记忆管理」module 可查；不改 049 语义、审计失败不阻断 PATCH | **待 B5 验收**（T032/T033/T034/T038；049 spec FR-011 与 tasks「017 C-7 增量」节已登记，本清单不重复添加） |
| C-8 | 017 不得引用 `quota_projects`、假定 `project_members` 集合或 `projects.sharing_enabled` 字段（防回归） | 待 B2–B7 验收（贯穿项） |

## D. 写入与分层（P1）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| D-1 | 显式 scope + 服务端校验；`project_owner_id` / `department_id` 一律服务端解析，客户端传值忽略 | 待 B3 验收（T019） |
| D-2 | 默认策略：单人会话有有效项目上下文 → `project`，否则 `personal`；多人 → `project`（无上下文回落 `personal`） | 待 B3 验收（T019） |
| D-3 | 同一内容写入多范围各存独立副本，不走跨范围去重 | 待 B3 验收 |
| **D-4** | **超长优先分层；仅 `tierable=false` 且 L2 超硬上限时拒绝写入并明确提示** | 待 B3 验收（口径已改写，见文末「D-4 口径修正」） |
| D-5 | 写时摘要 + 读时惰性补全两条路径都有生产注入点；缺摘要须告警，不得静默退化为全文 | 待 B3 验收（T022） |
| D-6 | 更新走增量 `$set`，保留分层 / provenance / `archived` / `project_owner_id`（修 promote 全量替换清空字段） | 待 B3 验收（T020） |
| D-7 | 写入必须 `await` motor（`replace_one` / `update_one`） | 待 B3 验收 |

## E. 会话沉淀（P1）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| E-1 | 002 `SessionEnd` → 009 → 017 链路保持，`ended_at` 幂等为唯一去重判据 | 部分（2026-10-06 链路已重构落地；v3 验收 T021/T025 待 B3） |
| E-2 | 项目上下文从 `session_doc.project_id` 取（046 三级回退），反查 `projects.user_id` 写 `project_owner_id` | 待 B3 验收（T021） |
| E-3 | 沉淀产 L0/L1/L2 + `source_session_id` / `source_type=session` | 部分（分层沉淀已落地；T022 写时摘要注入待 B3） |
| E-4 | 多人会话默认 `project`；`default` 回落 **`personal`**（不回落 department） | 待 B3 验收（T021，N2） |
| E-5 | 沉淀失败不阻塞会话结束，但必须落观测日志 | 待 B3 验收 |

## F. 检索与轨迹（P1）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| F-1 | 记忆进 RAG（005），检索前按 scope 过滤；所有调用点传完整 viewer（含部门集合） | 部分（B1 已修通 RAG 适配器路径；完整 viewer 待 B3/T023） |
| F-2 | 默认只注入 L0+L1，L2 仅显式请求；降级命中需标注 | 待 B3 验收 |
| F-3 | `retrieval_trace` 含 candidates + **非空 skipped**，原因含 `scope_invisible` / `default_project_excluded` / `missing_project_owner` | 待 B3 验收（T023） |
| F-4 | 轨迹落观测通道（非 001），按 `trace_id` 回看；高价值命中抽样进 001 | 待 B3 验收 |
| F-5 | （D4）地址往返一致仅在新值域内成立；旧段地址由迁移脚本改写持久化引用，运行时 404 | 待 B2/B3 验收（T024） |

## G. 提升与治理（P1）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| G-1 | 提升到 `department` 需 `full_access_admin` 且目标部门在 `visible_department_ids` 内 | 待 B5 验收（T035） |
| G-2 | 提升 / 部门范围写入进 001 审计，失败留痕不阻塞主流程 | 待 B5 验收（T035） |
| G-3 | 普通用户提升需审批（与 001 `portal_requests` 状态机联动） | 待 B5 验收（T035） |

## H. 生命周期与组织变更（P1/P2）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| H-1 | 衰减周期可配置（`MEMORY_DECAY_DAYS` 注入，不得硬编码 30 天） | 待 B5 验收（T036） |
| H-2 | 读取命中调用 `lifecycle.touch()` 重置计时（生产接线） | 待 B5 验收（T036） |
| H-3 | 离职 / 删号：personal 与 project 记忆失效，department 记忆保留且不依赖创建者 | 待 B5 验收（T037） |
| H-4 | 部门移动后 `visible_department_ids` 动态重算 | 待 B5 验收（T037） |
| H-5 | 049 成员移除后 `visible_project_keys` 动态重算，不固化名单 | 待 B5 验收（T037） |
| H-6 | 项目归档保留历史记忆但退出 RAG 默认检索 | 待 B5 验收（T037） |

## I. 双端功能（P1/P2）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| I-1 | admin `/memories`：指标卡 / 跨范围列表 / 筛选 / 详情抽屉 / 治理动作 | 待 B4 验收（T026，前端完全空白） |
| I-2 | admin 可见范围配置 / 策略 / 配额 | 待 B4 验收（T027） |
| I-3 | admin 独立审计视图复用 `/audit`，新增「记忆管理」module（纳入 `memory.*` 与 `project.member.*`） | 待 B4/B5 验收（T028） |
| I-4 | user「我的记忆」：双 Tab / 搜索 / 卡片 / 增删改 / 提升申请（**不含成员编辑**，归 049） | 待 B4 验收（T029） |
| I-5 | 两端共用响应契约、分页、唯一可见性判据、审计桥；不可见一律 404 | 待 B4 验收（T030） |
| I-6 | admin `get_current_admin_user` + 权限码；user `require_end_user_principal` + scope 断言 | 待 B4 验收（T030） |

## J. 契约与一次性切换（P1/P2）

| FR | v3 要求（摘要） | 状态 |
| --- | --- | --- |
| J-1 | `/api/v1/memories` 路径不变，新增 `project_id` / `project_owner_id`（只读回显）/ `department_id`；回显 `actual_scope` / `resolved_from`（无 `legacy_alias`） | 待 B3 验收（T019） |
| J-2 | `memories` schema 按设计文档 §2.2；幂等迁移脚本（dry-run / `--apply` / `--reverse` / 失败清单） | 待 B6 验收（T039） |
| J-3 | 不引用 `quota_projects` / `project_members` / `project_memories` / `organizations` 作范围主数据 | 待 B2–B7 验收（贯穿项） |
| J-4 | 全部对外文档同步新口径（017 五件套、021、契约、INDEX、049 spec/tasks） | **进行中（本任务 T044）**；旧版 100% 勾选作废 |
| J-5 | （D4）全仓一次性替换清单：`MemoryScope` / `Visibility` / `SCOPE_VISIBILITY` / `Memory` dataclass、各模块、契约与 017/021 SDD | 待 B2/B6 验收（T011） |
| J-6 | （D4）切换顺序约束：M1 代码替换与 M2 数据迁移在同一维护窗口原子切换，切换前冻结写入；回滚走 `--reverse`；S4/S7 `archived` 不自动撤销 | 待 B6 验收（T041/T042） |

## SC-1 ~ SC-15（成功判据）

| # | 可测标准（摘要） | 状态 |
| --- | --- | --- |
| SC-1 | 真实 auth 契约 + 真实 `projects` / `org_units` fixture；跨用户 personal、非成员 project、跨部门 department 三类越权全失败且 404 | 部分（B1 已通过 personal 越权项；project/department 越权待 B2/T017） |
| SC-2 | 049 增/删成员后可见性即时生效，无需改 017 数据；创建者始终可见 | 待 B2/B5 验收 |
| SC-3 | 显式写 `project_id="default"` 400、沉淀回落 `personal`、同租户他人不可见 | 待 B2/B3 验收（N2） |
| SC-4 | （D3）所在部门及全部后代可见、下级不可读上级、部门移动后集合自动变化、无 `status` 用户仍解析非空、跨租户 fail-closed | 待 B2 验收（T015/T017） |
| SC-5 | 多人会话沉淀落 `project`（含 `project_owner_id`），单人按 D-2；L0/L1 非空、可回查 | 待 B3 验收（T021/T025） |
| SC-6 | 提升后分层 / provenance / `archived` / `project_owner_id` 全保持；审计事件可查 | 待 B3 验收（T020） |
| SC-7 | RAG 默认只注入 L0+L1；`skipped` 非空且原因可归类；按 `trace_id` 回看 | 待 B3 验收（T023） |
| SC-8 | 用户停用/删号后 personal/project 不可见，department 仍对部门可见 | 待 B5 验收（T037） |
| SC-9 | 049 回归：管理端 `/projects` 有数据、四列有值、join 不丢行、`/policy` 可用；017 改动后行为不变 | 待 B7 验收（T043） |
| SC-10 | （D4）迁移脚本第二次 0 条写入；`--reverse` 还原 S1/S2/S6 且不撤销 S4/S7 `archived`；三类孤儿进清单 | 待 B6 验收（T039/T042） |
| SC-11 | admin `/memories` 与 user「我的记忆」可见性一致（同一 `visible_to`）；治理动作在 `/audit` 可查 | 待 B4 验收（T031） |
| SC-12 | 017 + 021 单测全绿、**无 monkeypatch 出契约外字段的用例**；不假定 `project_members` / `sharing_enabled` | 部分（B1 已通过「无契约外字段 mock」；全量回归待 B7/T046） |
| SC-13 | 同名 `project_id` 不同创建者的项目记忆互相不可见；历史缺 `project_owner_id` 一律不可见 | 待 B2 验收（N1/T014/T017） |
| SC-14 | （C-7）成员变更事件在 `/audit` 两 module 可查、payload 含 diff 与 actor；空 diff / 只改标题状态不发；审计桥异常 PATCH 仍成功；049 语义回归全绿 | 待 B5 验收（T032/T033/T038） |
| SC-15 | （D4）全仓旧字面量仅残留迁移脚本与历史说明；`memories` 旧 scope / 旧字段 0 条；写旧 scope / 请求旧字段 / 解析旧地址分别 400/400/404；M1 与 M2 同窗口、`--reverse` 演练通过 | 待 B2/B6 验收（T011/T042/T045） |

## D-4 口径修正（对应旧版第 48 行 CHK013 / CHK019）

> 旧版 `## 评审结论` 第 48 行把 CHK013 记为「**超限拒绝写入** → FR-11」，并称「现 100% 勾选」；同文件第 62 行 CHK019 又写「FR-11 改写后『分层为主、仅 `tierable=false` 且超 `l2_hard_max_bytes` 才拒绝』是否明确（**不再一律拒绝**）」——**旧版自身即相互矛盾**，且均不能作为本轮 Gate。
>
> **v3 FR D-4 正确口径**：超长内容**优先分层**（L0/L1/L2）；**仅当 `tierable=false` 且 L2 超硬上限（`MEMORY_L2_HARD_MAX_BYTES`）时才拒绝写入**并明确提示。`contracts/memory-context-contract.md`「FR-16 硬限制」同口径：`tierable=False` 且内容超限时抛 `MemoryTooLargeError`、**不静默截断**。「一律超限拒绝写入」为已作废的旧稿口径。

## 本轮 Gate 结论

- **不可判为通过**：B2–B7 仍在落地、D4 原子切换尚未执行，绝大多数 FR / SC 为「待 B2–B7 验收」。
- **已可确认的落地项**（仅 B1 范围）：A-2 / A-3 / A-6、A-1 的过渡版 `MemoryViewerContext`、SC-1 的 personal 越权项、SC-12 的「无契约外字段 mock」、RAG 路径非空；证据见 `tasks.md` B1 与 `spec.md` §9。
- **安全必项不得裁剪**：N1（B-8）、N2（B-9）、C-7（C-7）、D3（B-3）为 v3 强制验收项。
