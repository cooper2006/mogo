# Requirements Checklist: user-web 会话级「对话 / 轨迹」双 tab（路线 C）

## 需求质量

- [x] 需求无实现细节泄漏（spec 以行为描述为主，代码路径仅作背景证据）
- [x] 需求可测试（每条 FR 有对应 Acceptance Scenario 或验证步骤）
- [x] 需求无歧义（「轨迹」范围明确为「当前会话全部 assistant 轮次」）
- [x] 用户故事按优先级排序（P1 tab 切换 → P2 pane 独立 → P3 实时跟随）
- [x] 每个用户故事可独立测试
- [x] 边界情况已列出（无轨迹数据 / 流式中切换 / 多 pane / 刷新）

## 范围与边界

- [x] 明确不做项已列出（iframe 嵌入 / 直连 `/api` / 官方前端依赖 / 绕过治理）
- [x] 第一版范围明确（逐消息渲染，非聚合时间线）
- [x] 后端零改动已声明
- [x] 不涉及部署面（compose / nginx / 镜像）

## 可测性

- [x] SC-001（切换无网络请求）可验证
- [x] SC-002（现有测试全绿）可验证
- [x] SC-003（对话 tab 零改动）可验证——ChatWindow.vue 不在改动清单
- [x] SC-004（≥2 轮历史聚合）可验证

## 一致性

- [x] 与 `docs/user-web-复用dsh-web会话能力-方案.md` 路线 C 一致
- [x] 与宪法原则 I（Specification-First）一致
- [x] 与 ChatWindow 架构边界（不加大 UI 块）一致
- [x] 与 AGENTS.md 改动纪律一致（只改必要文件）

## 待办

- [ ] 阶段 2（后续迭代）：会话级轨迹聚合时间线/表格 + 工具栏（时长/轮次/调用数/搜索），对齐官方 `dsh-client-ui-trajectory`
