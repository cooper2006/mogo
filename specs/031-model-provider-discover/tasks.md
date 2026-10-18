# Tasks: 模型供应商发现与多协议接入（031-model-provider-discover）

**Input**: Design documents from `/specs/031-model-provider-discover/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: 代码先行的回溯补规格。实现已于 commit `6ea16f3` 落地（`feat(models): 新增「获取模型列表」并支持 Anthropic/Gemini/Ollama`），本任务清单把已实现项勾选并补本轮新增的向导字段提示。

**Tests**: admin-api `tests/test_models_discover.py` 11 项（已实现，全绿）；前端用 `@vue/compiler-sfc` 单文件编译校验 SFC。

**Organization**: 任务按 user story 分组；已落地项标记 `[x]` 并附证据，本轮新增项标记 `[ ]`。

---

## Phase 1: Setup（已落地）

- [x] T001 建立 spec/plan/tasks 三件套（`specs/031-model-provider-discover/`，本文件）
- [x] T002 确认 provider_type 五值体系 `openai_compatible|azure_openai|anthropic|gemini|ollama` 在 seed/setup/连接测试/前端四处一致

---

## Phase 2: Foundational（已落地，US1/US2/US3 的底座）

- [x] T003 [P] [US2] `services/admin-api/app/api/routes/models.py`：`ModelDiscoverPayload` 正则扩展为五协议；新增 `POST /api/models/discover` 按 providerType 分发
- [x] T004 [P] [US2] `models.py`：新增 `_discover_openai_compatible_models` / `_discover_azure_models` / `_discover_anthropic_models` / `_discover_gemini_models` / `_discover_ollama_models` 五个纯函数，统一返回 `[{id,name,ownedBy}]` 并去重
- [x] T005 [P] [US2] `models.py`：HTTP 错误/网络不可达统一转 502（`_format_url_error`）；复用既有 `_build_ssl_context()`
- [x] T006 [P] [US2] `models.py`：`_provider_test_events` 新增 `_anthropic_test_events` / `_gemini_test_events` / `_ollama_test_events` 一次性非流式分支，复用 `_decrypt_api_key`
- [x] T007 [P] [US3] `services/admin-api/app/repositories/model_repository.py`：`DEFAULT_PROVIDERS` 新增 anthropic（priority 40）/ gemini（priority 50）/ ollama（priority 80）三条种子（auth_type api_key/api_key/none）

**Checkpoint**: 后端 discover 与连接测试五协议齐备，种子就绪

---

## Phase 3: User Story 1 - 新增配置「获取列表」点选保存（Priority: P1）🎯 MVP（已落地）

**Goal**: 选供应商后点「获取列表」拉真实模型清单，点选回填 ID 保存，免去手敲。

### Tests for User Story 1

- [x] T008 [P] [US1] `services/admin-api/tests/test_models_discover.py`：路由分发（openai/anthropic/gemini/ollama）+ HTTP 错误→502 + 未知类型→422（共 11 项，全绿）

### Implementation for User Story 1

- [x] T009 [P] [US1] `apps/admin-web/src/api/models.ts`：新增 `discoverProviderModels()` 与 `DiscoveredModel` 接口；`providerType` 联合类型扩展为五值
- [x] T010 [P] [US1] `apps/admin-web/src/components/models/providerLabels.ts`：`providerMessageKeys` 新增 anthropic/gemini/ollama
- [x] T011 [US1] `apps/admin-web/src/views/models/ModelsPage.vue`：模型 ID 字段改 `n-input-group` +「获取列表」按钮；新增模型选择弹窗（列表点选回填 `form.modelName`）；`providerType` computed 与 `modelFieldPlaceholder`/`baseUrlPlaceholder` 按五协议给出占位符

**Checkpoint**: US1 可独立测试——真实 admin-web 走「获取列表 → 点选 → 保存」链路，手敲 ID 摩擦归零

---

## Phase 4: User Story 2 - 后端 discover 五协议 + 统一结构（Priority: P1）（已落地）

**Goal**: discover 按 providerType 分发，归一化结构、去重、错误转 502。

### Implementation for User Story 2

- [x] T012 [P] [US2] 五协议 discover 纯函数（见 T004）解析口径：anthropic `GET {base}/v1/models`（header `x-api-key`+`anthropic-version`）；gemini `GET {base}/v1beta/models?key=`（剥离 `models/` 前缀）；ollama `GET {base}/api/tags`；openai `GET {base}/models`；azure `GET {base}/openai/deployments?api-version=`
- [x] T013 [P] [US2] `ModelDiscoverPayload.providerType` pydantic 正则约束未知值→422；参数顺序与占位符按 A 模式位置绑定纪律

**Checkpoint**: US2 由 `test_models_discover.py` 11/11 独立证伪

---

## Phase 5: User Story 3 - 种子 + 首次向导字段提示（Priority: P2）

**Goal**: 三类新协议可在向导中选到，且 Base URL / 模型 ID 占位符与字段提示与真实接入方式一致。

### Implementation for User Story 3（部分已落地，向导提示为新增）

- [x] T014 [P] [US3] 种子三类（见 T007）已落地，向导与模型页均可选
- [x] T015 [US3] `apps/admin-web/src/components/setup/SetupModelFields.vue`：扩展 `modelPlaceholder` / `baseUrlPlaceholder` computed，按 providerType 为 anthropic/gemini/ollama 给专属占位符；新增 `baseUrlFeedback` / `apiKeyFeedback` 字段提示（ollama 标注「无需 API Key」），并在对应 `n-form-item` 挂 `:feedback`（2026-10-18 落地，SFC 编译通过）

**Checkpoint**: US3 独立可测——`@vue/compiler-sfc` 编译 SetupModelFields.vue 通过；切供应商时占位符/提示随 provider_type 变化

---

## Phase 6: Polish & Cross-Cutting（收尾）

- [x] T016 [P] 在 `specs/INDEX.md` 登记 031 条目（「四（补 5）」+ 顶部 2026-10-18 补充 + 计数 30→31）并更新
- [x] T017 [P] 用 `@vue/compiler-sfc` 校验 `SetupModelFields.vue` SFC 编译通过（替代全量 vue-tsc/build）
- [x] T018 提交并推送本轮向导扩展改动（`git add` 具体文件，推 `cooper2006/mogo`，commit `6a2e46b`，5 files）；更新 `specs/031` 任务勾选状态（含本条）

---

## Dependencies & Execution Order

- Setup/Foundational 已完成（commit `6ea16f3`）。
- US1/US2 已完成，互相独立但共用 `_discover_*_models` 与 `ModelDiscoverPayload`。
- US3 仅剩 T015（向导字段提示）待本轮执行；T016/T017/T018 为收尾。
- T015 不依赖其他会话改动，可独立落地；前端校验走 SFC 编译（本机 vue-tsc/build >10min，按既有约束规避）。

## Notes

- `n-input-group` 未在 `bootstrap.ts` 全局注册，ModelsPage.vue 已局部 `import { NInputGroup }`；SetupModelFields.vue 改动沿用既有组件、无需新增全局注册。
- 三类新协议无 API Version 概念（anthropic-version 由后端固定、gemini 走 URL key、ollama 无版本），故向导**不**为它们新增版本字段，仅以占位符+feedback 提示，符合 YAGNI。
- i18n 新文案用中文 key，`t()` 缺翻译时回退中文本身，无需改 locale 文件。
