# Orchestration 契约（七模式）

> 本文档是 `specs/010-dag-orchestration-engine/quickstart.md` §5 引用的权威形态说明，
> 由 `specs/044-multi-agent-modes` 在实现期补建：010 原本把模式清单写在 quickstart §5，
> 并未形成独立契约文档，044 R-10 补上这一块并扩为六模式。
>
> 解析入口：`services/chat-api/app/orchestration/loader.py::load_orchestration_document`
> （返回 `LoadedOrchestration`）；执行入口：
> `services/chat-api/app/orchestration/dispatch.py::execute_orchestration`。

## 1. 文档顶层

```yaml
orchestration:
  id: competitor_deep_dive
  version: 1.0.0
  mode: graph            # 七选一，缺省 graph（044 R-11；052 扩 team 见 §7）
  max_concurrency: 4     # 010 既有；round_robin 复用为候选并发上限
  timeout: 1800
  retry: {max_attempts: 2, backoff: exponential, base_seconds: 5}
  select: highest_score            # round_robin 专属
  arbiter: adjudicator             # debate 专属（可选）
  max_rounds: 3                    # debate 专属
  convergence_threshold: 0.8       # debate 专属
  similarity_threshold: 0.9        # debate 专属

nodes: [...]
```

节点 `mode` 缺省继承文档 `mode`；显式声明的节点按自己的模式分发。

## 2. 四种 010 既有模式

`sequential` / `supervisor` / `hybrid` / `graph` 形态不变，仍走
`DagEngine`（`run_sequential` / `run_graph`）与
`supervisor.run_hybrid`。`graph` 分支在
`competitor_deep_dive.py` 上验证过行为不变（044 FR-010 / FR-012）。

## 3. round_robin（轮询择优，044 FR-002/FR-003）

文档级：每个 graph 节点视为同一逻辑任务的候选，按 `max_concurrency`
并发运行，按 `select` 策略选一。

```yaml
orchestration:
  id: pick_winner
  mode: round_robin
  max_concurrency: 4
  select: highest_score        # first_success | highest_score(默认) | majority
nodes:
  - id: candidate_a
    mode: graph                # 文档级 round_robin 下节点不必写 mode
    prompt: 用模型 A 总结
    score: 0.9                 # 可选，0..1；无则按策略回退
  - id: candidate_b
    prompt: 用模型 B 总结
```

节点级（作为 `graph` 的子节点，FR-009/R-16）：

```yaml
nodes:
  - id: picker
    mode: round_robin
    instances:                          # 候选实例覆盖，仅允许 model/temperature/prompt/label
      - {model: m1, label: fast, prompt: 简短结论}
      - {model: m2, label: thorough, prompt: 详尽结论}
    select: first_success
```

`instances` 中的候选**只允许**覆盖 `model` / `temperature` / `prompt` / `label`；
出现 `retry` / `conditions` / `condition` / `depends_on` / `mode` 会在加载期
fail-closed（`RoundRobinError` → `OrchestrationLoadError`，R-1）。空或缺失 =
单候选（label 缺省 `default`）。

策略语义（R-2/R-3/R-14）：`highest_score` 取 `payload.score`（夹取 0..1）；
部分候选有分时只在有分之间比较；全部无分回退 `first_success`（记 `no_score`）；
有分候选全失败而无分候选成功 → 采用无分候选（记 `scored_all_failed`）。
`majority` 按文本归一化（小写 + 去空白）计数，无多数回退 `first_success`
（记 `no_majority`），平票取最先完成（记 `majority_tie`）。

## 4. debate（辩论对质，044 FR-005/FR-006/FR-007）

文档级：解析 role 标签得到 pro / con / 可选 arbiter 三个节点。

```yaml
orchestration:
  id: pick_or_fold
  mode: debate
  max_rounds: 3
  convergence_threshold: 0.8
  similarity_threshold: 0.9
  arbiter: adjudicator          # 可选；声明则必须有 role=arbiter 节点
nodes:
  - id: pro
    role: pro
    prompt: 论证做这件事的收益
  - id: con
    role: con
    prompt: 论证这件事的风险
  - id: adjudicator
    role: arbiter
    prompt: 裁决谁占优
```

每轮先 pro 后 con，双方通过
`context["debate"] = {round, side, opponent_previous}` 读取对方**上一轮**输出
（R-4，局部字典不污染全局 context）。三类终止条件（R-6 之外补充）：

1. 轮次上限（`max_rounds`，缺省 3；越界钳制 1..10 并记 `clamped`）；
2. 仲裁置信度 `>= convergence_threshold`（缺省 0.8）；
3. pro 与 con 各自连续两轮输出 jaccard 相似度 `>= similarity_threshold`
   （缺省 0.9）。

未声明 arbiter 时 `conclusion` 取最后一轮 pro 输出、`confidence=None`（不伪造）。
`pro` / `con` / `arbiter` 指向不存在的节点在**加载期** fail-closed（FR-007/R-7）。
任一方失败立即终止并整体 failed（R-15）。

## 5. 事件与可解释性（R-9）

round_robin / debate 作为节点时，事件以该节点为 `item_id` 产生一层
`item.started` / `item.completed`（R-16）；择优依据通过
`payload.selection = {strategy, chosen, fallback_reason}` 与
`payload.candidates` / `payload.rounds` 明细暴露，不派生嵌套
`item.*` 子事件。

## 6. human_approval（转人工节点，050 FR-001..FR-006）

`human_approval` 是**节点类型**，不是文档模式：`VALID_MODES` 不扩展，任何
`graph` 模式的图中可嵌入审批节点（050 首期仅 graph 模式支持，其它模式声明
审批节点 → 加载期 fail-closed）。节点声明：

```yaml
nodes:
  - id: legal_review
    type: human_approval          # 节点类型（050，区别于文档 mode）
    approver: u-legal             # 必填：审批人 user_id（fail-closed 校验存在）
    timeout: 86400                # 可选：秒，默认 24h，钳制 60..30d
    on_reject: rework             # 可选：驳回分支节点（必须是本节点的直接依赖）
    prompt: 合同审查请审批          # 可选：审批说明（进待办与审计）
    depends_on: [draft]
  - id: rework
    depends_on: [legal_review]    # 驳回分支：normal 路径需在节点上声明
                                  #   condition: {op: "!=", left: {var: legal_review.decision}, right: rejected}
```

**运行状态机**（`orchestration_runs` 集合，050 run_store）：

非终态 `running | awaiting_approval | needs_review`，终态 `completed | rejected | timeout | cancelled | failed`（`needs_review` 经 POST /runs/{id}/review 的 skip/terminate/reassign 处置，非终态）。

* 执行到审批节点：写运行快照（checkpoint）→ 持久化待办 → 运行置
  `awaiting_approval` → 释放协程（**不在进程内等待**，重启不丢）。
* 批准：消费待办（原子一次）→ 从挂起点续跑，已完成节点零重跑。
* 驳回：未声明 `on_reject` → 运行 `rejected`（理由必填进审计）；声明了
  `on_reject` → 审批节点记 `skipped`，分支执行，其它直接依赖被注入
  `decision != rejected` 守卫而跳过。
* 超时：恢复扫描把过期待办置 `timeout`，审批节点 `failed`，下游按 010 FR-6
  阻塞（**fail-closed，无超时自动批准**）。
* 恢复：单活租约（`lease_owner` / `lease_until`），运行中 worker 崩溃 →
  `needs_review` 由管理员经 POST /runs/{id}/review 的 skip/terminate/reassign 处置，不静默重跑（非终态，见状态机）。
* 定义版本锁定：运行创建时内嵌定义全文，挂起期间改定义不影响在途运行。
* 票据两段式：持久化待办在 DB，决策瞬间经 `ApprovalRuntime` 签发并即时消费短
  TTL（5min）票据——001 的一次性/审批分离语义不变。票据存 `ApprovalRuntime` 进程内字典，签发与消费在同一次决策请求内闭环，故不依赖跨进程票据持久化（重启不丢待办、不遗留未消费票据）。
* 审批与决策全审计（挂起/批准/驳回/超时/改派/取消，含运行 ID/节点/决策人/
  理由），可从运行 ID 还原决策序列。

## 7. team（团队协作，052 FR-001..FR-006）

`team` 是**第七种文档模式**：`VALID_MODES` 扩展为七模式，任何模式不默认改
变（未声明 mode 仍默认 `graph`）。领导节点拆解任务 → 成员执行 → 团队黑板 →
领导验收（accept/rework 循环）→ 人工接管（050 消费）。文档级声明：

```yaml
orchestration:
  id: team_contract_demo
  version: "1"
  mode: team                # 第七模式
  max_concurrency: 4        # 成员并发上限（graph 同口径）
  leader: lead_node         # 可选：领导节点 id（默认第一个节点）
  members: [member_a, member_b]   # 可选：成员节点 id 子集（默认 = 全部非领导节点）
  max_review_rounds: 3      # 可选：验收轮次上限，默认 3，钳制 1..5
  max_reassign: 3           # 可选：重指派上限，默认 3，钳制 1..10

nodes:
  - id: lead_node
    payload: {skill: decomposer}   # 领导拆解（LLM，prompt 由 YAML 承载）
  - id: member_a
    payload: {skill: analyst, employee_id: emp-finance}  # 成员可引用 051 员工
  - id: member_b
    payload: {skill: writer}
```

**执行语义**：

* **拆解指派**：领导产出 `{assignments: {member_id: subtask}}` 分派表；引用不
  存在成员 → 加载期/执行期 fail-closed（044 arbiter 校验同风格）。
* **成员执行**：成员按分派执行（并发受 `max_concurrency`），经 050 运行持久化
  checkpoint + 恢复驱动；单成员失败不拖垮团队，重指派计数受上限。
* **团队黑板**：运行级键值材料区，条目含作者/版本/内容；键以作者前缀做
  命名空间隔离（跨成员同键不覆盖），旧版本保留。
* **验收循环**：领导判 `accept` 完成 / `rework`（附意见）退回对应成员重做；
  轮次上限默认 3（1..5 钳制，越界钳制记事件）；达上限仍不合格 → 团队运行
  `failed`（**fail-closed，不静默接受**）。领导判定 JSON
  `{verdict: accept|rework, opinion, target_member}`，解析失败 fail-closed。
* **人工接管**：声明接管点（`takeover:`）命中 → 经 050 `human_approval` 挂起
  （`awaiting_approval`），人工决策覆盖领导判定，决策全审计。
* **事件**：team 作为节点时事件以该节点为 `item_id` 一层（044 R-9 口径），
  轮次/黑板明细收 `payload`，不派生嵌套 `item.*` 子事件。
* **子节点原子性**：team 节点可作为 graph 子节点，对外一次原子成功/失败
  （044 R-16 口径）。

