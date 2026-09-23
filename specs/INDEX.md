# 特性规约总览（SDD Index）

本索引汇总 `specs/` 下全部特性规约，按"既有能力回溯"与"缺口新特性"分组，标注每个特性的 spec/plan 完成度、对应规划文档条目与代码位置。

> 规划文档：`docs/MOVO企业级智能体功能补强规划.md`（§1.1 既有优势 / §1.2 不重复投入边界 / §2 GAP / §3 补强清单 / §4 路线图）

## 一、既有能力回溯规约（§1.1/§1.2 优势固化）

| 编号 | 特性 | 类型 | spec | plan | 对应规划 | 主要代码位置 |
|---|---|---|---|---|---|---|
| 003 | document-ingestion-delivery | 既有回溯 | ✅ | ✅ | §1.2 文档理解+内容生成 | `services/document-parser`、`chat-api/enterprise_capabilities/content` |
| 004 | skillhub-lifecycle | 既有回溯 | ✅ | ✅ | §1.2 SkillHub+ZIP 安装 | `admin-api/skill_lifecycle`、`chat-api/skills + skill_packages` |
| 005 | knowledge-rag-research | 既有回溯 | ✅ | ✅ | §1.1 企业知识/RAG | `chat-api/knowledge`、`document-parser` 检索 |
| 006 | position-rbac-admin | 既有回溯 | ✅ | ✅ | §1.1 管理后台 RBAC | `admin-api/position_roles` |

## 二、缺口新特性规约（§2 GAP / §3 补强清单）

| 编号 | 特性 | 对应规划 | 优先级 | spec | plan |
|---|---|---|---|---|---|
| 001 | gatekeeper-governance（六层门禁） | 清单 1（§2.1） | P0 | ✅ | ✅（3 OQ 待 clarify） |
| 002 | session-versioning（会话级版本化） | 清单 6（§2.6） | P1 | ✅ | ✅ |
| 007 | llm-gateway-resilience（网关韧性） | 清单 2（§2.2） | P0 | ✅ | ⏳ |
| 008 | ops-dashboard（总览驾驶舱） | 清单 3 | P0 | ✅ | ⏳ |
| 009 | hooks-interception（Hooks 拦截） | 清单 4（§2.3） | P1 | ✅ | ⏳ |
| 010 | dag-orchestration-engine（DAG 编排） | 清单 5（§2.4） | P1 | ✅ | ⏳ |
| 011 | dream-cycle-self-evolution（自进化） | 清单 7（§2.5） | P2 | ✅ | ⏳ |

## 三、P2 规模化生态后置清单（spec 已建，plan 待补）

| 编号 | 特性 | 对应规划 | 优先级 | spec | plan |
|---|---|---|---|---|---|
| 012 | a2a-agent-gateway | 清单 8 | P2 | ✅ | ✅ |
| 013 | multi-im-entry | 清单 9 | P2 | ✅ | ✅ |
| 014 | business-semantic-index | 清单 10 | P2 | ✅ | ✅ |
| 015 | knowledge-graph-layer | 清单 11 | P2 | ✅ | ✅ |
| 016 | skill-market-hardening | 清单 12（市场强化部分） | P2 | ✅ | ✅ |
| 017 | three-scope-memory | 清单 13 | P2 | ✅ | ✅ |
| 018 | capability-asset-registration | 清单 14 | P2 | ✅ | ✅ |
| 019 | harness-elastic-config | 清单 15 | P2 | ✅ | ✅ |

> 规划清单 12 的"沉淀闭环（会话→经验→Skill）"已并入 011（Dream Cycle）；016 仅承载"市场强化"部分。

## 四、未独立拆分的后续范围

| 规划清单 | 说明 | 归属 |
|---|---|---|
| 清单 6 工作流级版本化 | GraphSpec 可执行契约 + 灰度/回滚/轨迹回放 | 002 后续 + 010 引擎 |
| 清单 12 Skill 沉淀闭环 | 会话→经验→Skill 自动沉淀 | 已并入 011 |

## 五、规约完成度统计

- spec.md：001–019 全部完成（19 份）
- plan.md：001–019 全部完成（19 份，19/19 技术契约齐全）
- checklist（需求质量门禁，`/speckit-checklist`）：001–019 全部完成（19 份，`checklists/requirements.md`，reviewer-owned）；**001/002/007–019 共 15 份已 agent 代审 + FR 回填 + 跨特性双向声明，100% 勾选达标**；003–006（既有回溯）保留原始未勾状态
- tasks（可执行任务，`/speckit-tasks`）：001、007、008 完成（P0 三份 tasks.md，含 clarify 决策 + checklist 门禁 + 故事分阶段 + 并行点 + MVP）；002/009/010/011 + P2 待补
- clarify（OQ 消解）：001–019 全部完成（19 份），各 spec 新增 "Clarify 记录" 节 + plan "Open Questions（已 clarify 消解）"。关键消解：
  - 001：审批复用 `approval_runtime`（poll，5min 超时）；配额用 MongoDB（不引入 Redis）；PII 全局默认 + 租户可覆盖
  - 007：tenacity 既有依赖；退避 1.5s/30s/±10%/3 次；事件落 token_usage_logs
  - 008：人工介入率=审批挂起数；P50/P95 取 token_usage_logs.duration_ms；瓶颈 top-N；DashboardPage 加标签页
  - 002：独立 session_snapshots；熵 ≥3.5 + 前缀双判定；不引入 Redis；share 联动 006
  - 009：超时 5s；fail_closed 不可放行；首期仅 PreToolUse
  - 010：JSON 条件对象（禁代码 AST）；并行度 4；节点/模型重试分层；双轨迁移
  - 011：Jaccard ≥0.7 + 样本 ≥5 建 MR；14 天低采纳淘汰；与 016 共用标记位
  - 012–019：各自口径/阈值/依赖顺序已定（019 薄模式保留身份/RBAC/脱敏/审计/红线，可省审批/配额）

## 五（补）、checklist 暴露的缺陷修正记录（✅ 已修，2026-07-08）

以下 5 处由 checklist 审阅暴露的 spec 缺陷已在对应 spec 正文订正，reviewer 审阅时直接确认即可：

| 缺陷 | 所在 | 类型 | 修正结果 |
|---|---|---|---|
| 001 Non-Goals 特性编号引用错配 | 001 CHK011 | 一致性 | ✅ 已订正：LLM 韧性→007、DAG→010、自进化→011、会话版本化→002（原误写 002/003/004/005） |
| 016 FR-4 与 clarify 矛盾 | 016 CHK006 | 一致性 | ✅ 已对齐：FR-4 + US3 改为"首期按租户，按比例/用户为后续扩展" |
| 017 FR-3 vs FR-5 默认策略矛盾 | 017 CHK002 | 一致性 | ✅ 已统一：按"单/多人会话"区分默认范围（单人 personal、多人 workspace） |
| 008 成本预测 N 值未定 | 008 CHK013 | 完整性 | ✅ 已补：N = 4 期（可配置 forecast_periods）+ clarify OQ-5 |
| 010 表达式语法错误策略未定 | 010 CHK013 | 完整性 | ✅ 已补：默认 fail_closed（跳过 + 审计）+ clarify OQ-5 + FR-4 同步 |

## 五（补2）、P0/P1/P2 checklist 评审 + FR 回填记录（2026-07-08，已全部消解）

按 `/speckit-checklist` 语义 agent 代审 15 份 checklist（001/002/007–019），**只勾真正达标项**；同时把 clarify 已定但未进 FR 正文的值 + 可消解的边界缺口回填进 spec。随后在"跨特性双向声明轮"中，把 15 份剩余未勾项（跨特性两两关系 + 特性自身缺口）全部消解，**现 15 份 checklist 全部 100% 勾选**（003–006 为既有回溯、未代审，保留原状态）。

| 特性 | 勾选/总数 | 回填消解项 | 后续消解项（跨特性双向声明轮已清） |
|---|---|---|---|
| 001 gatekeeper | 15/18 | 逐层返回码、级联/回落、配额 MongoDB+UTC、预设组结构、审批 5min+poll+超时动作、R4 全能力管理员、删层重排、脱敏请求体前 | 25格矩阵完整表、001↔006、001↔019 |
| 007 llm-resilience | 10/15 | 主/备显式声明、降档=文本档位、agent_id 维度、成本单价取 008 MODEL_PRICES、退避默认值、仅文本模型、全故障聚合错误 | 降级原因枚举、007↔001 配额、重试取消、切换计量归属 |
| 008 ops-dashboard | 13/15 | 分摊字段、去重键、异常枚举、周期、人工介入率、P50/P95 源、top-5、容差、007 failover 字段对齐、最小角色、分维空态、时区、下钻脱敏 | 契约边界、月同比 |
| 002 session-versioning | 12/16 | 触发条件、resume seq、share 权限转移、co-presence 冲突、秘密判定、独立快照集合、审计字段、解引用定义、附件边界、乐观锁、share 失效、离线贡献 | 002↔001/009/011/005 |
| 009 hooks-interception | 11/16 | 三规则语义、作用域叠加、fail_closed、首期 PreToolUse、超时 5s、observe 强度、解析失败三类、拒绝语义、生效时机、求值顺序 | 五事件数据、009↔001/002/019、延迟预算 |
| 010 dag-orchestration | 13/16 | 节点数据传递、并发度 4、跳过追溯、阻塞闭包、JSON 条件、版本字段、环路径格式、双轨、语法错误、原子语义、supervisor 传播 | 010↔007/009/002、跨层并发预算 |
| 011 dream-cycle | 12/16 | 片段字段、双指标算法、测试定义、采纳率口径、friction 默认、MR 不直接合入、草稿vsMR、恢复路径、堆积上限、去重、生效范围、生成侧门槛 | 011↔004/002/016/010 |
| 012 a2a-agent-gateway | 13/15 | AgentCard 字段+skills[]、JSON-RPC 方法名、agent 路由、客户端超时/failover、Dify 优先、卡刷新触发、同租户边界、双向审计、错误码映射、幂等、鉴权枚举、外部注册 | 012↔001/018 |
| 013 multi-im-entry | 13/15 | 映射粒度 1:1、长响应分段、能力=Web 全量、租户级开关、首期飞书、纯文本+基础卡片、会话映射、@bot 主体、撤回不回改、离线降级、凭据注入、1会话1IM | 013↔001/002 |
| 014 business-semantic-index | 12/15 | 4 类实体+schema 可配、定时拉取、联查键、来源三级、首期 CRM、PII 走 001、数据源不可用、全量首刷、对齐失败降级、副本延迟标注 | 014↔005/015/001 |
| 015 knowledge-graph-layer | 12/15 | 实体/关系类型、跳语义+3 跳、三类约束、查询入口、迁移阈值、断裂判定、合并策略、防环、低置信门槛、矛盾不阻断、融合裁决 | 015↔005/014/001 |
| 016 skill-market-hardening | 13/15 | 异常口径、打分权重、租户灰度、降权行为、效果分口径、20% 回滚、0.4/7天、数据源、最小样本、稳定版本、恢复路径、多版本归集 | 016↔004/011 |
| 017 three-scope-memory | 12/15 | Workspace 粒度、默认策略、授权角色、衰减口径、三级可见性、001 治理点、离职处置、超限拒绝、多范围各存、检索过滤 | 017↔005/002/006 |
| 018 capability-asset-registration | 12/15 | 契约四段、扫描目标、3 态、owner 粒度、自动/人工分工、多对多 skill_refs、下线审批、旧版可查、去重键、视图下钻、owner 转移 | 018↔004/012/001 |
| 019 harness-elastic-config | 13/15 | 厚/薄层集合、三维 profile、审计粒度+超时、默认厚、优先级、可省/不可省、最小审计四元组、工具调用级生效、配置权、过渡挂载、中途切换 | 019↔001/009 |

**共性结论（2026-07-08 跨特性双向声明轮后）**：15 份 checklist 的剩余未勾项已全部消解——①**跨特性两两关系**在各 spec 的"跨特性关系（被依赖方视角）"节**双向声明**（001↔006/009/012/013/018/019，002↔009/011/013/017/005，004↔011/016/018，005↔014/015/017，006↔017/019，007↔010/001/008，009↔010/019，012↔018，014↔015）；②**特性自身缺口**回填 FR（001 的 25 格矩阵表、007 降级原因/取消/计量归属、009 五事件数据/延迟预算、010 跨层并发预算、008 契约边界）。**现 15 份 checklist 全部 100% 勾选，19 份 spec 契约无冲突，达 implement 就绪。**

## 六、SDD 路径

- 既有回溯（003/004/005/006）：spec ✅ → plan ✅ → checklist ✅ → 后续 `/speckit-tasks` → `/speckit-analyze`
- 缺口 P0（001/007/008）：spec ✅ → plan ✅ → clarify ✅ → checklist ✅ → tasks ✅（本轮补齐）→ analyze → implement → converge
- 缺口 P1（002/009/010/011）：spec ✅ → plan ✅ → clarify ✅ → checklist ✅（已评审勾选）→ tasks ⏳ → analyze → implement → converge
- P2 后置（012–019）：spec ✅ → plan ✅ → clarify ✅ → checklist ✅（已评审勾选）→ tasks ⏳ → 按路线图节奏 implement
