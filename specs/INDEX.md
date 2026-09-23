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
- checklist（需求质量门禁，`/speckit-checklist`）：003、004、005、006 完成（4 份，`checklists/requirements.md`，全未勾选，reviewer-owned）
- 待 clarify 的 OQ 集中在：001（审批表/配额存储/PII 粒度）、002（快照存储/熵阈值/co-presence/share 鉴权）、005（个人知识分享范围/重排）、006（权限码联动/能力维度）、007（退避默认值/事件 collection）、009（超时阈值/fail_closed 默认）、010（表达式语言/并行度/迁移双轨）、011（friction 阈值/相似度算法/MR 阈值）
- 各 checklist 标记的跨特性口径对齐项（003↔001/005、004↔006/001/016、005↔002/003/001、006↔001/004/019）建议在 clarify 阶段统一消解

## 六、SDD 路径

- 既有回溯（003/004/005/006）：spec ✅ → plan ✅ → checklist ✅（本轮生成，待审阅勾选）→ 后续 `/speckit-tasks` → `/speckit-analyze`
- 缺口 P0/P1（001/002/007/008/009/010/011）：spec ✅ → plan ✅ → clarify 消解 OQ → checklist → tasks → analyze → implement → converge
- P2 后置（012–019）：spec ✅ → plan ✅（本轮补齐）→ clarify 消解 OQ → checklist → tasks → analyze → 按路线图节奏 implement
