# Implementation Plan: user-web 会话级「对话 / 轨迹」双 tab（路线 C）

**Branch**: `028-user-web-trajectory-tab` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

## Summary

在 user-web 会话页新增会话级「对话 / 轨迹」tab 切换。**纯前端、数据层零新增**：轨迹与对话消费同一份 V3 事件与 `ExecutionStoreV3`，本特性只增加一层视图切换与一个会话级轨迹聚合视图。

## Technical Context

- **语言/框架**：TypeScript + Vue 3（`<script setup>`）+ Vite，目录 `apps/user-web`
- **状态管理**：`composables/useChatRuntimeStore.ts` 的 `reactive({ panes, activeKey })`，多 pane（最多缓存 8 个）
- **被测组件**：`components/ChatWindow.vue`（chat shell，**文件不改**）
- **轨迹数据**：`features/execution-v3/`（`ExecutionStoreV3` + `ExecutionViewV3.vue`），按消息幂等附着（`stores/messageExecution.ts:38-69`）
- **测试**：`apps/user-web/tests/*.test.ts`（vitest）
- **i18n**：`src/locales/messages.ts`（扁平 key → `{ zh, en }`）
- **后端**：无改动

## Constitution Check

- **原则 I Specification-First**：✅ 本 spec/plan 先于实现。
- **改动纪律（AGENTS.md）**：✅ 只改必要文件，不顺手重构；`ChatWindow.vue` 保持零改动。
- **架构边界（ChatWindow.vue:49-54）**：✅ 新增能力以**独立子组件**形式接入，不向 ChatWindow 加 UI 块。
- **不做**：官方 dsh 前端依赖、`/api` 直连、后端改动（见 spec 边界）。

## Project Structure

### 改动文件

| 文件 | 动作 | 说明 |
|---|---|---|
| `apps/user-web/src/composables/useChatRuntimeStore.ts` | 修改 | pane 加 `activeView` 字段 + `setPaneView()` |
| `apps/user-web/src/components/chat/ChatViewTabs.vue` | **新增** | 「对话 / 轨迹」tab 切换器（纯展示 + emit） |
| `apps/user-web/src/features/execution-v3/components/SessionTrajectoryView.vue` | **新增** | 会话级轨迹视图（遍历消息渲染 ExecutionViewV3） |
| `apps/user-web/src/App.vue` | 修改 | chat pane 容器改 flex-col + 挂载 tab 切换器 + 视图切换 |
| `apps/user-web/src/locales/messages.ts` | 修改 | 新增 2 个 i18n key |
| `apps/user-web/tests/trajectory-view-tabs.test.ts` | **新增** | tab 状态与视图切换的单测 |

### 不改动

- `components/ChatWindow.vue`（零改动，保证 FR-005 零回归）
- `services/` 全树、`docker-compose*.yml`、`deploy/`

## 设计

### 1. pane 增加视图维度

`ChatRuntimePane`（`useChatRuntimeStore.ts:85-103`）新增：

```ts
activeView: 'chat' | 'trajectory'   // 默认 'chat'
```

`createPane()`（:171-191）初始化 `activeView: 'chat'`；新增并导出 `setPaneView(key, view)`。

**为什么放 pane 而不是 App 局部 state**：tab 归属「会话」，多 pane 切换必须各自独立（FR-004）。pane 是会话状态的唯一 owner。

### 2. `ChatViewTabs.vue`（新）

- Props：`view: 'chat' | 'trajectory'`
- Emits：`update:view`
- 纯展示：两个按钮 + 选中态样式；文案走 `t('chat.view.chat')` / `t('chat.view.trajectory')`
- 不持有业务逻辑（符合 ChatWindow 的架构边界精神）

### 3. `SessionTrajectoryView.vue`（新）

- Props：`messages: RuntimeMessage[]`
- 计算：过滤 `role === 'assistant'` 的消息，逐条 `ensureMessageExecutionV3(msg)` 取 store
- 渲染：对每条有轨迹的消息渲染一个 `ExecutionViewV3`（**逐消息纵向堆叠**，阶段 1 最小可用），每条上方标注轮次序号/时间
- 空态：无 assistant 消息或无轨迹数据时显示占位文案
- **不绑定 `resolve-permission`**：轨迹 tab 为只读（见 spec Assumptions）

### 4. `App.vue` 会话 pane 接线

当前（`App.vue:2557-2562`）：

```vue
<div v-for="pane in visibleChatPanes" v-show="pane.key === activeChatKey" :key="pane.key" class="h-full w-full">
  <ChatWindow ... />
</div>
```

改为：

```vue
<div v-for="pane in visibleChatPanes" v-show="pane.key === activeChatKey" :key="pane.key" class="flex h-full w-full flex-col">
  <ChatViewTabs
    :view="pane.activeView"
    @update:view="(v) => chatRuntime.setPaneView(pane.key, v)"
  />
  <div class="relative min-h-0 flex-1">
    <ChatWindow v-show="pane.activeView === 'chat'" ... />
    <SessionTrajectoryView
      v-show="pane.activeView === 'trajectory'"
      class="h-full w-full"
      :messages="pane.messages"
    />
  </div>
</div>
```

**布局安全性论证**：`BrowserWorkspace.vue:122` 的 `.browser-workspace { width:100%; height:100% }` 要求父容器有确定高度。改造后 ChatWindow 的父容器从 `h-full w-full` 变为 `min-h-0 flex-1`（flex-col 子项 → 仍有确定高度），`height:100%` 依旧成立。

**为什么用 `v-show` 而非 `v-if`**：`v-if` 会在切换时卸载/重建 ChatWindow，可能中断 `useChatStream` 的读取、丢失滚动位置与吸顶状态。`v-show` 保持挂载（FR-006/FR-007）。

### 5. i18n

`messages.ts` 新增：

```ts
'chat.view.chat': { zh: '对话', en: 'Chat' },
'chat.view.trajectory': { zh: '轨迹', en: 'Trajectory' },
```

## 风险与对策

| 风险 | 对策 |
|---|---|
| ChatWindow 高度塌陷 | 父容器用 `flex-1 min-h-0` 保持确定高度；实现后目视验证滚动/吸顶 |
| 切换中断流式生成 | 用 `v-show` 保持挂载；单测覆盖「生成中切换」 |
| 轨迹 tab 渲染开销（多轮历史） | 阶段 1 逐消息渲染；若卡顿，阶段 2 改虚拟滚动 |
| 老会话无 `execution_events` | 空态兜底，不抛错 |
| 并行会话污染 | 只 `git add` 本特性文件（见 tasks 的提交纪律） |
