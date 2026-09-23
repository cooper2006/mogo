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

## 三、已声明但未独立拆分的后续范围

| 规划清单 | 说明 | 归属 |
|---|---|---|
| 清单 6 工作流级版本化 | GraphSpec 可执行契约 + 灰度/回滚/轨迹回放 | 002 后续 + 010 引擎 |
| 清单 12 Skill 市场强化 | 版本灰度/回滚/低质量自动标记 | 004 后续 + 011 沉淀闭环 |
| 清单 8/9/10/11/13/14/15 | A2A 网关、多 IM、业务语义索引、知识图谱、Memory 粒度、能力资产化、Harness 弹性 | P2 后置，未建特性目录 |

## 四、规约完成度统计

- spec.md：001–011 全部完成（11 份）
- plan.md：001、002、003、004、005、006 完成（6 份）；007–011 待补
- 待 clarify 的 OQ 集中在：001（审批表/配额存储/PII 粒度）、002（快照存储/熵阈值/co-presence/share 鉴权）、005（个人知识分享范围/重排）、006（权限码联动/能力维度）

## 五、SDD 路径

- 既有回溯（003/004/005/006）：spec ✅ → plan ✅ → 后续 `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze`
- 缺口新特性（001/002）：spec ✅ → plan ✅ → clarify 消解 OQ → checklist → tasks → analyze → implement → converge
- 缺口新特性（007–011）：spec ✅ → plan ⏳（下一步补齐）→ 同上
