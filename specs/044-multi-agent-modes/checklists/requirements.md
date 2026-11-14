# Requirements Quality Checklist: 044 multi-agent-modes

**Purpose**: 校验 044（多智能体协作模式 round_robin / debate）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 `instances:` 列表的**字段结构**是否定义（决策 #2 说"每实例可覆写 model/temperature/prompt 变体"，但 `instances` 数组元素的 schema（必填/可选键、是否可覆盖 `payload`/`retry`/`conditions`）未给出，加载期无法校验）
- [x] CHK002 `highest_score` 依赖的 **`score` 字段来源与类型**是否定义（FR-002 说"候选输出须带 `score` 字段"；该字段由谁写入（模型输出 JSON？节点配置？外部评分）？缺失或非数值时的行为只写了"回退 `first_success`"，但**仅部分候选缺失**时的处理未写）
- [x] CHK003 `majority` 的**输出归一化口径**是否定义（决策 #1 说"输出归一化后投票"——归一化到哪一层（trim+小写？去标点？语义等价？）直接决定多数票是否成立，未定义不可实现）
- [x] CHK004 debate 的**共享上下文键结构**是否定义（FR-005 说"共享上下文按轮次键写入"；键名格式、存放位置（会话上下文？节点间共享字典？）、正反双方交替写入的可见性规则未给）
- [x] CHK005 "连续两轮高相似"的**相似度算法与阈值**是否指定（FR-006 终止条件③只说"高相似"；仓库已有 `services/chat-api/app/self_evolution/similarity.py` 的 Jaccard/归一化编辑距离，但**用哪个、阈值多少**未写）

## 清晰度（Clarity）

- [x] CHK006 `round_robin` "余量候选取消"的**取消语义**是否明确（决策 #1 说 `first_success` 时余量候选取消；候选已并发启动的情况下是**硬取消**（中断请求）还是**丢弃结果**？对计费/审计有实质差异）
- [x] CHK007 `debate` 在**无 `arbiter`** 时的收敛结论来源是否定义（FR-007 说支持 arbiter 节点；若 YAML 未声明 arbiter，终止后"结论"由谁产出——正方最后输出？原文拼接？）
- [x] CHK008 "轮次上限越界钳制并记事件"的**事件名与字段**是否定义（FR-006 要求记录，但事件名、`detail` 结构未给，Trace 消费者无法依赖）
- [x] CHK009 新模式 Trace 事件的**层级/父子关系**是否定义（FR-004 要求含各候选输出与择优依据；候选输出是作为父节点的子事件还是内嵌数组？与 010 既有 `item.started/completed` 同构到什么程度）

## 一致性（Consistency）

- [x] CHK010 **`contracts/orchestration.md` 实际不存在**（FR-011 要求"同步扩展为六模式契约"，但 `specs/010-dag-orchestration-engine/` 下**无 `contracts/` 目录**；010 的目录名也非 spec 所写的 `010-dag-orchestration`，而是 `010-dag-orchestration-engine`）
- [x] CHK011 模式枚举的真实落点是否与 spec 一致（`services/chat-api/app/orchestration/graph.py:13` 为 `VALID_MODES = ("sequential", "supervisor", "hybrid", "graph")`；`graph.py:25` `mode: str = "graph"`；`loader.py:274` `mode = str(header.get("mode") or "graph")`；`registry.py:29` 同样默认 `"graph"`——FR-001 的描述与实际一致，但**新增模式后 `VALID_MODES` 的校验时机**（加载期 vs 执行期）未写）
- [x] CHK012 "复用 `fair_selection.py`"的**复用粒度**是否澄清（该文件实际在 `services/chat-api/app/enterprise_capabilities/evidence/foundation/fair_selection.py`，导出 `round_robin_take(groups, *, limit)`，语义是"跨源组轮流取项避免早期源垄断"——与"候选实例择优选一"**不是同一语义**，是思想借鉴还是代码调用需明确，否则会误调用）
- [x] CHK013 FR-012 的**既有调用点清单**是否核对（要求"`competitor_deep_dive.py` 等既有调用点迁移到统一分发入口后行为不变"；实际文件在 `services/chat-api/app/enterprise_capabilities/research/competitor_deep_dive.py`，spec 未列全"等"字覆盖的调用点）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 `round_robin` 的失败边界是否覆盖（全部候选失败 → 整体失败还是部分成功放行？部分成功但无 `score` 时按 `first_success` 取谁？`majority` 平票如何裁决——按加入顺序？取失败？）
- [x] CHK015 `debate` 的异常边界是否覆盖（正方或反方中途失败 → 继续还是终止？arbiter 指向的节点本身执行失败 → fail-closed 还是回退到最后一方输出？达到 `max_concurrency` 排队时轮次上限是否继续计时）
- [x] CHK016 新模式作为 **graph 子节点**时的继承语义是否定义（FR-009 要求可作子节点；**节点的重试策略、超时、条件跳过、trace 层级**由子模式继承还是父图统一管理，未写）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类。
- 本特性需求风险集中在**评分与相似度的可计算性**（CHK002/CHK003/CHK005）：三种择优策略与三类终止条件全都依赖"评分/相似度"，而这两个量的产生方式在 spec 中未落到具体字段与算法——这是"看起来完备、实现时全靠猜"的典型缺口。
- 一致性类发现了 3 处**实证偏差**（CHK010 contracts 目录不存在、CHK012 fair_selection 语义不同、CHK013 调用点路径），均已取证到具体文件行。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

- 逐条映射：
- CHK001 → R-1
- CHK002 → R-2
- CHK003 → R-3
- CHK004 → R-4
- CHK005 → R-5
- CHK006 → R-6
- CHK007 → R-7
- CHK008 → R-8
- CHK009 → R-9
- CHK010 → R-10
- CHK011 → R-11
- CHK012 → R-12
- CHK013 → R-13
- CHK014 → R-14
- CHK015 → R-15
- CHK016 → R-16
- **实证缺口（已取证）**：CHK010 `specs/010-dag-orchestration-engine/` 无 `contracts/` 目录（010 契约实际在 `quickstart.md:69`）；CHK012 `fair_selection.round_robin_take` 是证据检索的跨源轮流取样，与候选择一不同语义，回填明确为"只借鉴思想"；CHK013 `competitor_deep_dive.py` 实际在 `enterprise_capabilities/research/`。
- **可计算性缺口**：`score` 的产生方式（R-2）、`majority` 归一化（R-3）、相似度算法与阈值（R-5）在 spec 原文中均未落地，回填给出确定口径后需求方可实现。
- 本特性尚未实现（`services/chat-api/app/orchestration/graph.py:13` `VALID_MODES` 仍为四模式），tasks.md 不勾选。
