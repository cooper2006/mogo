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
- checklist（需求质量门禁，`/speckit-checklist`）：003、004、005、006 完成（4 份，`checklists/requirements.md`，全未勾选，reviewer-owned）；007–019 待补
- clarify（OQ 消解）：001–019 全部完成（19 份），各 spec 新增 "Clarify 记录" 节 + plan "Open Questions（已 clarify 消解）"。关键消解：
  - 001：审批复用 `approval_runtime`（poll，5min 超时）；配额用 MongoDB（不引入 Redis）；PII 全局默认 + 租户可覆盖
  - 007：tenacity 既有依赖；退避 1.5s/30s/±10%/3 次；事件落 token_usage_logs
  - 008：人工介入率=审批挂起数；P50/P95 取 token_usage_logs.duration_ms；瓶颈 top-N；DashboardPage 加标签页
  - 002：独立 session_snapshots；熵 ≥3.5 + 前缀双判定；不引入 Redis；share 联动 006
  - 009：超时 5s；fail_closed 不可放行；首期仅 PreToolUse
  - 010：JSON 条件对象（禁代码 AST）；并行度 4；节点/模型重试分层；双轨迁移
  - 011：Jaccard ≥0.7 + 样本 ≥5 建 MR；14 天低采纳淘汰；与 016 共用标记位
  - 012–019：各自口径/阈值/依赖顺序已定（019 薄模式保留身份/RBAC/脱敏/审计/红线，可省审批/配额）

## 六、SDD 路径

- 既有回溯（003/004/005/006）：spec ✅ → plan ✅ → checklist ✅（本轮生成，待审阅勾选）→ 后续 `/speckit-tasks` → `/speckit-analyze`
- 缺口 P0/P1（001/002/007/008/009/010/011）：spec ✅ → plan ✅ → clarify 消解 OQ → checklist → tasks → analyze → implement → converge
- P2 后置（012–019）：spec ✅ → plan ✅（本轮补齐）→ clarify 消解 OQ → checklist → tasks → analyze → 按路线图节奏 implement
