# DSH 0.1.7-rc.2 Skill Catalog 未注入模型请求 — 定位报告

**状态**：**已定案并已修复。** 根因经官方源码仓库交叉验证确认；修复已实施并通过全量回归。
**结果**：`services/chat-api/dsh/runtime-host` node 测试 **87/87 全通过**（修复前 84 pass / 3 fail）。

---

## 0. 结论（经官方源码交叉验证）

**根因（已定案）**：ASKAI 的 `buildAskaiHostOverlay` **未透传 web-app patch 对 `tool-skill` / `skill-filesystem` 的 `disabled: true` 指令**，导致 host 平面（`dsh-base`）的 `tool-skill` 仍然挂载。它与 preset 内 `tool-skill` 形成**同名工具遮蔽（same-name shadow）**，而 DSH 的可见性判定使用严格对象身份比较：

```ts
// packages/skill/tool-skill/src/index.ts:220
const toolVisible = ctx.tools.get(skillTool.name, agent) === skillTool
```

`ctx.tools.get('skill', agent)` 解析到的那份**不是**执行钩子的插件实例所注册的 `skillTool`，故 `toolVisible` 为 `false` → 走 `{ skills: [], complete: true }` → catalog 静默不注入。

**这是 ASKAI 侧的 overlay 缺陷，而非 DSH 缺陷。** DSH 的行为是明确设计，官方文档与测试均有记载。

### 0.1 DSH 官方设计（`dsh-v0.1.7-rc.2`）

官方在 **host 平面显式禁用** `tool-skill`，交由 preset 挂载。`dsh-web-app/cordis.patch.yml`（L471-481）：

```yaml
# The `skill` REGISTRY stays in the host plane. It is host+per-scope layered
# (the tools-registry shape): deployment-level providers — repository plugins,
# a host skill-filesystem row — register into its global layer, while a preset's
# `skill-filesystem` registers into that preset's layer, and each agent reads the
# merged catalog its scope chain selects. Only the per-agent rows move behind
# presets: the base host `skill-filesystem` row is disabled here (presets own local
# discovery), and `tool-skill` is what a preset mounts to give its agent the
# catalog and loader at all.

- id: skill-filesystem
  disabled: true

- id: tool-skill
  disabled: true
```

README 亦明确：

> the visibility check compares against the **exact tool definition this plugin registered**, so a **scoped same-name shadow removes both the schema and its guidance**; the plugin works mounted globally or inside one agent's composition.

官方测试 `tests/tool-skill.spec.ts:769` `'does not attach shipped catalog guidance to a scoped same-name tool shadow'`：

```ts
expect(ctx.tools.get('skill', agent)).not.toBe(ctx.tools.get('skill'))
expect(await composePrefixForAgent(ctx, agent)).toEqual([])   // catalog 为空
```

### 0.2 本项目实测

| 检查项 | 结果 | 期望 |
|---|---|---|
| web-app patch 是否携带禁用指令 | `{"id":"tool-skill","disabled":true}` ✅ 携带 | 携带 |
| ASKAI overlay 是否透传该禁用 | ❌ **丢失**（overlay 的 disabled 行仅 `hmr`、`session-title-llm`） | 透传 |
| 挂载 preset 前 root 是否已有 `skill` 工具 | **YES**（异常，本应被禁用） | NO |
| `ctx.tools.get('skill', agent) === ctx.tools.get('skill')` | `false` | — |
| `agent/pre-step` 是否触发 | 触发（`kind=enter messages=2`） | 触发 |
| session 内 `skill-catalog` 事件数 | **0** | ≥1 |

### 0.3 修复方案（已实施）

**改动**：`src/official-host/overlay.mjs`

1. 新增 `disabledHostRows(webAppPatches)`：从 web-app patch 中提取**顶层 `{ id, disabled }` 行**（仅顶层，`insert` 内的 UI 行不参与 host 装配）。
2. `buildAskaiHostOverlay` 的返回数组改为先输出**顶层禁用行**：ASKAI 自有两项（`hmr`、`session-title-llm`）+ 官方透传行，以 Map 去重（ASKAI 自有优先）。
3. 禁用行**不经 `planOverlayRows`** 处理——该函数会把已存在的 id 降级为只带 `config`，从而丢弃 `disabled` 语义。

**效果**：overlay 顶层禁用行由 2 → **26**，其中新增 24 项官方透传（`tool-skill`、`skill-filesystem`、`tool-bash`、`tool-fs`、`tool-jobs`、`tool-subagent*`、`tool-web`、`agent-instructions`、`plan-mode`、`tool-todo`、`tool-workflow`、`tool-ralph` 等）。

**验证结果**：

| 检查项 | 修复前 | 修复后 |
|---|---|---|
| 挂载 preset 前 host 平面 `skill` 工具 | 存在（异常） | **`undefined`（正确）** |
| session 内 `skill-catalog` 事件数 | 0 | **1** |
| agent scope 能力工具（bash/read/write/subagent 等 11 项） | 全可用 | **全可用（无丢失）** |
| node 测试 | 84 pass / 3 fail | **87 pass / 0 fail** |
| composition 测试 | 9/9 | 9/9 |
| 契约测试（chat-api） | 5/5 | 5/5 |
| host 启动 | OK | OK（`kernelVersion:0.1.7-rc.2`） |

**关于 `askai-enterprise` preset**：修复后该 preset 的 `snapshot` 为空（不发现 workspace `.agents/skills/`）。经核验这是**正确行为**——其 `preset.yml` 描述为"不暴露本地代码、文件系统或 Shell 能力的普通会话"，本就不应获得本地目录发现能力。修复前 host 平面 `skill-filesystem` 的兜底反而让企业会话意外获得该能力，属偏差。故**不为该 preset 补挂 `skill-filesystem`**。

**未受影响**：chat-api 侧 `tests/dsh_runtime` 另有 5 项 `real_dsh` gateway Timeout（v0.1.6 基线同类失败），与本问题非同一根因，仍待处理。

---



## 1. 环境

| 项 | 值 |
|---|---|
| Node | v24.18.1 |
| `@deepseek-ai/dsh` | 0.1.7-rc.2 |
| `@deepseek-ai/dsh-tool-skill` | 0.1.7-rc.2 |
| `@deepseek-ai/dsh-agent-loop` | 0.1.7-rc.2 |
| `@deepseek-ai/dsh-skill` | 0.1.7-rc.2 |
| `@deepseek-ai/cordis` | 4.0.4（0.1.7 要求 `~4.0.4`） |
| 升级前 | 0.1.6-alpha.1（该断言在 0.1.6 下通过） |

## 2. 失败现象

三项断言失败，均期望模型请求体中出现 skill catalog 内容：

| 测试文件 | 行 | 断言 |
|---|---|---|
| `tests/official-code-enterprise-e2e.test.mjs` | 129 | `assert.match(JSON.stringify(modelCalls[0]), /verified-workflow/)` |
| `tests/official-skill-profile-e2e.test.mjs` | 119 | `assert.match(JSON.stringify(calls[0]), /available_skills/)` |
| `tests/runtime-capability-admission.test.mjs` | — | 期望 `/installed-audit/` 出现 |

三者均在 workspace 下创建 `.agents/skills/<name>/SKILL.md`，期望该 skill 被 catalog 广告给模型。

实测 `modelCalls[0]` 的消息组成为：

```
role=user    source=user             len=124
role=user    source=runtime-context  len=4195
```

`system-reminder` / `available_skills` / `skill-catalog` 均缺席；`call0.system`（2738 字符）亦不含 skill 内容。

持久化层面同样确认：session 事件中 `user/message` 仅有 `source=user` 与 `source=runtime-context` 两条，**`source.kind === 'skill-catalog'` 的事件数为 0**。

## 3. 已验证通过的守卫（逐条实测）

DSH 0.1.7 `dsh-tool-skill` 的 catalog 注入钩子位于 `agent/pre-step`，核心逻辑：

```js
ctx.on("agent/pre-step", async ({ agent, messages, signal }, next) => {
  const decision = await next();
  if (decision.kind === "reject") return decision;
  const snapshot = ctx.tools.get(skillTool.name, agent) === skillTool
    ? await ctx.skills.snapshot({ cwd: agent.session.header.cwd, signal, scope: agent })
    : { skills: [], complete: true };
  if (!snapshot.complete) return decision;
  const skills = snapshot.skills.filter(isModelInvocable);
  const entries = catalogSourceEntries(skills, catalogDescriptionMaxLength);
  const digest = digestCatalogEntries(entries);
  const history = catalogHistory(agent);
  const existing = catalogMessage(decision.messages);
  if (history.visibleDigest === digest) return ...;
  if (existing !== undefined && ...) return decision;
  if (!history.published && skills.length === 0) return decision;
  const catalog = history.published ? renderCatalogUpdate(entries) : renderCatalogMessage(entries);
  return { ...decision, messages: existing === void 0
    ? [...decision.messages, catalog]
    : decision.messages.map(m => m.id === existing.message.id ? catalog : m) };
});
```

逐条验证结果：

| 守卫 | 实测结果 | 判定 |
|---|---|---|
| `ctx.tools.get('skill', agent)` 存在 | 返回工具对象，`name === 'skill'` | 通过 |
| 工具实例身份 `=== skillTool` | 解析路径唯一（见 §4），无模块重复 | 通过 |
| `agent.session.header.cwd` 正确 | 等于 workspace 绝对路径 | 通过 |
| `snapshot.complete` | `true` | 通过 |
| `snapshot.skills` 含 workspace skill | `["codexhost-delegation","evolver","tabbit","verified-workflow"]` | 通过 |
| `isModelInvocable` 过滤后非空 | 4/4 均为 `{modelInvocable:true,userInvocable:true}` | 通过 |
| `history.visibleDigest === digest`（提前返回分支） | `visibleDigest === undefined`（无历史事件），不相等 | 未触发 |
| `existing !== undefined`（提前返回分支） | `existing === undefined` | 未触发 |
| `!history.published && skills.length === 0`（提前返回分支） | `published=false` 但 `skills.length=4`，条件为假 | 未触发 |
| `agent/pre-step` 是否被调度 | **已触发**：`kind=enter messages=2` | 通过 |

**结论**：按源码逻辑，执行应当抵达 `renderCatalogMessage(entries)` 并追加 catalog 消息。实际未追加。所有提前 `return` 分支经实测均不应生效。

## 4. 已排除的假设（均有实测证据）

| 假设 | 排除依据 |
|---|---|
| workspace skill 发现机制在 0.1.7 失效 | `snapshot({cwd})` 正确返回 4 个 skill，`complete: true` |
| `code` preset 在 0.1.7 不存在导致挂载错误 | 0.1.7 registry preset 集合为 `{standard, ptc, minimal, cordis, askai-enterprise}`；既有 `resolveNativePreset` fallback 将 `code` → `standard`，后者含 `skill-filesystem` + `tool-skill` |
| `.pnpm` 中 0.1.6 残留包参与解析 | `pnpm-lock.yaml` 已 0 处引用 `0.1.6-alpha.1`；运行时解析实测全部指向 0.1.7 |
| `dsh-tool-skill` 存在多实例导致身份比较失败 | 从 `dsh` 包与 runtime-host 两处解析**指向同一实例**（`cordis@4.0.4` peer 版）；其余两目录为无引用的孤儿 |
| ASKAI 自定义 adapter 绕过 `agent/pre-step` | adapter 经 `ctx.llm.registerAdapter(['askai-model-gateway'], ...)` 正规注册（`inject = ['llm']`）；且实测 `agent/pre-step` **确实被触发** |
| 钩子注册顺序导致观测偏差 | 通过 session 持久化事件确认（非仅靠 `ctx.on` 观测），`skill-catalog` 事件数为 0 |
| `cordis` peer 版本不匹配 | 已升至 4.0.4，`unmet peer` 冲突由 10+ → 0 |

## 5. 与 0.1.6 的关键差异

0.1.6 的 catalog 注入使用**嵌套 tool 消息结构**，0.1.7 改为**扁平结构**并以 `source.kind === 'skill-catalog'` 标记（`renderCatalogMessage` 产出 `<system-reminder>` + `<available_skills>` 的 user 消息）。本项目的 `stableModelRequest` 兼容层按 `role === 'system'` 提取 system 字段，不会误删 `role: 'user'` 的 catalog 消息。

> 另注：0.1.7 中 `dsh-tool-skill` 的 `skill` 工具描述文案为 "Load the full instructions for **a** skill."（0.1.6 为 "for **an available** skill."）。本项目 overlay 未覆盖该文案。

## 6. 复现方式

```bash
cd services/chat-api/dsh/runtime-host
node --test tests/official-code-enterprise-e2e.test.mjs      # 1 fail
node --test tests/official-skill-profile-e2e.test.mjs        # 1 fail
node --test tests/runtime-capability-admission.test.mjs      # 1 fail
```

最小复现（不经 HTTP，直接 composition + 真实 turn）：

```js
const host = new OfficialDshHostComposition({ storageRoot: root })
const ctx = await host.start()
const composer = new OfficialSessionComposer(ctx, {
  agentOptions: { provider: 'askai-deterministic', model: 'deterministic-v1' },
  enterpriseTools: [],
})
const prepared = await composer.prepare('code')
const handle = await ctx.get('agents').create({
  sessionId: 'repro', meta: { cwd: root }, setup: prepared.setup,
  agentOptions: { provider: 'askai-deterministic', model: 'deterministic-v1' },
})
const agent = handle.agent
// workspace 下预置 .agents/skills/verified-workflow/SKILL.md
const snap = await ctx.get('skills').snapshot({ cwd: agent.session.header.cwd, scope: agent })
console.log(snap.skills.map(s => s.name))   // 含 verified-workflow，complete: true
agent.followup({ type: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: 'hi' }] })
// 观测：session 中 skill-catalog 事件数为 0
```

## 7. 原待确认问题 — 均已由官方源码解答

调研来源：[github.com/deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)，release `dsh-v0.1.7-rc.2`（published 2026-09-24T14:10Z，与 npm 发布同步）。

| # | 原问题 | 解答 | 依据 |
|---|---|---|---|
| 1 | `agent/pre-step` 钩子在 scoped agent context 下是否正常执行？ | **正常执行**，但可见性判定失败 | 实测钩子被触发（`kind=enter messages=2`）；`src/index.ts:220` |
| 2 | `ctx.tools.get(name, agent) === skillTool` 在 scoped 挂载下是否恒成立？ | **不成立** —— 存在同名遮蔽时恒为 `false`，且这是**有意设计** | `src/index.ts:207` 注释 + README + `spec.ts:769` 测试 |
| 3 | `catalogHistory` 是否存在静默跳过路径？ | **是**，但在本例中未触发（本项目的跳过发生在更早的 `toolVisible` 判定） | `src/index.ts:231`；实测 `visibleDigest === undefined` 不相等 |
| 4 | 0.1.7 是否有意变更 catalog 注入时机？ | **未变更时机语义**；变更在于可见性判定严格化为**对象身份比较** | README "exact tool definition" + 官方 shadow 测试 |

**结论**：问题 4 的答案关键——**注入时机未变**（仍是 "before the first request"），因此本项目的 3 项断言**语义正确、应当修复实现而非调整断言**。

### 7.1 为何 0.1.6 可用而 0.1.7 不可用

0.1.6 的可见性判定未采用严格对象身份比较（或 host 平面与 preset 的 `tool-skill` 挂载关系不同），因此同名遮蔽未导致 catalog 丢失。0.1.7 明确将判定收紧为 `=== skillTool` 并在注释中说明意图（防止 scoped shadow 继承 catalog）。

### 7.2 实现细节 — 已解答

**原问题**：host 平面那份 `skill` 工具对 agent scope 是否可见？

**答案**：**本不该存在**。官方 web-app patch 在 host 平面显式 `disabled: true` 了 `tool-skill` 与 `skill-filesystem`，设计上只由 preset 挂载。本案的 host 平面那份是 **ASKAI overlay 丢失禁用指令**造成的意外产物。

因此修复不是"选择哪一份"，而是**恢复官方的禁用语义**：在 `overlay.mjs` 透传 `webAppPatches` 的 `disabled` 行。

## 8. 本项目已完成的修复（不涉及本问题）

同轮升级中另有两项 0.1.7 breaking change 已在本地修复并通过：

1. **jobs registry owner 契约变更**：`@deepseek-ai/dsh-jobs-local@0.1.7` 围栏为 `job.owner.id === caller`（caller 须为 session id 字符串，0.1.6 传 agent 对象可用）。修复见 `src/session-cancellation.mjs` 的 `jobCaller(agent)`。
2. **tool 消息结构扁平化**：0.1.7 由 `content[0].content[0].text` 改为 `content[0].text`。修复见 `tests/official-code-enterprise-e2e.test.mjs`。

## 9. 参考：相关文件

**本项目**
- `services/chat-api/dsh/runtime-host/src/official-host/session-composer.mjs`（preset 挂载路径）
- `services/chat-api/dsh/runtime-host/config/agent-presets/askai-enterprise/agent.cordis.yml`（挂载了 `tool-skill`）
- `services/chat-api/dsh/runtime-host/src/askai-model-gateway-plugin.mjs`（自定义 LLM adapter）
- `services/chat-api/dsh/runtime-host/src/official-host/model-request-compat.mjs`（`stableModelRequest` 兼容层）
- `services/chat-api/dsh/runtime-host/src/session-cancellation.mjs`（jobs 修复）

**DSH 官方源码（`dsh-v0.1.7-rc.2`）**
- [`packages/skill/tool-skill/src/index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.7-rc.2/packages/skill/tool-skill/src/index.ts) — 可见性判定（L220）与注释（L207）
- [`packages/skill/tool-skill/README.md`](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.7-rc.2/packages/skill/tool-skill/README.md) — "Catalog lifecycle" 设计说明
- [`packages/skill/tool-skill/tests/tool-skill.spec.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.7-rc.2/packages/skill/tool-skill/tests/tool-skill.spec.ts) — L750 restrict 测试、L769 shadow 测试
- `docs/WORK_LOG.md`（2026-09-25 两轮记录）
