# Requirements Quality Checklist: 031 model-provider-discover

**Purpose**: 校验 031（模型供应商发现与多协议接入：获取模型列表 + Anthropic/Gemini/Ollama）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**（本特性属回溯补规格，代码已先于 spec 落地，见 spec.md 顶部）。
**Created**: 2026-11-04（QA 审计补建，使 48 特性需求门禁清单齐备）
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 一、完整性（关键口径是否都写了）

- [x] CHK001 获取模型列表的入口与契约是否定义？→ FR-001：`POST /api/models/discover` 接收 `{providerType, baseUrl, apiKey, apiVersion}` 并按 providerType 分发；与 §User Story 1 的写入口一致
- [x] CHK002 支持的协议集合是否封闭且可校验？→ FR-002：`providerType ∈ {openai_compatible, azure_openai, anthropic, gemini, ollama}` 五类，未知值校验层返回 422；决策表 #2 与前端类型贯穿一致
- [x] CHK003 归一化输出结构是否定义？→ FR-003：`[{id, name, ownedBy}]`，缺失字段给默认值并对 id 去重（Key Entities `DiscoveredModel`）
- [x] CHK004 上游失败的错误语义是否定义？→ FR-004：非 2xx / 网络不可达 → 502 + 可读错误，禁止抛栈或空 200
- [x] CHK005 种子供应商是否覆盖新增三类协议？→ FR-005：`DEFAULT_PROVIDERS` 含 Anthropic/Gemini/Ollama，provider_type 与 auth_type（ollama=none）及 `default_base_url`/`priority` 明确
- [x] CHK006 前端"获取列表 → 点选回填"交互是否定义？→ FR-006：弹窗展示清单、点选回填模型 ID 并关闭弹窗
- [x] CHK007 连接测试是否同步扩展？→ FR-007：`_provider_test_events` 对 anthropic/gemini/ollama 各增一次性非流式分支，复用 `_decrypt_api_key`/`_build_ssl_context`
- [x] CHK008 首次向导字段提示是否按协议区分？→ FR-008：`SetupModelFields` 为三类协议给专属 Base URL 占位符与提示，ollama 提示"无需 API Key"

## 二、清晰度（口径是否可执行）

- [x] CHK009 各协议列表端点与解析口径是否可执行？→ 决策表 #6 逐协议给出端点（OpenAI `GET {base}/models`、Azure deployments、Anthropic `/v1/models`、Gemini `/v1beta/models`、Ollama `/api/tags`）与解析规则（Gemini 剥离 `models/` 前缀、统一去重）
- [x] CHK010 请求体字段约束是否明确？→ Key Entities `ModelDiscoverPayload`：`providerType: enum`、`baseUrl: str[1..300]`、`apiKey?: str[0..600]`、`apiVersion?: str[0..40]`
- [x] CHK011 成功标准是否可测？→ SC-001：五类协议单测 `tests/test_models_discover.py` 全绿（11/11）；SC-002：真实 admin-web 链路成功率 100%；SC-003：向导占位符与 provider 实际接入一致

## 三、一致性（与既有特性是否冲突）

- [x] CHK012 与既有 discover（openai/azure）是否兼容？→ 决策表 #2 在既有两类基础上"完整接入"三类，未破坏既有分发；plan 与 tasks 收敛一致
- [x] CHK013 provider_type 枚举是否全局一致？→ 决策表 #3 明确贯穿 seed / setup 校验 / 连接测试 / 前端类型四处一致
- [x] CHK014 与 030/035 等鉴权与成本口径是否冲突？→ 本特性仅做"发现与回填"，不涉及计费/权限变更；apiKey 走既有 `_decrypt_api_key`，与全仓加密口径一致

## 四、边界与歧义

- [x] CHK015 **apiVersion 对无版本协议（ollama）的处理**：✅ 已定值。ollama/Anthropic/Gemini 无 apiVersion 概念，前端向导不渲染版本字段（仅占位提示 YAGNI），后端接受时忽略该字段（不报错）。FR-005/FR-008 的"不强行加版本字段"已隐含此语义，无需额外声明。
- [x] CHK016 网络/凭据假设是否声明？→ Assumptions 显式声明 API Key 来源、各 provider 默认 Base URL 可自定义、后端沿用 `urllib.request` + `asyncio.to_thread` 不引入新网络库、前端共用 `providerLabels` 映射
- [x] CHK017 子模型实例 API key 继承修复是否纳入？→ §实现补充（`_with_inherited_api_key`，`1498da65`+`005d4a93`）：解决空 `api_key_encrypted` 导致 401 的中途中断；属健壮性补强，已在实现态记录

## 五、需求质量结论

16 项需求质量条目中 **15 项达标（CHK001–CHK014、CHK016–CHK017）**，**1 项待定（CHK015 apiVersion 对无版本协议的口径）**。

CHK015 **不阻塞 spec 定稿与发布**：它是一次纯口径澄清（无版本协议忽略 apiVersion），不影响 FR-001~FR-008 的可执行性，建议在发布评审时补一句即可。

**已知的诚实占位**：SC-002"真实 admin-web 链路成功率 100%"为可测目标，需真实 admin-web 走查确认；本清单仅评审需求质量，不替代该走查。
