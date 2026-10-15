# Quickstart: user-web 会话级「对话 / 轨迹」双 tab（路线 C）

## 前置

```bash
cd apps/user-web
pnpm install     # 若依赖未装
```

## 启动开发态

```bash
pnpm -C apps/user-web dev
```

浏览器打开 dev 地址，登录进入会话页。

## 验证清单

### 1. 基本切换（US1）

1. 新建一个会话，发送一条会触发工具调用的消息（例如让助手检索知识库）。
2. 会话页顶部应出现「对话 / 轨迹」两个 tab。
3. 点击「轨迹」→ 应看到本轮的处理过程（思考、工具调用等），**不显示**问答气泡。
4. 点击「对话」→ 恢复原有问答气泡。

### 2. 跨轮次聚合（FR-003）

1. 在同一会话里再发 1–2 条消息。
2. 切到「轨迹」→ 应看到**所有轮次**的处理过程（按时间顺序），而非仅最后一轮。

### 3. pane 独立（US2 / FR-004）

1. 会话 A 切到「轨迹」。
2. 切到会话 B → 应为「对话」（默认）。
3. 切回会话 A → 应仍停在「轨迹」。

### 4. 生成中切换不中断（US3 / FR-006 / FR-007）

1. 发送一条长回答的消息。
2. 生成过程中切到「轨迹」→ 处理项实时增长。
3. 切回「对话」→ 正文仍在流式输出，未中断、未重复。

### 5. 零回归（FR-005 / SC-003）

1. 在「对话」tab 完成一次完整问答：气泡、产物卡、证据抽屉、审批提示均与改造前一致。
2. 滚动位置、吸顶行为正常。

### 6. 空态

1. 打开一个老会话（无 `execution_events`）。
2. 切到「轨迹」→ 显示空态提示，不报错。

## 自动化验证

```bash
pnpm -C apps/user-web test          # vitest 全量
pnpm -C apps/user-web typecheck     # 若存在该脚本
```

期望：现有测试全绿 + 新增 `trajectory-view-tabs.test.ts` 通过。

## 回滚

本特性纯前端、无数据迁移。回滚只需还原以下文件：

- `apps/user-web/src/composables/useChatRuntimeStore.ts`
- `apps/user-web/src/App.vue`
- `apps/user-web/src/locales/messages.ts`
- 删除新增的 `ChatViewTabs.vue` / `SessionTrajectoryView.vue` / 测试文件
