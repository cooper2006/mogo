# Requirements Quality Checklist: 041 connector-market

**Purpose**: 校验 041（连接器市场：预置模板目录 + 从模板创建 + 凭证托管依赖）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 模板参数 schema 的"描述对象"未定义（FR-001 要求每模板含"参数 schema"，Key Entities 给 `param_schema`，Edge Case「模板 schema 与 `tools.py` payload 结构不一致」要求"按模板 schema 校验参数，再映射到既有 payload"；但既有 `config` 存在两套互不相同的入参结构——HTTP 侧是 `url`/`method`/`headers`/`authType`/`authToken`/`apiKeyHeader`/`timeoutSeconds`，MCP 侧是 `inputSchema` 逐节点 `name`/`type`/`location`/`require`/`value`——模板 schema 究竟描述"连接参数"还是"业务入参"、是否两者都要，未写）
- [x] CHK002 模板字段的必填集与类型未穷举（FR-001 列 标识/名称/类别/版本/描述/认证类型/参数 schema/示例参数/测试建议 9 项，但 `category` 的合法取值（plan.md:35-41 五类 vs 自由文本）、`example_params` 与 `param_schema` 的键对应关系、`test_hint` 是自由文本还是结构化（plan.md:43 说"探测端点/预期状态码"）均未定义；US1-2 说详情"展示测试建议"，未说它是否参与创建/测试链路）
- [x] CHK003 安装记录的存储与"模板来源"在工具记录上的留痕未定义（Key Entities 给 `ConnectorInstall{template_id, tenant_id, tool_id, installed_at, installed_by}`，plan.md:19 只说新集合 `connector_installs`；但 FR-003 要求"经既有创建路径落库"，而 `ToolPayload` 只有 `name`/`type`/`description`/`usageHint`/`tags`/`status`/`config`——**没有 `template_id`/`template_version` 字段，多传即被 pydantic 丢弃**，"从哪个模板创建"在既有存储上无法留痕，未写替代口径）
- [x] CHK004 种子加载告警的落点与两级校验未定义（US1-3"跳过该模板并记录告警"、Edge Case「模板种子含真实凭证」"拒绝加载该模板并告警"——告警写进程日志/审计集合/启动响应哪一处、损坏模板与含真实凭证是否同一通道同一严重级、被跳过模板是否计入列表 `total`，未写）
- [x] CHK005 首批清单的自检判据未定义（FR-011 说 10–20 个、plan.md:35-41 建议 18 个，SC-005 说"≥10 个模板可加载、可创建、可测试"；但"可测试"是否要求真实第三方可达（离线/无外网环境如何验收）、18 与 ≥10 冲突时以谁为准、模板数量是否进测试断言，未写）

## 清晰度（Clarity）

- [x] CHK006 「测试连接」的成功判定未定义（FR-005 只说"复用既有 test 链路；失败 MUST 返回可读错误"；既有 `POST /api/tools/{tool_id}/test` 先过 `_enforce_gate` 六层门禁，返回体含 `success`/`status`（passed|failed）/`message`/`responseSummary` 并置头 `X-MOGO-Operation-Result: success|failed`（`_operation_succeeded` 判 `success is not False` 且 `status ∉ {failed,error}`）——"测试通过"以哪个字段为准、门禁拒绝算"测试失败"还是"未测试"、向导据何判定可上架，未写）
- [x] CHK007 「上架（active）」的操作语义未定义（US2-3"测试通过并上架（active）"，但既有 `create_tool` 恒定写 `status="disabled"`（`tools.py:241-261` 字典字面量后置覆盖），上架只能再 `PATCH /api/tools/{tool_id}`；且 `_validate_final_activation` 对 `type=mcp` 且 `status=active` 强制要求 `enabled_mcp_tool_names(config)` 非空（`app/api/tool_limits.py:26-32`）——"上架"是一次 PATCH 还是创建时可带 active、测试未通过能否上架、上架失败如何反馈，未写）
- [x] CHK008 安装计数的计数语义未定义（FR-007"记录模板安装计数（按模板 × 租户）"——是 `connector_installs` 行数聚合还是工具记录上的冗余计数器（并发 `$inc` 与丢更新风险）、删除连接器是否递减、Edge Case「同名模板重复安装」每次是否 +1、计数为 0 的模板是否返回，未写）
- [x] CHK009 市场列表搜索与筛选口径未定义（FR-002"按类别筛选与关键词搜索"——关键词命中 `name`/`description`/`tags`/参数说明中的哪些字段、大小写与中英文是否归一、非法 `category` 是 400 还是空列表、空关键词是否等于全量，未写）

## 一致性（Consistency）

- [x] CHK010 引用的注入代码位置与实际不符（背景事实表、FR-004、US4-3 三处引用 `external_tools.py:947-977` 作为"凭证服务端注入"证据；实际该区间是 `_flatten_schema`/`_build_debug_trace`，凭证注入在 `external_tools.py:784-802`（HTTP 直连/测试）与 `1010-1031`（runtime/MCP，`runtime_headers` 最后应用）——引用需更正，否则 SC-002"同一注入路径"验收无处落地）
- [x] CHK011 与 034 的关系口径已与代码现状不符（决策 #7、FR-009、背景事实表均按"034 未落地 → 存储侧明文 → 落地后验收"表述；实际 034 已接线：`tools.py:_normalize_payload` 写侧调 `encrypt_credentials`（`KmsConfigError` → 503 fail-closed）、`merge_credential_preserve` 做凭证继承、`_serialize` 用 `redact_credentials` 掩码，读侧 `external_tools.py:784`/`1010` `decrypt_credentials` 宽容解密——"034 未落地保持明文"的分支已不存在，spec 未更新）
- [x] CHK012 「自动注册 018 资产（`type=connector`）」与 018 实际模型不一致（决策 #6、FR-006 统一用 `type=connector`；实际资产模型是 `CapabilityAsset.kind`（默认 `"rest"`，`registry.py:51`），`AUTO_DISCOVERABLE_KINDS = {"rest","mcp"}`（`registry.py:27`），`connector` 会被 `discover_assets` 判入 `needs_manual`（`registry.py:129-137`）；注册面只有 `POST /api/capabilities/discover`（需 `service_token`、批量 candidates、**无单资产注册路由**），`asset_id = dedupe_key(endpoint, method) = f"{METHOD}:{endpoint.lower()}"`——`type=connector` 无对应字段可写，字段映射未写）
- [x] CHK013 租户隔离的判定键未对齐既有 `scope` 维度（FR-012/决策 #3 只说"按租户隔离"；既有工具查询是 `organization_tool_query(tenant_id)` = `tenant_id` + `$or[{scope:"organization"},{scope 缺失},{scope:""}]`（`app/services/organization_tools.py:14-16`），`scope="user"` 的个人工具被排除——「已安装」视图若只按 `tenant_id` 过滤会把个人工具算进来，口径未写）

## 边界与歧义（Boundaries & Ambiguities）

- [x] CHK014 模板版本升级与已装实例的"配置固化"判据未定义（Edge Case「模板版本升级」"已安装实例继续用创建时固化的配置，不被动刷新（升级只影响新安装）"——但 `external_tools` 无 `template_version` 字段、POST 也会丢弃额外字段，**"创建时版本"无处可存**；市场页是否提示"有新版本"、是否需要升级动作，未写）
- [x] CHK015 不支持的 `authType` 的拒绝时机未定义（Edge Case「多认证形态」"oauth 等留后（模板声明即拒绝创建，提示不支持）"——是**加载期跳过该模板**（种子不合格，与 CHK004 同通道）还是**创建期 400**？若走加载期，含 oauth 的模板永不出现在市场；若走创建期，市场会列一个必然失败的模板，两种口径与 FR-002"返回全部模板元信息"冲突，未写）
- [x] CHK016 向导「测试连接」与门禁审批的交互未定义（`test_tool`/`test_draft_tool` 都先 `_enforce_gate`，被拒时按层映射 403/409/503（`tools.py:349-400`）；US2-2 只覆盖"不可达或参数错误返回可读错误"，未说审批待办（409）时向导应展示"提交审批"还是"测试失败"、是否可绕过直接上架，未写）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 `spec.md` 的 FR-001…FR-012 / 决策 #1–#7 / Edge Cases / Key Entities 原文，并逐条指出"缺什么"。
- 本特性需求风险集中在三处：**同构承诺**（CHK003/CHK007/CHK010/CHK012——"与手工创建同构"是硬约束，但既有 `ToolPayload` 与 018 资产模型都没有模板维度字段，同构与留痕直接冲突）；**计数与隔离**（CHK008/CHK013）；**依赖口径漂移**（CHK011——034 已接线，spec 仍按"未落地"描述）。
- spec 定稿于 2026-10-23，早于 034 接线落地与 018 模型核对，故 CHK011/CHK012 属"文档滞后于代码"而非需求缺失，已由回填口径更正而非改写 FR 语义。
- 041 代码全未开工（2026-10-24 核查：无 `app/connector_templates/`、无 `connector_market.py`、无 `connector_installs`、无 `views/connectors/`、无 `api/connectorMarket.ts`、无 `test_connector_market.py`），故本清单只审需求质量，实现项全部"未落地"。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

16 条全部达标，均经 `spec.md` 新增的「判定口径补充（2026-10-24，/speckit-checklist 回填）」R-1~R-16 消解：

- CHK001（schema 描述对象）→ R-1 + R-2 + R-3：`param_schema` **只描述业务入参**（节点 `{name,type,required,location,description,default}`），连接参数走模板 `connection` 段；映射规则见 R-3。
- CHK002（字段必填集/类型）→ R-2：`category` 枚举 `oa|erp|data|devops|im`，`example_params` 键集 ⊆ `param_schema.required`，`test_hint` 结构化 `{endpoint, expected_status}` 且**不参与创建链路**。
- CHK003（安装记录/模板留痕）→ R-8 + R-12：新集合 `connector_installs`（含 `template_version`），模板来源**只落安装记录**，工具记录零改动（同构硬约束优先）。
- CHK004（告警落点）→ R-4：三级分离——损坏/缺字段 `warning` 跳过；疑似真实凭证 `error` 拒绝加载；均只落进程日志，列表响应带 `skipped:[{id,reason}]`。
- CHK005（首批自检判据）→ R-5：18 个为计划值、≥10 为测试硬断言（且 5 类别各 ≥2），"可测试"用 mock API 验收，不依赖外网。
- CHK006（测试连接判定）→ R-7：通过 = `success is not False` ∧ `status=="passed"` ∧ HTTP 2xx（等价 `X-MOGO-Operation-Result=="success"`）；门禁拒绝不写 `last_test_status`，记为 `blocked`。
- CHK007（上架语义）→ R-6：**两步**——`POST /api/tools` 恒 disabled（不改既有语义）→ 安装成功后服务端 `PATCH {"status":"active"}`；MCP 经 `validate_mcp_activation` 校验；未测试通过**允许**上架但市场页标"未验证"。
- CHK008（计数语义）→ R-8：`count_documents({tenant_id, template_id})` 行数聚合，不设冗余计数器；删除连接器级联 `delete_many({tool_id})`；计 0 也返回。
- CHK009（搜索筛选口径）→ R-11：`category` 非法 400 `invalid_category`；`q` 空 = 全量；`casefold()` 子串命中 5 个字段；排序 `category asc, name asc`；未知 id 404。
- CHK010（注入引用行号）→ R-16：更正为 `784-802`（HTTP）与 `1010-1031`（runtime/MCP），`947-977` 实为 `_flatten_schema`/`_build_debug_trace`。
- CHK011（与 034 关系）→ R-9：**034 已接线**（写侧 `encrypt_credentials` + 503 fail-closed + `merge_credential_preserve` + `redact_credentials`，读侧 `decrypt_credentials` 宽容解密）；041 走既有 POST 即自动加密，"未落地保持明文"分支作废。
- CHK012（018 字段映射）→ R-6：018 无 `type` 字段，`connector` 语义落 `connector_installs.template_id` + 工具 `tags=["connector"]`；资产 `kind` 按 `http→rest`/`mcp→mcp` 注册；走 `POST /api/capabilities/discover`（无单资产注册路由），枚举扩展诉求挂 018 侧只做关系声明。
- CHK013（隔离判定键）→ R-10：复用 `organization_tool_query`（`scope ∈ {organization, 缺失, ""}`），排除 `scope="user"`；模板目录平台级不按租户过滤。
- CHK014（版本固化）→ R-12：`template_version` 存安装记录，创建后无任何按 `template_id` 回写 config 的路径；版本落后仅提示，首期不做升级动作。
- CHK015（authType 拒绝时机）→ R-13：**加载期跳过**（`unsupported_auth_type`，走 R-4 的 a 通道）+ 创建期 400 兜底，双重实现。
- CHK016（审批交互）→ R-14：403 提示无权限并禁用上架；409 提示"已提交审批"不算失败；503 提示重试；三种都不写 `last_test_status`。

**验收证据**：2026-10-24 代码级核查——`services/chat-api/app/services/external_tools.py`（784-802 / 1010-1031 凭证注入与 `decrypt_credentials`；947-977 确认为 `_flatten_schema`/`_build_debug_trace`）、`services/admin-api/app/api/routes/tools.py`（`ToolPayload` 207-215、`create_tool` 241-261、`_normalize_payload` 87-140、`/{tool_id}/test` 323-336、`/test-draft` 338-346、`_enforce_gate` 349-400、`_serialize` 67-86）、`services/admin-api/app/services/capability_assets/registry.py`（`ASSET_STATES` 21、`AUTO_DISCOVERABLE_KINDS` 27、`dedupe_key` 34-37、`kind` 51、`discover_assets` 119-155）、`services/admin-api/app/api/routes/capability_assets.py`（discover/list/detail/contract/state/owner/a2a-exposed）、`services/admin-api/app/services/organization_tools.py:14-16`、`services/admin-api/app/api/tool_limits.py:26-32`、`services/admin-api/app/security/tool_credentials.py`（`encrypt_credentials` 104 / `decrypt_credentials` 137 / `merge_credential_preserve` 189）、`apps/admin-web/src/views/tools/`（仅 `ToolsPage.vue`/`ToolEditPage.vue`，无 connectors 目录）、`apps/admin-web/src/api/`（无 `connectorMarket.ts`）、`apps/admin-web/src/router/routes.ts:96-110`。**本特性无测试**（`services/admin-api/tests/` 无 `test_connector_market.py`），测试项待 `tasks.md` 落地。
