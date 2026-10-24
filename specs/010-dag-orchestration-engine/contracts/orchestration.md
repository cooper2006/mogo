# Orchestration 契约（六模式）

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
  mode: graph            # 六选一，缺省 graph（044 R-11）
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
