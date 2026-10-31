# himovo/movo 再比对分析（P0-P3 合入后复查）

> 目的：在既有 `movo-merge-analysis-2026-10-31.md`（P0–P3 已执行 + 三期-b 已取消）的基础上，**重新**比对 himovo/movo 与本地 mogo，识别**仍然剩余的可合并内容**。
> **本次只做分析，不执行任何合并。**
>
> | 项 | 值 |
> |---|---|
> | himovo 参照点 | `himovo/main` @ `305bd927`（feat(product): support enterprise member policy and deployment errors） |
> | 本地参照点 | `main` @ `94273df0`（P3 SSE 联调 20 断言已合入） |
> | himovo 自上次参照后新提交 | **0**（`git rev-list --count 305bd927..himovo/main` = 0，main 无进展） |
> | 比对日期 | 2026-10-31 |
> | 结论 | 本地已用 mogo 品牌**自主实现**了绝大多数 himovo「独有」功能；**剩余可合并候选很少且多为全新功能域**，需连带移植依赖，非零成本。 |

---

## 1. 结论摘要

1. **himovo/main 无新提交**：仍停留在 `305bd927`。本次比对的对象与上次一致，唯一变量是**本地推进到了 `94273df0`**（已合入 P0-P3 + SSE 联调）。
2. **「himovo 独有 606 文件」不等于 606 个可合并**。逐域核对后，绝大多数 himovo 独有文件对应的功能**本地已有等价或更成熟的自主实现**（mogo 品牌），或属于**用户已明确取消**的域（三期-b snapshot/desktop），或属于**纯文案/基础设施/主题**（P4 惯例暂缓）。
3. **真正的剩余合并候选集中在 6~8 个「本地完全没有」的全新功能域**，均为「前后端 + 依赖 + 测试」的整域移植，工作量大，需评估依赖后才能动手。
4. **`305bd927`（企业成员策略 + 部署错误）已决定不合并**：其后端成员上限走 `member_limit_resolver` 扩展点，与本地已有 FR-022 的 `resolve_member_limit`（平台覆盖成员上限）**方向互斥**——本地实现保留，himovo 版本不引入。

---

## 2. 比对方法与总览

```bash
# himovo 独有（本地无同名文件，状态 A）
git diff --diff-filter=A --name-only HEAD himovo/main | wc -l   # 606
# 全部差异状态
git diff --name-status HEAD himovo/main | awk '{print $1}' | sort | uniq -c
# → 1443 D（本地独有） 991 M（双方都改） 606 A（himovo 独有） 10 R（重命名）
```

| 维度 | 数量 | 含义 |
|---|---|---|
| A（himovo 独有） | 606 | himovo 有、本地无同名文件 —— 本次逐域核对主体 |
| M（双方都改） | 991 | 本地与 himovo 都改、方向不同 —— **非简单可合并**，多为本地自主重构 |
| D（本地独有） | 1443 | 本地有、himovo 无 —— 本地自主开发的**体量证据** |
| R（重命名） | 10 | 文件重命名 |

**关键判断**：本地有 **1443 个 himovo 没有的文件**、且 991 个双方文件走向不同 —— 说明本地早已脱离 himovo 自行演进（mogo 品牌、自主实现）。himovo 独有文件里那些功能，本地极可能已在 `1443` 里用**不同文件名/结构**实现了等价物。因此**不能把 A 文件数直接当作合并量**，必须逐域核对「本地是否已有对应功能」。

---

## 3. himovo 独有 606 文件的目录分布

```
apps/user-web        219      services/chat-api    207
apps/admin-web        96      services/admin-api    56
qa                    10      deploy                8
scripts                6      services/document-parser  1
.github                2      movo（CLI 脚本）       1
```

---

## 4. 功能域归类总表

> 归类以「本地是否已有对应功能」为第一判据，其次才是文件数量。部分文件跨域，域间有小重叠，数量为 grep 模式统计（代表路径见 §5）。

| # | 功能域 | himovo 独有文件 | 本地对应实现 | 判定 |
|---|---|---|---|---|
| 1 | browser 运行引擎 `browser_run_*` | 10 | `enterprise_capabilities/browser/engine/` 已有 **~70 文件**自主实现 | **已覆盖**，不合并 |
| 2 | content 写作引擎 `writer_engine/*` | 13 | `content/writer_engine/unified_compose/` 已有自主实现（assembler/components/prompt_registry 等） | **已覆盖**，不合并 |
| 3 | evidence / knowledge 基础 | 4 | `evidence/foundation/` 已有 ~12 文件（kb_qa_projection、writer_packet 等） | **已覆盖**，不合并 |
| 4 | knowledge_source 配置 | 10 | `api/endpoints/knowledge_sources.py`、`personal_knowledge.py` 已存在 | **已覆盖**，不合并 |
| 5 | skill 支持（skill_support / skill_* 服务） | 17 | `dsh_runtime/profile/skills/` 已有 9 文件 + `api/endpoints/skills.py`、`skill_lifecycle.py` | **已覆盖**，不合并 |
| 6 | 模型配置 / 视觉 / 代理 | 4 | `llm/` 已有 configured_models/model_router/image_model_runtime | **已覆盖**，不合并 |
| 7 | desktop（三期-b） | 6+（user-web desktop/platform/windows-dark） | 用户**已明确取消**三期-b | **用户取消**，不合并 |
| 8 | session snapshot 用户态 | 5 | 本地已有 `services/session_versioning/snapshot.py`、`session_sharing/snapshot.py` | **已覆盖**，不合并 |
| 9 | 暗色主题（theme/、dark-*、naive） | 9 | 可选增强 | **暂缓**（P4） |
| 10 | i18n 文案 `locales/*.ts` | 52 | 本地已有 i18n 体系（key 不同） | **暂缓**（P4，文案不随代码合入） |
| 11 | qa / CI / 镜像源 / 校验脚本 | 24 | 本地无 qa 目录，测试方式不同（esbuild+node） | **暂缓**（基础设施） |
| 12 | 知识库文档页样式/辅助 | 7 | 本地已有 `KnowledgeDocumentsPage.vue` | **已覆盖**，不合并 |
| 13 | skill / tool 编辑器样式 | 17 | 本地已有对应页面 | **已覆盖**，不合并 |
| 14 | app shell 重构（user-web App*/useApp*） | ~40 | 本地已有不同 app shell | **已覆盖**，不合并 |
| 15 | 企业成员策略 + 部署错误（305bd927） | 8（含 4 个 M 状态后端） | **本地已有不同实现**（FR-022） | **不合并**（用户已决定） |
| 16 | DSH 插件管理（plugin_management） | 40 | 本地 dsh_runtime **无 plugin_management** | **候选**（全新域） |
| 17 | 主题准入（topic_admission / topic_matcher） | 17 | 本地 governance **无 topic_admission** | **候选**（全新域） |
| 18 | 模型组（model_groups / ModelGroup*） | 21 | 本地 admin-api **无 model_group** | **候选**（全新域） |
| 19 | docx 审阅（docx_review / ReviewCheckNode） | 12 | 本地无 docx 审阅（本地有 pdf_editing/delivery） | **候选**（全新域） |
| 20 | workflow 审阅（workflow_messages / node_bindings） | 26 | 本地无 ReviewCheckNode | **候选**（全新域） |
| 21 | 用户问题（user_questions / question_answers） | 11 | 本地无 | **候选**（全新域） |
| 22 | 企业邀请（invite_* / Invite*） | 10 | 本地 organizations 无 invite | **不合并**（用户已决定） |
| 23 | sandbox 审计内部端点 | 2 | 本地已有 `execution_isolation/audit_reader.py`，仅缺端点 | **候选**（小、低风险） |
| 24 | migrations / sequence 修复 | 7 | 本地已有 `migrations/session_sharing.py` | **候选**（高风险，数据迁移） |

---

## 5. 剩余可合并候选明细（唯一需要评估的部分）

> 以下为**本地完全没有**（或仅部分具备）的功能域。每一项都是「前后端 + 依赖 + 测试」的整域移植。**均未执行**。

### 5.1 企业成员策略 + 部署错误（305bd927，8 文件）— 已决定不合并

- **himovo 侧**（305bd927，8 文件）：admin-api `core/product_edition.py` + `product/extensions.py`、chat-api `core/product_edition.py` + `product/extensions.py`（后端成员上限扩展点）；admin-web `api/deploymentError.ts`（纯新增 7 行）+ `locales/additionalMessages.ts`（164 行文案）+ `views/auth/LoginPage.vue` + `views/dashboard/DashboardPage.vue`（部署错误接入）。
- **本地状态**：后端 `product_edition.py` 本地已有 **FR-022 `resolve_member_limit` + `tenants.member_limit` 平台覆盖**（与 himovo 的 `member_limit_resolver` 扩展点**方向互斥**，两者叠加会双重计算上限）；前端 `deploymentError.ts` 为纯新增。→ **用户已明确决定不合并**，整域（含前端部署错误接入）从候选清单移除。

### 5.2 DSH 插件管理（plugin_management，全新域，~40 文件）

- **himovo 侧**：`dsh_runtime/plugin_management/*`（9：installer/repository/compatibility/audit/invocation/source_policy/archive_store/install_failure/__init__）、`dsh_runtime/profile/{plugins,plugin_runtime_recovery,mcp_schema}.py`、`profile/skills/review_protocol.py`、`api/endpoints/{dsh_plugins,dsh_plugin_archives,dsh_skill_bundles}.py`、`api/{dsh_access_messages,skill_package_messages}.py`、`Dockerfile.sandbox-script`、`sandbox_script/prepare_skill.py`、`scripts/backfill_dsh_token_usage_users.py`；admin-api `api/routes/dsh_plugins.py`；admin-web `views/dsh-plugins/*`（5）+ `api/dsh-plugins.ts` + `icons/DshPluginsIcon.ts` + `locales/modules/dshPlugins.ts`；user-web `api/dshPlugins.ts` + `components/plugins/*`（4）+ `MyPluginsPage.vue` + `locales/pluginEnvironmentMessages.ts`。
- **本地状态**：`dsh_runtime/` 已存在（gateway/hooks/profile/tool_gateway/model_gateway/session_live 等），但**无任何插件管理**；`profile/` 下无 `plugins.py`。→ 真增量，但需**接入现有 profile/gateway 生命周期**。
- **依赖缺口**：`dsh_runtime/plugin_management` 依赖 `profile` 现有 bundle/catalog 体系，需确认兼容；沙箱脚本 `Dockerfile.sandbox-script` + `prepare_skill.py` 需接入现有 sandbox 镜像构建链。
- **风险**：中等。全新域、跨三层（chat-api + admin-api + 两端），工作量大。

### 5.3 主题准入（topic_admission / topic_matcher，全新域，~17 文件）

- **himovo 侧**：`chat-api app/governance/topic_admission.py`、`app/utils/topic_matcher.py`；admin-api `topic_admission/{__init__,models,rules,service}.py`（4）+ `api/routes/topic_admission.py`；admin-web `components/settings/Topic{AdmissionModePicker,AdmissionPanel,RuleDialog,RuleEditor,RuleList}.vue`（5）+ `useTopicRuleAudiences.ts` + `api/topic-admission.ts` + `locales/modules/taskAdmission.ts`。
- **本地状态**：`governance/` 已有（approval_runtime/audit/position_policy/suspensions），但**无 topic_admission**；无 `topic_matcher`。→ 真增量。
- **依赖缺口**：`topic_matcher` 为全新工具；`ProductExtension.topic_rule_audience_policy` 扩展点字段（5.1 已决定不合并，不会随之引入）→ 若合入 5.3 需**自行补该扩展点字段**。
- **风险**：中等。

### 5.4 模型组（model_groups，全新域，~21 文件）

- **himovo 侧**：`chat-api app/llm/model_group_config.py`；admin-api `api/routes/model_groups.py` + `repositories/{model_group_repository,model_identity_index}.py` + `services/{model_pricing,model_knowledge_connectivity,model_test_tls}.py`；admin-web `components/models/{ModelAccessExtensionPanel,ModelGroupCard,ModelGroupEditor,ModelGroupMemberRow,ModelGroupTestPane,ModelPricingFields}.vue`（6）+ `composables/{useModelAccessExtension,useVisionCapabilitySuggestion}.ts` + `locales/modules/modelAccess.ts` + `components/models/{modelApiError,modelTestKind}.ts`。
- **本地状态**：admin-api 无 model_group；`llm/` 已有 configured_models/model_router（不同体系）。→ 真增量。
- **依赖缺口**：`ProductExtension.model_access_policy` 扩展点字段（5.1 已决定不合并，不会随之引入）→ 若合入 5.4 需**自行补该扩展点字段**。
- **风险**：中等。

### 5.5 docx 审阅（docx_review，全新域，~12 文件）

- **himovo 侧**：`chat-api app/enterprise_capabilities/docx_review/{__init__,annotations,comment_content,service,source}.py`（5）+ `app/tools/docx_structure.py`；admin-web `components/workflow/ReviewCheckNodeConfig.vue` + `reviewSourceBinding.ts`；user-web `components/workflow/{ReviewCheckNodeConfig,KnowledgeDocumentSourceConfig,PersonalKnowledgeDocumentPicker}.vue` + `reviewSourceBinding.ts`。
- **本地状态**：本地有 `enterprise_capabilities/pdf_editing/`、`delivery/`，但**无 docx 审阅**。→ 真增量。
- **风险**：中等（docx 解析依赖 python-docx 是否已装）。

### 5.6 workflow 审阅（workflow_messages / node_bindings，全新域，~26 文件）

- **himovo 侧**：`chat-api app/api/{workflow_messages,workflow_check_messages}.py` + `services/workflow_node_bindings.py`；admin-web/user-web `components/workflow/*`、`workflow{NodeCatalog,SectionStructure,DefaultLocale,ResponseText,RequiredSelections}.ts`、`locales/{reviewWorkflow,skillWorkflowEditor,workflowSelectOptions,workflowTextInferenceRules,workflowNodeUsageMessages}.ts`。
- **本地状态**：本地无 ReviewCheckNode / reviewSourceBinding。→ 真增量。
- **风险**：中等（前端 workflow 编辑器是本地已存在的大模块，需接入现有节点目录）。

### 5.7 用户问题（user_questions，全新域，~11 文件）

- **himovo 侧**：`chat-api app/api/endpoints/user_questions.py` + `dsh_runtime/conversation/{question_answers,sequence_allocator}.py`；user-web `api/userQuestions.ts` + `composables/useUserQuestions.ts` + `components/chat/{UserQuestionPanel,AnsweredQuestionMessage}.vue` + `questionAnswerHistory.ts` + `tests/question-answer-history.test.ts`。
- **本地状态**：无。→ 真增量。
- **风险**：中等。

### 5.8 企业邀请（invite，全新域，~10 文件）— 已决定不合并

- **himovo 侧**：admin-api `api/routes/{invite_history,invite_members}.py` + `services/{invite_acceptances,invite_links,invite_policy}.py`；admin-web `views/organizations/{InviteHistoryPanel,InviteHistoryRow,InviteMemberDetail}.vue`；user-web `api/invitations.ts` + `components/login/InvitationRegistrationForm.vue`。
- **本地状态**：admin-web `views/organizations/` 无 invite；admin-api 无 invite 服务。→ 虽为本地缺失域，但**用户已明确决定不合并**，故从候选清单移除。

### 5.9 sandbox 审计内部端点（小，低风险）

- **himovo 侧**：`chat-api app/api/endpoints/sandbox_audit_internal.py` + `tests/execution_isolation/test_sandbox_audit_internal.py`。
- **本地状态**：已有 `execution_isolation/audit_reader.py`（himovo 的 `test_audit_reader.py` 亦为独有测试，说明本地 audit_reader 实现与 himovo 可能不同）。→ 仅缺端点，**可低风险补**，但需核对与本地 audit_reader 的接口一致性。

### 5.10 migrations / sequence 修复（高风险，数据迁移）

- **himovo 侧**：`chat-api app/migrations/{__main__,sequence_index,sequence_repair}.py` + `deploy/cli/sequence-fix.sh` + `deploy/cli/migrations.sh`。
- **本地状态**：已有 `migrations/session_sharing.py`（迁移机制存在）。→ 增量是 **sequence 修复脚本**，属数据修复类，需在副本库先演练。
- **风险**：高（可能修改现有数据）。

---

## 6. 明确「不合并 / 暂缓」说明

- **本地已覆盖（不合并，避免双实现冲突）**：browser 引擎、content 写作引擎、evidence/knowledge 基础、knowledge_source 配置、skill 支持、模型配置/视觉、session snapshot 用户态、知识库文档页样式、skill/tool 编辑器样式、user-web app shell。
  - 理由：本地这些域已用 mogo 品牌**自主实现且更成熟**（如 `browser/engine` 本地 ~70 文件 vs himovo 10 个 `browser_run_*`；`evidence/foundation` 本地 ~12 文件 vs himovo 1 个 `source_labels.py`）。合入 himovo 版本会造成**两套代码 + 命名冲突 + 行为分歧**。
- **用户已取消（不合并）**：三期-b desktop 域（user-web `components/desktop/`、`composables/desktop/`、`platform/windowsPlatform.ts`、`styles/windows-dark/*`、`Desktop*`/`WindowsTitleBar` 组件）、session snapshot 用户态前端（`SessionSnapshot*`、`sessionSnapshots.ts`、`session_snapshots.py`、`desktop_question_answers.py`）。
- **暂缓（P4 惯例 / 基础设施）**：暗色主题（admin-web `theme/*`、`dark-*.css`、`naive-overrides.ts`、`workflow-colors.ts` + user-web `naiveThemeOverrides.ts`）、i18n 文案 `locales/*.ts`（52 文件，纯文案，key 体系不同，不随代码合入）、qa/playwright（10）、CI 镜像源/发布/校验脚本（`qa/*`、`.github/*`、`deploy/docker/infra-mirror/*`、`scripts/{publish_cn_multiarch,check_*}.sh/py`）。
- **品牌冲突（不适用）**：根目录 `movo`（himovo 的 CLI 启动脚本）——本地已有 `mogo` CLI；品牌字符串 `movo.community`/`MOVO_PRODUCT_EXTENSION_MODULE`——仅在合入 5.1 时需改写回 `mogo.*`/`MOGO_*`（5.1 现已决定不合并，当前不再涉及）。

---

## 7. 依赖缺口汇总（合并候选的前置条件）

| 缺口 | 涉及候选 | 本地现状 |
|---|---|---|
| `dsh_runtime/plugin_management` 需接入现有 profile/gateway | 5.2 | 本地 profile 有 bundle/catalog 体系，需确认调用点 |
| `ProductExtension` 的 `member_limit_resolver` / `model_access_policy` / `resource_access_policy` / `topic_rule_audience_policy` 4 字段 | ~~5.1~~（不合并）/ 5.3 / 5.4 | 本地 ProductExtension **无这 4 字段**；5.1 已决定不合并故不会引入，若合入 5.3/5.4 需**自行补对应扩展点字段** |
| `topic_matcher` 工具 | 5.3 | 本地无（全新） |
| python-docx 依赖 | 5.5 | 需确认是否在 requirements |
| 沙箱镜像构建链接入 `Dockerfile.sandbox-script` | 5.2 | 需确认现有沙箱镜像如何挂脚本 |

---

## 8. 结论：本次不执行任何合并

1. **himovo 无新提交**，本次没有「增量」可吃；本地已远超 himovo（1443 本地独有文件）。
2. **剩余候选均为整域移植**（前后端 + 依赖 + 测试），非零成本；且大部分「看似独有」的功能本地已自主实现，**合并会制造双实现冲突**。
3. 若后续要动，**只建议从低风险小项开始**：`5.9 sandbox 审计端点`、`5.10 sequence 修复（先演练）`。其余 5.2~5.7 建议**先开独立分支逐域评估**，勿整批合入（5.1 企业成员策略 + 5.8 企业邀请已决定不合并）。
4. 本分析**未修改任何代码、未执行任何 git 操作**（除只读 diff）。

---

## 附录：本次比对命令（可复现）

```bash
# 1) 确认 himovo 无新提交
git fetch himovo
git rev-list --count 305bd927..himovo/main        # = 0
git log --oneline -1 himovo/main                  # 305bd927

# 2) himovo 独有文件清单
git diff --diff-filter=A --name-only HEAD himovo/main | sort > /tmp/himovo_only.txt
wc -l /tmp/himovo_only.txt                        # 606
cut -d/ -f1-2 /tmp/himovo_only.txt | sort | uniq -c | sort -rn

# 3) 全部差异状态
git diff --name-status HEAD himovo/main | awk '{print $1}' | sort | uniq -c

# 4) 305bd927 引入文件
git show --stat --oneline 305bd927

# 5) 关键域差异（browser / writer / evidence / profile-skills / product_edition）
git diff HEAD himovo/main -- services/chat-api/app/core/product_edition.py \
  services/chat-api/app/product/extensions.py
ls services/chat-api/app/enterprise_capabilities/browser/engine/    # 本地 ~70 文件
ls services/chat-api/app/enterprise_capabilities/content/writer_engine/unified_compose/
```
