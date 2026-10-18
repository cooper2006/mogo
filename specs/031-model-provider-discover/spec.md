# Feature Specification: 模型供应商发现与多协议接入（获取模型列表 + Anthropic/Gemini/Ollama）

**Feature Branch**: `031-model-provider-discover`

**Created**: 2026-10-18

**Status**: Draft（已落地部分代码，见 §「实现状态」）

**Input**: User description: "admin-web 新增模型配置中不用手填模型 ID，参考 dsh 模型功能，增加「获取模型列表」功能，从模型列表直接保存；并把 discover 支持扩展到 Anthropic Claude / Google Gemini / Ollama（本地）三种协议，同时在首次配置向导里为这三种协议加上专属字段提示"

> **设计来源**：本规约把已在 commit `6ea16f3` 落地的实现固化为 spec/plan/tasks（代码先于 spec，与 027、030 同类处理）。冲突时以代码 + 本 spec 的 FR 为准。
>
> **性质说明**：**回溯补规格** —— 后端 discover 端点、三协议种子、前端「获取列表」弹窗与首次向导字段提示均已实现；本文件把实现口径与剩余任务一并固化，后续按 tasks.md 收敛。

## 定位（一句话）

在「新增模型配置」中免去手敲模型 ID 的摩擦：用户选好供应商后点「获取列表」，由 **admin-api 用已配置的 baseUrl + apiKey 直连各 provider 真实 API** 拉回可用模型清单，点选即回填模型 ID 并保存；本次将 discover 从无差别的 OpenAI/Azure 扩展到 **Anthropic Claude、Google Gemini、Ollama（本地）** 三类协议，并补齐首次配置向导（`SetupModelFields`）对这三类的专属字段提示。

## 已定决策（2026-10-18，实现落地时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 「获取模型列表」的数据来源 | **代理 provider 真实 API**（用已配置的 baseUrl + apiKey 调各 provider 的 models 列表接口），不引入 dsh 内部 catalog 静态清单 | `models.py` `_discover_*_models` 系列 |
| 2 | discover 支持哪些协议 | 在既有 `openai_compatible` / `azure_openai` 基础上，**完整接入** `anthropic` / `gemini` / `ollama` 三类（种子 + 前端类型/标签 + 连接测试分发） | `model_repository.py` DEFAULT_PROVIDERS + `models.py` 路由分发 |
| 3 | provider_type 体系 | 全局 provider_type 取值扩展为 `openai_compatible | azure_openai | anthropic | gemini | ollama`，贯穿 seed、setup 校验、连接测试、前端类型 | 三处一致 |
| 4 | 连接测试（Connection Test）是否同步扩展 | 是 —— `_provider_test_events` 增加 anthropic/gemini/ollama 三个一次性非流式测试分支，与 discover 共用 `_decrypt_api_key` / `_build_ssl_context` | `models.py` `_anthropic_test_events` / `_gemini_test_events` / `_ollama_test_events` |
| 5 | 首次向导字段提示 | `SetupModelFields` 为三类新协议给出专属 Base URL 占位符、模型 ID 占位符与字段提示（feedback），不新增无关字段（如为无 API Version 的协议强行加版本字段） | `SetupModelFields.vue` |
| 6 | 各协议列表端点与解析口径 | OpenAI: `GET {base}/models`；Azure: `GET {base}/openai/deployments?api-version=`；Anthropic: `GET {base}/v1/models`（header `x-api-key` + `anthropic-version`）；Gemini: `GET {base}/v1beta/models?key=`（剥离 `models/` 前缀）；Ollama: `GET {base}/api/tags`；统一返回 `[{id,name,ownedBy}]` 并去重 | `models.py` 纯函数 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 新增模型配置时用「获取模型列表」点选保存（Priority: P1）

租户管理员在 admin-web「模型管理 → 新增模型配置」里选好供应商、填好 Base URL 与 API Key，点「获取列表」按钮，后端直连该 provider 真实 API 拉回可用模型清单，弹窗展示（模型 ID / 名称 / 提供方），点选一项即把模型 ID 回填到表单并关闭弹窗，管理员再填配置名称保存即可，全程无需手敲模型 ID。

**Why this priority**: 这是整个特性的**唯一写入口与最高频摩擦点**——手敲模型 ID 易错（大小写、日期后缀、部署名差异）。点选回填即构成可交付 MVP。

**Independent Test**: 用 `azure_openai` / `anthropic` / `gemini` / `ollama` 任一可达的测试凭据，在 admin-web 走完整「获取列表 → 点选 → 保存」链路；并直接对 `POST /api/models/discover` 发请求，断言返回结构为 `[{id,name,ownedBy}]` 且不含重复项。

**Acceptance Scenarios**:

1. **Given** 已选供应商且 Base URL / API Key 非空，**When** 点「获取列表」，**Then** 后端按 provider_type 分发到对应 discover 函数，返回去重后的模型清单；前端弹窗逐行展示并可点选。
2. **Given** 某 provider 的列表接口返回 4xx/5xx 或网络不可达，**When** 调用 discover，**Then** 后端返回 502 并附可读错误（`_format_url_error`），前端提示拉取失败而不静默卡死。
3. **Given** 点选列表中的某项，**When** 确认，**Then** 模型 ID 被回填、弹窗关闭，且表单其余字段（Base URL / Key）保持不变。
4. **Given** provider_type 为未知值（如 `foo`），**When** 提交 discover，**Then** 请求在 pydantic 校验层返回 422，不进入分发逻辑。

---

### User Story 2 - 后端 discover 覆盖五类协议且统一返回结构（Priority: P1）

admin-api 的 `POST /api/models/discover` 按 `providerType` 分发给五类协议的 discover 纯函数，每类把各自响应归一化为 `[{id,name,ownedBy}]`，对缺字段/重复项做稳健处理；同时连接测试 `_provider_test_events` 同步分发到三协议分支。

**Why this priority**: 这是 US1 的底座。没有它，前端「获取列表」无从拉数据；统一返回结构是前端弹窗能复用的前提。

**Independent Test**: `tests/test_models_discover.py` 11 项 —— 覆盖 OpenAI/Azure 解析、Anthropic/Gemini/Ollama 解析、HTTP 错误→502、路由分发（openai/anthropic/gemini/ollama）、未知类型→422。全部通过即独立可证伪。

**Acceptance Scenarios**:

1. **Given** `providerType=anthropic` 且 baseUrl 指向一个返回 `[{id:"claude-3-5-sonnet-20241022",type:"..."}]` 的 mock，**When** 调 discover，**Then** 返回 `[{id:"claude-3-5-sonnet-20241022",name:"claude-3-5-sonnet-20241022",ownedBy:"anthropic"}]`。
2. **Given** `providerType=gemini` 且响应含 `models/gemini-1.5-pro` 形式的 name，**When** 调 discover，**Then** 返回项的 `id` 为去掉 `models/` 前缀的 `gemini-1.5-pro`。
3. **Given** `providerType=ollama` 且 `/api/tags` 返回 `[{name:"llama3.1",details:{family:"llama"}}]`，**When** 调 discover，**Then** 返回 `[{id:"llama3.1",name:"llama3.1",ownedBy:"ollama"}]`。
4. **Given** 任意协议列表出现重复 id，**When** 解析完成，**Then** 结果去重，不出现两项同 id。

---

### User Story 3 - 种子供应商 + 首次配置向导字段提示（Priority: P2）

在 `DEFAULT_PROVIDERS` 种子中新增 Anthropic Claude / Google Gemini / Ollama（本地）三条（provider_type 分别对应 anthropic / gemini / ollama，auth_type 为 api_key / api_key / none），使首次配置向导与模型管理页都能选到；并在首次向导 `SetupModelFields` 中为这三类给出专属 Base URL 占位符、模型 ID 占位符与字段提示（feedback）：anthropic/gemini 说明官方地址与鉴权方式、ollama 说明本地地址且无需 API Key。

**Why this priority**: 降低首次接入三类协议的学习成本，避免把 anthropic 的 Base URL 提示写成 `https://api.openai.com/v1` 这类误导性通用占位。优先级低于 US1/US2，因为向导提示不阻塞列表拉取能力本身。

**Independent Test**: 前端用 `@vue/compiler-sfc` 单文件编译 `SetupModelFields.vue` 通过；手动核对切换供应商时 Base URL 占位符与 feedback 文案随 provider_type 变化（anthropic→`https://api.anthropic.com`、gemini→`https://generativelanguage.googleapis.com`、ollama→`http://localhost:11434` 且提示「无需 API Key」）。

**Acceptance Scenarios**:

1. **Given** 向导中切到 Anthropic Claude，**When** 查看 Base URL 字段，**Then** 占位符为 `https://api.anthropic.com`，且出现字段提示说明以 `/v1/models` 拉清单、需 `x-api-key`。
2. **Given** 向导中切到 Google Gemini，**When** 查看 Base URL 字段，**Then** 占位符为 `https://generativelanguage.googleapis.com`，提示 Key 经 URL 参数传递。
3. **Given** 向导中切到 Ollama（本地），**When** 查看 Base URL / API Key 字段，**Then** 占位符为 `http://localhost:11434`，API Key 字段提示「本地部署默认无需 API Key，可留空」。

---

### Edge Cases

- **provider_type 未知**：`ModelDiscoverPayload.providerType` 用正则 `^(openai_compatible|azure_openai|anthropic|gemini|ollama)$` 约束，非法值直接 422，不进分发逻辑。
- **列表接口超时 / TLS 错误**：discover 走 `urllib` + `asyncio.to_thread` + `_build_ssl_context()`，失败统一转 502（`_format_url_error`），不把底层异常抛给前端。
- **anthropic-version 头**：调用 Anthropic 列表接口须带 `anthropic-version: 2023-06-01`（后端固定，不暴露给用户），缺失会导致 401。
- **gemini key 位置**：Gemini 的 key 经 URL `?key=` 传递而非 Authorization 头；后端构造 URL 时拼入，避免把 key 写进 header。
- **ollama 无鉴权**：auth_type=none，API Key 可空；向导对 ollama 显式提示无需 Key。
- **空列表**：provider 返回空数组时，前端弹窗提示「未获取到模型，请检查配置」而非报错崩溃。
- **向导 Base URL prefill**：切供应商时 `watch` 已按 `defaultBaseUrl` 预填 Base URL（anthropic/gemini/ollama 各自默认值），字段提示只是辅助、不覆盖已填值。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供 `POST /api/models/discover`，接收 `{providerType, baseUrl, apiKey, apiVersion}` 并按 providerType 分发到对应 discover 实现。
- **FR-002**: 系统 MUST 支持 `providerType ∈ {openai_compatible, azure_openai, anthropic, gemini, ollama}` 五类，未知值 MUST 在请求校验层返回 422。
- **FR-003**: 各 discover 实现 MUST 把 provider 原生响应归一化为 `[{id, name, ownedBy}]`，对缺失字段给默认值并对 id 去重。
- **FR-004**: 当 provider 列表接口返回非 2xx 或网络不可达时，discover MUST 返回 502 并附可读错误，不得抛出栈或返回空 200。
- **FR-005**: `DEFAULT_PROVIDERS` 种子 MUST 包含 Anthropic Claude / Google Gemini / Ollama（本地）三条，provider_type 分别为 anthropic / gemini / ollama，auth_type 为 api_key / api_key / none，并带正确的 `default_base_url` 与 `priority`。
- **FR-006**: 前端新增模型配置页 MUST 提供「获取列表」入口，调用 discover 后在弹窗展示清单，点选即回填模型 ID 并关闭弹窗。
- **FR-007**: 连接测试（`_provider_test_events`）MUST 对 anthropic / gemini / ollama 各提供一次性非流式测试分支，复用既有 `_decrypt_api_key` / `_build_ssl_context`。
- **FR-008**: 首次配置向导 `SetupModelFields` MUST 为 anthropic / gemini / ollama 提供专属 Base URL 占位符与字段提示（feedback），ollama MUST 提示「无需 API Key」。

### Key Entities

- **ModelDiscoverPayload**: `{providerType: enum, baseUrl: str[1..300], apiKey?: str[0..600], apiVersion?: str[0..40]}`，discover 请求体。
- **DiscoveredModel**: `{id: string, name: string, ownedBy: string}`，归一化后的模型清单项（前端 `models.ts` 接口）。
- **Provider seed（DEFAULT_PROVIDERS 条目）**: `{name, code, provider_type, default_base_url, auth_type, status, priority}`，决定向导可选供应商与默认值。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 五类协议的 discover 在单测下均返回结构正确、去重、错误转 502；`tests/test_models_discover.py` 全绿（11/11）。
- **SC-002**: 管理员在真实 adman-web 走「获取列表 → 点选 → 保存」链路成功率 100%（手敲 ID 摩擦归零）。
- **SC-003**: 首次向导切到 anthropic/gemini/ollama 时，Base URL 占位符与字段提示与 provider 实际接入方式一致（不再出现 `https://api.openai.com/v1` 误导 ollama/anthropic 用户）。

## Assumptions

- 假设用户已在对应 provider 处取得可用 API Key（Ollama 本地部署可无 Key）。
- 假设 provider 列表接口地址与官方一致（anthropic `https://api.anthropic.com`、gemini `https://generativelanguage.googleapis.com`、ollama `http://localhost:11434`），用户可自定义 Base URL 指向代理/网关。
- 假设后端沿用标准库 `urllib.request` + `asyncio.to_thread`（admin-api 无 httpx 依赖），不引入新网络库。
- 假设前端 setup 向导与模型管理页共用 `@/components/models/providerLabels` 的 provider 标签映射，保持一致。
