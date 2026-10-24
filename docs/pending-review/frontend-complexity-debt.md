# 前端复杂度债务清单（DEBT-CX）

> **状态：已全部偿还（2026-10-24 QA R12）。**
> R11 建立的 99 处超限函数 / 44 个文件已全部重构至 `complexity: max 15`，
> `apps/eslint.shared.config.js` 的 `complexityDebt` 登记表已清空为 `[]`。
> 下列内容为 R11 建立时的原始清单，保留作历史记录；新增例外只允许
> 上限 ≤ 15 且已确认无法通过抽取降级的条目，并需在配置处登记原因。
>
> （R11 建立：2026-10-24 QA R11；门禁配置：`apps/eslint.shared.config.js` 的 `complexityDebt` 登记块。）

## 1. 背景

`apps/eslint.shared.config.js` 对 `complexity` 设置 `['error', { max: 15 }]`，
配置注释标注 **QF-054：门禁级别** —— 即项目意图是「函数复杂度 15 为硬门禁」。
但存量代码中已存在 **99 处超限函数**，分布在 **44 个文件**，最高复杂度 **99**。

逐个重构属于与功能无关的批量改写（AGENTS.md「不顺手重构」），且部分对象是
`ChatWindow.vue`（复杂度 99）、`PresentationEditor.vue`（81）这类数百行的核心组件，
在 QA 审计轮次里强行改写回归风险过高。因此本轮采用**按文件登记当前上限**的方式：

| 机制 | 效果 |
|---|---|
| `complexity: ['error', { max: N }]` 按文件登记 | 已存在的违规不再阻断 CI（规则只在 `> N` 时报错） |
| 新文件、非登记文件 | 仍走全局 `max: 15` 硬门禁 |
| 同一登记文件新增分支 | 突破该文件已登记上限才报错 |
| 偿还债务 | 改小该文件那一行的 `max`，并从未超线的函数中移除登记 |

**禁止事项**：禁止把已有行的 `max` 往上调；禁止新增文件入表。

## 2. 总览

| 应用 | 超限函数数 | 涉及文件数 | 最高复杂度 |
|---|---|---|---|
| admin-web | 24 | 12 | 38 |
| user-web | 75 | 32 | 99 |
| **合计** | **99** | **44** | **99** |

## 3. 分档

| 档位 | 处数 | 建议处置 |
|---|---|---|
| T1 重构区（≥50） | 7 | 按单一职责拆分为多个小函数/组合式函数；需配合功能测试 |
| T2 拆分区（30–49） | 16 | 提炼子函数或抽成 composable；风险中等 |
| T3 简化区（20–29） | 43 | 减少分支（查表替代 if 链、合并早退、`??` 收口） |
| T4 收尾区（16–19） | 33 | 通常是几行就能改的 2–4 个分支，随下次触碰该文件顺手清掉 |

## 4. 逐条清单

按复杂度降序。`max` 列为该文件在 `complexityDebt` 中登记的上限。

| 复杂度 | 应用 | 文件:行 | 函数 | 文件登记上限 |
|---:|---|---|---|---|
| 99 | user-web | `src/components/ChatWindow.vue:1484` | `renderChartBlocks` | 99 |
| 81 | user-web | `src/components/PresentationEditor.vue:748` | `Function 'canvasToBlueprint' has a complexity of 81. Maximum allowed is 15.` | 81 |
| 74 | user-web | `src/components/PresentationEditor.vue:1417` | `Function 'onObjectMoving' has a complexity of 74. Maximum allowed is 15.` | 81 |
| 63 | user-web | `src/features/execution-v3/stores/executionStore.ts:24` | `Function 'applyEvent' has a complexity of 63. Maximum allowed is 15.` | 63 |
| 62 | user-web | `src/components/PresentationEditor.vue:382` | `Function 'addBlockToCanvas' has a complexity of 62. Maximum allowed is 15.` | 81 |
| 60 | user-web | `src/composables/useChatRuntimeStore.ts:319` | `sendMessage` | 60 |
| 55 | user-web | `src/components/SkillConfigPage.vue:360` | `Arrow function has a complexity of 55. Maximum allowed is 15.` | 55 |
| 39 | user-web | `src/components/ChatWindow.vue:1765` | `Function 'parseChartPayload' has a complexity of 39. Maximum allowed is 15.` | 99 |
| 38 | admin-web | `src/views/skills/SkillConfigPage.vue:2152` | `generateScriptPluginStep` | 38 |
| 38 | user-web | `src/api/tokenUsage.ts:61` | `listTokenUsage` | 38 |
| 38 | user-web | `src/components/MySkillConfigPage.vue:2119` | `generateScriptPluginStep` | 38 |
| 36 | user-web | `src/api/compositeSkill.ts:113` | `Function 'decodeCompositeSkill' has a complexity of 36. Maximum allowed is 15.` | 36 |
| 36 | user-web | `src/composables/evidenceBundles.ts:13` | `Function 'isEmptyKbSource' has a complexity of 36. Maximum allowed is 15.` | 36 |
| 35 | admin-web | `src/views/tools/ToolEditPage.vue:859` | `Function 'commonFieldMeaning' has a complexity of 35. Maximum allowed is 15.` | 35 |
| 35 | user-web | `src/components/MyToolsPage.vue:1037` | `Function 'commonFieldMeaning' has a complexity of 35. Maximum allowed is 15.` | 35 |
| 32 | user-web | `src/api/skills.ts:483` | `generateSkill` | 32 |
| 32 | user-web | `src/components/orchestration/canvasSchema.ts:261` | `Function 'engineDocumentToCanvas' has a complexity of 32. Maximum allowed is 15.` | 32 |
| 30 | admin-web | `src/components/NativeDocumentPreview.vue:108` | `Function 'markdownBlocks' has a complexity of 30. Maximum allowed is 15.` | 30 |
| 30 | admin-web | `src/views/organizations/TrafficAllocationsPage.vue:437` | `Arrow function has a complexity of 30. Maximum allowed is 15.` | 30 |
| 30 | user-web | `src/components/PresentationEditor.vue:1085` | `Function 'syncToolbarFromSelection' has a complexity of 30. Maximum allowed is 15.` | 81 |
| 30 | user-web | `src/components/execution/NativeSourcePreview.vue:108` | `Function 'markdownBlocks' has a complexity of 30. Maximum allowed is 15.` | 30 |
| 30 | user-web | `src/components/scheduled-tasks/ScheduledTaskEditor.vue:53` | `Arrow function has a complexity of 30. Maximum allowed is 15.` | 30 |
| 30 | user-web | `src/utils/assistantMarkdown.ts:16` | `Function 'isProseContent' has a complexity of 30. Maximum allowed is 15.` | 30 |
| 29 | user-web | `src/App.vue:1536` | `openAdminConsole` | 29 |
| 29 | user-web | `src/api/skills.ts:296` | `updateSkill` | 32 |
| 29 | user-web | `src/components/chat/shortcutGuideResolver.ts:37` | `Function 'resolveShortcutGuideCategories' has a complexity of 29. Maximum allowed is 15.` | 29 |
| 28 | user-web | `src/api/compositeSkill.ts:60` | `Function 'encodeCompositeSkill' has a complexity of 28. Maximum allowed is 15.` | 36 |
| 28 | user-web | `src/components/PresentationEditor.vue:288` | `Function 'renderBlockContainer' has a complexity of 28. Maximum allowed is 15.` | 81 |
| 27 | admin-web | `src/api/token-stats.ts:100` | `fetchTokenStats` | 27 |
| 27 | admin-web | `src/views/settings/ExternalSearchSettingsPage.vue:1127` | `runTest` | 27 |
| 27 | admin-web | `src/views/skills/SkillConfigPage.vue:1316` | `Function 'normalizeWorkflowNode' has a complexity of 27. Maximum allowed is 15.` | 38 |
| 27 | user-web | `src/api/auth.ts:77` | `loginWithPassword` | 27 |
| 27 | user-web | `src/components/ChatWindow.vue:1028` | `regenerateDocument` | 99 |
| 27 | user-web | `src/components/MySkillConfigPage.vue:1368` | `Function 'normalizeWorkflowNode' has a complexity of 27. Maximum allowed is 15.` | 38 |
| 27 | user-web | `src/components/PresentationEditor.vue:1343` | `Function 'onKeyDown' has a complexity of 27. Maximum allowed is 15.` | 81 |
| 27 | user-web | `src/composables/useChatStream.ts:48` | `Async` | 27 |
| 26 | user-web | `src/api/auth.ts:129` | `exchangePortalTicket` | 27 |
| 25 | admin-web | `src/views/skills/SkillConfigPage.vue:1681` | `Function 'hydrateWorkflow' has a complexity of 25. Maximum allowed is 15.` | 38 |
| 25 | admin-web | `src/views/skills/SkillConfigPage.vue:1928` | `supplementStepWithAi` | 38 |
| 25 | admin-web | `src/views/skills/SkillConfigPage.vue:2240` | `fixScriptPluginStep` | 38 |
| 25 | user-web | `src/components/MySkillConfigPage.vue:1701` | `Function 'hydrateWorkflow' has a complexity of 25. Maximum allowed is 15.` | 38 |
| 25 | user-web | `src/components/MySkillConfigPage.vue:1945` | `supplementStepWithAi` | 38 |
| 25 | user-web | `src/components/MySkillConfigPage.vue:2207` | `fixScriptPluginStep` | 38 |
| 24 | admin-web | `src/views/organizations/OrganizationUsersPage.vue:1153` | `saveUser` | 24 |
| 24 | user-web | `src/api/auth.ts:241` | `fetchUserProfile` | 27 |
| 24 | user-web | `src/api/recording.ts:143` | `Function 'eventsToSteps' has a complexity of 24. Maximum allowed is 15.` | 24 |
| 24 | user-web | `src/composables/useChatRuntimeStore.ts:259` | `Function 'resolvePaneSession' has a complexity of 24. Maximum allowed is 15.` | 60 |
| 23 | user-web | `src/components/ChatWindow.vue:1098` | `Function 'handleScroll' has a complexity of 23. Maximum allowed is 15.` | 99 |
| 23 | user-web | `src/components/LocatorEditor.vue:48` | `Function 'extractFromHTML' has a complexity of 23. Maximum allowed is 15.` | 23 |
| 23 | user-web | `src/composables/evidenceBundles.ts:50` | `Function 'mergeEvidenceBundles' has a complexity of 23. Maximum allowed is 15.` | 36 |
| 23 | user-web | `src/features/execution-v3/components/ActivityItem.vue:26` | `Arrow function has a complexity of 23. Maximum allowed is 15.` | 23 |
| 22 | admin-web | `src/views/knowledge/KnowledgeDocumentPreviewPage.vue:687` | `loadBlob` | 22 |
| 22 | admin-web | `src/views/models/ModelsPage.vue:620` | `saveModel` | 22 |
| 22 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:496` | `Function 'normalizeSourceBBox' has a complexity of 22. Maximum allowed is 15.` | 22 |
| 22 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:857` | `renderPdf` | 22 |
| 21 | admin-web | `src/views/skills/SkillConfigPage.vue:2021` | `runWorkflowTest` | 38 |
| 21 | user-web | `src/App.vue:1913` | `Async` | 29 |
| 21 | user-web | `src/components/MySkillConfigPage.vue:1988` | `runWorkflowTest` | 38 |
| 21 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:147` | `loadActiveSource` | 22 |
| 21 | user-web | `src/components/skills/SkillFeedbackPanel.vue:61` | `load` | 21 |
| 21 | user-web | `src/features/execution-v3/domain/repeatedToolCalls.ts:197` | `Function 'toolCallSummary' has a complexity of 21. Maximum allowed is 15.` | 21 |
| 20 | admin-web | `src/components/settings/ShortcutSettingsPanel.vue:273` | `Function 'saveEntry' has a complexity of 20. Maximum allowed is 15.` | 20 |
| 20 | user-web | `src/components/ChatWindow.vue:797` | `openDocumentEditor` | 99 |
| 20 | user-web | `src/components/chat/ChatComposer.vue:269` | `loadSelectableSkills` | 20 |
| 20 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:552` | `Function 'sourceCoordinateSizeForBBox' has a complexity of 20. Maximum allowed is 15.` | 22 |
| 20 | user-web | `src/research/researchService.ts:233` | `Function 'extractAssistantContent' has a complexity of 20. Maximum allowed is 15.` | 20 |
| 19 | admin-web | `src/views/knowledge/KnowledgeDocumentPreviewPage.vue:431` | `Arrow function has a complexity of 19. Maximum allowed is 15.` | 22 |
| 19 | admin-web | `src/views/skills/SkillConfigPage.vue:1507` | `Function 'normalizeSectionNode' has a complexity of 19. Maximum allowed is 15.` | 38 |
| 19 | user-web | `src/components/MySkillConfigPage.vue:1527` | `Function 'normalizeSectionNode' has a complexity of 19. Maximum allowed is 15.` | 38 |
| 19 | user-web | `src/components/code/changePresentation.ts:9` | `Function 'changeStatusPresentation' has a complexity of 19. Maximum allowed is 15.` | 19 |
| 19 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:347` | `Function 'isMatchedTextLine' has a complexity of 19. Maximum allowed is 15.` | 22 |
| 19 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:514` | `Function 'drawBBoxHighlight' has a complexity of 19. Maximum allowed is 15.` | 22 |
| 19 | user-web | `src/composables/code/codeRuntimeErrors.ts:1` | `Function 'codeRuntimeErrorMessage' has a complexity of 19. Maximum allowed is 15.` | 19 |
| 18 | admin-web | `src/views/skills/SkillConfigPage.vue:1972` | `polishStepRequirement` | 38 |
| 18 | admin-web | `src/views/tools/ToolEditPage.vue:1407` | `runDebug` | 35 |
| 18 | user-web | `src/App.vue:1474` | `Arrow function has a complexity of 18. Maximum allowed is 15.` | 29 |
| 18 | user-web | `src/api/auth.ts:195` | `register` | 27 |
| 18 | user-web | `src/components/MySkillConfigPage.vue:1873` | `regenerateSteps` | 38 |
| 18 | user-web | `src/components/MyToolsPage.vue:801` | `Function 'normalizeSchemaNode' has a complexity of 18. Maximum allowed is 15.` | 35 |
| 18 | user-web | `src/components/MyToolsPage.vue:1392` | `runTest` | 35 |
| 18 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:650` | `Function 'tableTargetMatchScore' has a complexity of 18. Maximum allowed is 15.` | 22 |
| 17 | admin-web | `src/router/index.ts:11` | `Async` | 17 |
| 17 | admin-web | `src/views/skills/SkillConfigPage.vue:1439` | `Function 'normalizeStoredCheck' has a complexity of 17. Maximum allowed is 15.` | 38 |
| 17 | admin-web | `src/views/tools/ToolEditPage.vue:1022` | `Function 'schemaFromTestResponse' has a complexity of 17. Maximum allowed is 15.` | 35 |
| 17 | user-web | `src/components/MySkillConfigPage.vue:1459` | `Function 'normalizeStoredCheck' has a complexity of 17. Maximum allowed is 15.` | 38 |
| 17 | user-web | `src/components/MyToolsPage.vue:1176` | `Function 'schemaFromTestResponse' has a complexity of 17. Maximum allowed is 15.` | 35 |
| 16 | admin-web | `src/views/portal/PortalApprovalPage.vue:80` | `submit` | 16 |
| 16 | admin-web | `src/views/skills/SkillConfigPage.vue:2208` | `checkScriptPluginStep` | 38 |
| 16 | user-web | `src/App.vue:352` | `Arrow function has a complexity of 16. Maximum allowed is 15.` | 29 |
| 16 | user-web | `src/api/auth.ts:106` | `selectTenantAndLogin` | 27 |
| 16 | user-web | `src/api/auth.ts:217` | `switchTenant` | 27 |
| 16 | user-web | `src/components/ChatWindow.vue:449` | `usePromptGuideItem` | 99 |
| 16 | user-web | `src/components/MyKnowledgePage.vue:82` | `loadResources` | 16 |
| 16 | user-web | `src/components/MySkillConfigPage.vue:2175` | `checkScriptPluginStep` | 38 |
| 16 | user-web | `src/components/PresentationEditor.vue:1732` | `Function 'renderFsPage' has a complexity of 16. Maximum allowed is 15.` | 81 |
| 16 | user-web | `src/components/RecordingPanel.vue:118` | `Function 'eventLabel' has a complexity of 16. Maximum allowed is 15.` | 16 |
| 16 | user-web | `src/components/execution/KnowledgeSourceViewer.vue:71` | `Function 'previewKindForDocument' has a complexity of 16. Maximum allowed is 15.` | 22 |
| 16 | user-web | `src/composables/tasks/browserInterventionTaskFlow.ts:16` | `resumeBrowserInterventionTaskUntilSettled` | 16 |
| 16 | user-web | `src/composables/useChatRuntimeStore.ts:404` | `Arrow function has a complexity of 16. Maximum allowed is 15.` | 60 |

## 5. 偿还流程

每偿还一批，做三件事：

1. 重构对应函数，使复杂度降到 15 以下（或在确需保留时给出理由）。
2. 在 `apps/eslint.shared.config.js` 的 `complexityDebt` 中把该文件的 `max`
   改为新的实际最大值；若该文件已无超限函数，**删除整行**。
3. 从本文件删除对应条目，并在标题下的状态行更新已偿还数量。

验证：

```bash
cd apps/admin-web && pnpm lint   # 期望 0 errors
cd apps/user-web  && pnpm lint   # 期望 0 errors
```

进度自查（应随偿还单调递减）：

```bash
# 当前登记的文件数
grep -c "files: \['src/" apps/eslint.shared.config.js
```

## 6. 本轮（QA R11）实际改动

- `apps/eslint.shared.config.js`：新增 `complexityDebt` 登记块（44 个文件）。
- `apps/admin-web/src/components/ContinuousPdfPreview.vue`：修 4 处 `no-empty`
  （145/211/217/218 的空 `catch {}` 补上中文说明注释；已实测 `catch { /* 注释 */ }`
  不被 `no-empty` 命中，而空块会命中）。
- `apps/user-web/src/research/researchService.ts:184`：修 `no-useless-assignment`
  （`let data: any = null` 的初始化值从未被读取，删除初始化）。

**未做**：未重构任何复杂度超限函数（属独立技术债任务，需配合功能测试）。
