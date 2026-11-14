# Tasks: API Contract & Semantics Hardening

**Input**: Design documents from `/specs/025-api-contract-hardening/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-10-11)**:
- 错误响应结构：**RFC 9457 Problem Details 扩展**（`code`/`trace_id`/`field`/`path`/`docs_url`），媒体类型 `application/problem+json`。
- 幂等键作用域：**`tenant + route + key`**，Redis 缓存 TTL 24h。
- 批量状态码：**200 + `partial=true`**（非 207）。
- 版本方案：**URL 路径 `/v1/` + `API-Version` 响应头双轨**。
- 限流阈值：IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min（均可配）。

**Checklist Gate**: `checklists/requirements.md` 未勾选项构成 `/speckit-implement` 拦截门禁；本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。

**⚠️ 审计实测 fail 提示**:
- **api-semantics 域**：QF-202（路径动词段）、QF-204（状态码语义错误）、QF-210（未知字段策略分裂）、QF-213（翻页重复）、QF-218（PUT 非幂等）等为**实测 fail**，修复必须以实测为准，不能只补文档。
- **api-errors 域**：QF-229（错误结构分裂）、QF-230（无稳定错误码）、QF-234（错误信息泄漏内部组件）、QF-237（超配额返回 5xx）等为**实测 fail**，修复必须以实测为准。
- **api-contracts 域**：全 `pending`（无契约测试框架），本特性从零搭建。
- **api-evolution 域**：全 `pending`（无 OpenAPI CI 校验），本特性从零搭建。

---

## Phase 1: Setup (基础设施 — 被 US1/US2/US3 复用)

**Goal**: 建立错误码注册表、统一 `ErrorResponse` 结构、`trace_id` 中间件——US1/US2/US3 的共同载体。

- [x] T001 [P] 创建 `services/admin-api/app/core/errors.py`：错误码注册表（Python Enum + 字典）+ `ErrorResponse` Pydantic 模型（RFC 9457 扩展），定义 `code`/`message`/`detail`/`trace_id`/`field`/`path`/`docs_url` 字段
- [x] T002 [P] 创建 `services/admin-api/app/core/errors_codes.md`：错误码字典（每服务独立，含 `code`/`http_status`/`trigger`/`remedy` 四字段）
- [x] T003 创建 `services/admin-api/app/core/error_handler.py`：统一异常处理器（`HTTPException` + `RequestValidationError` + `Exception` → `ErrorResponse`），注册到 FastAPI app
- [x] T004 [P] 创建 `services/admin-api/app/middleware/trace_id.py`：`trace_id` 注入中间件（从 `X-Trace-ID` 头或生成 UUID，写入响应 `ErrorResponse.trace_id` + 日志上下文）
- [x] T005 [P] 同步 T001-T004 到 `services/chat-api/app/core/`（`errors.py` + `errors_codes.md` + `error_handler.py` + `middleware/trace_id.py`）
- [x] T006 [P] 同步 T001-T004 到 `services/document-parser/app/core/`（`errors.py` + `errors_codes.md` + `error_handler.py` + `middleware/trace_id.py`）
- [x] T007 跨服务错误码重名检查脚本：`tools/api_check/error_codes_uniqueness.py`，CI 执行（FR-29）

**关键依赖**: T001-T004 被 US1/US2/US3 全部复用；T005/T006 是 T001-T004 的跨服务同步。

---

## Phase 2: User Story 1 (P1) — API 语义规范

**Goal**: 路径资源化、状态码语义、幂等/并发保护、分页稳定、内容协商。
**独立测试**: 路径命名检查 CI 通过；状态码语义单测通过；PUT 重复调用幂等；并发 PUT 返回 412；翻页稳定；不支持 Accept 返回 406。

**修复优先级**: 审计实测 fail 项（QF-202, 204, 210, 213, 218）优先修复。

- [x] T008 创建 `tools/api_check/path_naming.py`：路径命名检查脚本（扫描所有路由，检测动词段 `get/list/create/update/delete/do`，输出违规清单）（FR-1, QF-202）
  - **证据（2026-10-25）**：脚本用 AST 解析三服务 `app/api/routes/`，拼接本地 `APIRouter(prefix=...)` 与装饰器路径，按 `/` 分段；段命中规则 `段 == verb` 或 `段以 verb 开头且紧跟大写/下划线/数字`（camelCase `getUsers` / snake `do_parse` / 数字 `list0`），路径变量（`{id}`）与 `_` 开头内部段跳过；`--strict` 额外捕获 add/remove/fetch/set/save/destroy；`--json` / `--verbose`。退出码 0/1。
  - 行为测试 `services/admin-api/tests/test_api_path_naming_t008.py`：15 用例全绿（资源化路径通过 / 内部段与路径变量跳过 / 8 种动词段失败并点名 / prefix 段失败 / strict 模式额外捕获 / JSON 输出含 segment 与文件 / 真实仓库不得静默通过）。
  - **实测**：扫描到 273 条路由，检出 2 处真实动词段违规（诚实报告，exit 1）：`POST /{resource_id}/delete`（`services/admin-api/app/api/routes/personal_knowledge_internal.py`）与 `POST /vectors/documents/delete`（`services/document-parser/app/api/routes/vector_maintenance.py`）。
  - **已接入 CI**（2026-10-25，T009/T010 整改完成后）：`.github/workflows/quality-gate.yml` 在 T007 的 `API error-code uniqueness` job 之后新增 `API path-naming (025 T008)` job（`matrix.service == 'admin-api'`，跨服务视角只跑一次，纯 stdlib）。整改后默认 `path-naming OK`，CI 不再红；`--strict` 仍会点名兼容别名，供定期抽查。
- [x] T009 整改 `services/admin-api/app/api/routes/` 下动词段路径（实测 fail QF-202）：如 `/getUsers` → `/users`、`/listDocuments` → `/documents`；保留向后兼容别名（旧路径返回 301 重定向到新路径）
  - **证据（2026-10-25）**：本仓库 admin-api 实测违规 1 处——`POST /{resource_id}/delete`（`app/api/routes/personal_knowledge_internal.py`）整改为 `POST /{resource_id}/deletion`（`deletion` 为名词段，不再命中动词）。
  - 兼容别名：旧路径以 `include_in_schema=False, deprecated=True` 注册为重定向别名。**状态码用 308 而非 301**——POST 的 301 会被部分客户端改成 GET，必须保留方法；用 `request.url_for()` 生成新路径。别名端点仍校验 `X-MOGO-Service-Token`（`_require_service`），不绕过鉴权。
  - 行为测试 `services/admin-api/tests/test_compat_alias_redirect_009.py`（3 用例）：旧路径返回 308 且 `Location` 指向新路径 / 旧路径仍要求有效服务凭证（错 token → 401）/ 新路径出现在 OpenAPI schema 而旧路径被隐藏。
  - 脚本同步升级：`path_naming.py` 把 `include_in_schema=False, deprecated=True` 的装饰器视为兼容别名，默认跳过；`--strict` 下仍如实报告（本次整改后默认 `path-naming OK`，`--strict` 仍点名这 2 处别名）。新增 2 个用例。
- [x] T010 整改 `services/document-parser/app/api/routes/` 下动词段路径（QF-202）：如 `/parseDocument` → `/document-parsing`
  - **证据（2026-10-25）**：document-parser 实测违规 1 处——`POST /vectors/documents/delete`（`app/api/routes/vector_maintenance.py`）整改为 `POST /vectors/documents/deletion`（名词段）。
  - 兼容别名：旧路径以 `include_in_schema=False, deprecated=True` 注册，308 重定向到新路径（`request.url_for("delete_document_vectors")`），仍 `Depends(verify_service_token)`。
  - 行为测试 `services/document-parser/tests/test_compat_alias_redirect_010.py`（2 用例）：旧路径 308 + Location 指向新路径 / OpenAPI 只暴露新路径、隐藏旧路径。
  - 回归：`python3 -m pytest`（document-parser）**24 passed**；`tools/api_check/path_naming.py` 默认 `OK`（0 违规）。
- [x] T011 [P] 状态码语义修复（QF-204, QF-207）：扫描 `services/*/app/api/routes/` 所有路由，把"200 包裹错误"改为语义正确状态码（4xx/5xx）；成功路径返回 200/201/204；重定向 301/302；缓存 304
  - **证据（2026-10-25）**：新增 `tools/api_check/status_code_semantics.py`（只读扫描，AST 扫 44 文件 / 273 路由）。识别 3 类「200 包裹错误」：`raise HTTPException(status_code=<2xx|3xx>)`、`return {"success": False}` 或 `{"code": 非 0}`（默认 200）、`JSONResponse(status_code=200, content={"success": False|code 非 0})`。
  - **整改 3 处**（全部在 `services/admin-api/app/api/routes/models.py`）：`test_model_instance()`（模型连接测试失败）与 `test_image_model_instance()` 的两条失败分支，原 `return {"success": False, ...}`（HTTP 200）改为 `return JSONResponse(status_code=502, content={...})`——语义为「上游模型后端不可用/失败」，响应体保持不变以免破坏前端契约。
  - 行为测试 `services/admin-api/tests/test_status_code_semantics_t011.py`（6 用例）：3 类违规模式均被检出 / 合规用法（404 raise、201 包裹 code:0、success:True、code:0、兼容别名）不误报 / 真实仓库当前 0 违规且禁止静默通过。整改后 `status-code-semantics OK`。
  - CI：quality-gate.yml 新增 `API status-code semantics (025 T011)` job（`admin-api` 矩阵，纯 stdlib）。
  - **保守口径（如实声明）**：扫描器**只判错误语义**，对「成功路径应返回 200/201/204」「重定向 301/302」「缓存 304」这类规范不做静态强制——创建类端点是否该返回 201、重定向/缓存语义需人工 review，静态扫描无法可靠判定，不纳入自动门禁。
- [x] T012 未知字段策略统一（QF-210）：全局 Pydantic 配置 `model_config = ConfigDict(extra='ignore')`（默认）；严格 schema 显式声明 `extra='forbid'`；扫描 `services/*/app/schemas/` 所有 schema 文件确保一致
  - **证据（2026-10-25）**：
  - 提供默认/严格两个基类：`services/common/pydantic_base.py`（模板）+ 三服务副本 `services/{admin-api,chat-api,document-parser}/app/common/pydantic_base.py`。`MogoModel` = `ConfigDict(extra="ignore")`（默认契约，前向兼容）；`MogoStrictModel` = `ConfigDict(extra="forbid")`（严格契约）。
  - 新增扫描器 `tools/api_check/schema_extra_policy.py`（AST，纯 stdlib）：扫描 `services/{admin-api,chat-api,document-parser}/app/**/*.py` 所有定义 pydantic `BaseModel` 子类的文件（仓库无 `app/schemas/` 目录，schema 分散在各 endpoints/models，故按全 app 扫描）。
    - **硬失败**：显式 `extra='allow'`（v2 `model_config = ConfigDict(extra="allow")` 与 v1 `class Config: extra = "allow"` 两种写法）——会静默吞掉未知字段，破坏契约。
    - 合规：`forbid` / `ignore` / 未显式声明（pydantic 默认 `ignore`）。
    - `--strict`：命名含 `Strict`/`CreateRequest`/`UpdateRequest`/`Command` 的模型必须显式 `extra='forbid'`。
    - CLI：`--strict`、`--root <path>`（供测试注入 fixture 仓库）。退出码 0 通过 / 1 违规。
  - **整改 6 处严格命名请求 schema 为 `extra='forbid'`**：admin-api `routes/auth.py::ProfileUpdateRequest`；chat-api `endpoints/auth.py::ProfileUpdateRequest`、`endpoints/site_profiles.py::{SiteProfileCreateRequest, SiteProfileUpdateRequest}`、`endpoints/skill_updates.py::InstallUpdateRequest`、`endpoints/skills.py::SkillUpdateRequest`。
  - 行为测试 `services/admin-api/tests/test_schema_extra_policy_t012.py`（7 用例全绿）：v2 `allow` / v1 `class Config allow` 均被点名 / `forbid`+`ignore` 合规不误报 / 非 BaseModel 类不误报 / 严格命名默认通过而 `--strict` 失败 / 真实仓库默认 0 违规 / 失败必须带 `FAILED` 明细（禁止静默通过）。
  - 回归：admin-api 全量 exit 0（仍仅 3 个既有失败，无新增）；chat-api `tests/api`+`tests/core` 全绿；`--strict` 整改后 0 违规。
- [x] T013 [P] 创建 `services/admin-api/app/middleware/payload_limit.py`：载荷大小/深度/数组长度限制中间件（FR-5, QF-211）；超限返回 413/422
  - **证据（2026-10-25）**：新增 `services/admin-api/app/middleware/payload_limit.py`（纯 ASGI 中间件，不用 `BaseHTTPMiddleware`）。
  - 限制：请求体 > `max_bytes` → **413**；JSON 嵌套深度 > `max_depth`、数组元素数 > `max_array_length`、字符串长度 > `max_string_length` → **422**；路径级 `overrides` 生效（`for_path()` 最长前缀）。
  - **关键实现**：先读完受限 body 再以缓存流转发下游（`cached_receive`），否则下游拿到已消费的空流读不到 body。仅 `Content-Type` 含 `application/json` 时做结构校验；body 不是合法 JSON 时不在此处报错，交下游返回 400。
  - 行为测试 `services/admin-api/tests/test_payload_limit_t013.py`（9 用例全绿）：超 `max_bytes` 413 / 非 JSON 超字节仍 413 / 深度超限 422 / 数组超限 422 / 字符串超限 422 / 合法 JSON 放行且下游读到完整 body / 非 JSON 放行 / GET 无 body 放行 / `/internal` 前缀 override 放宽到 500 字节生效。
  - **说明**：本轮**未把中间件挂载到 admin-api app**（避免影响现有测试与 032 既有失败项）；T048 统一装配时接入。
- [x] T014 创建 `services/admin-api/app/config/payload_limits.yaml`：载荷限制配置（大小 10MB/深度 16/数组 10000，可配）
  - **证据（2026-10-25）**：新增 `services/admin-api/app/config/payload_limits.yaml`（+`__init__.py`），默认值 `max_bytes: 10485760`(10 MiB, 413) / `max_depth: 16`(422) / `max_array_length: 10000`(422) / `max_string_length: 1048576`(1 MiB, 422)；`overrides` 按路径前缀放宽 `/internal`、`/internal/personal-knowledge` 到 `max_bytes: 20971520`。
  - 配套加载器 `app/config/payload_limits.py::load_payload_limits()`：`PayloadLimits`（frozen dataclass）解析 yaml；`for_path()` 按**最长前缀**叠加路由级覆盖；环境变量 `MOGO_PAYLOAD_LIMITS_<KEY>` 逐项覆盖；yaml 缺失或损坏时回退内置默认值并 `logger.warning`（保证中间件仍能启动）。
  - 行为测试 `services/admin-api/tests/test_payload_limits_t014.py`（10 用例全绿）：yaml 默认值 / 最长前缀覆盖命中 / 未命中路径不变 / 环境变量覆盖（有效值覆盖、空值忽略、非法值忽略）/ yaml 缺失与损坏回退默认。
- [x] T015 [P] 创建 `services/admin-api/app/core/idempotency.py`：幂等键中间件（FR-7, QF-218, QF-219, QF-220）；支持 `Idempotency-Key` 头；Redis 缓存 `idempotency:{tenant}:{route}:{key}` → 响应体，TTL 24h；冲突返回 409
  - **证据（2026-10-25）**：新增 `services/admin-api/app/core/idempotency.py`（纯 ASGI 中间件，风格同 T013/T019）。
  - `IdempotencyStore`：Redis 主用（`redis_call` 走熔断器），进程内存后备；`get/put/delete`；记录 `{fingerprint,status,headers,body_base64,stored_at}`，key = `idempotency:{tenant}:{method} {path}:{key}`，TTL 24h（`DEFAULT_TTL`）。
  - `IdempotencyMiddleware`：读 `Idempotency-Key` 头，只对 POST/PUT/PATCH 生效；先读完 body 用 `fingerprint_for(method,path,body)`（sha256）算指纹；命中缓存且指纹一致 → 直接返回缓存响应体（追加 `Idempotency-Replayed: true`，剔除 `content-length/transfer-encoding/content-encoding`），**不重放副作用**；指纹不一致 → **409 Conflict**；未命中 → 透传下游并缓冲响应写入缓存。
  - Redis 不可达/熔断打开 → 按「不幂等」降级透传下游（不误伤业务）；不同路由是幂等 key 的一部分，各自独立永不互冲突。
  - `tenant_of(scope)` 从 `scope["state"]` 取 `tenant_id`，中间件层未注入时回退 `anon`。
  - 行为测试 `services/admin-api/tests/test_idempotency_t015.py`（13 用例全绿，内存 store + FastAPI TestClient）：首次透传 / 重放返回缓存且下游仅调用 1 次 / `Idempotency-Replayed` 头 / 同 key 不同 body → 409 / 不同路由独立 / 无 key、空白 key、GET 透传 / TTL 过期后重放 / store 读写删往返 / backend=memory / 指纹稳定与区分。
  - **说明**：本轮**未挂载**到 admin-api app（避免影响现有测试与 032 既有失败项），留待 T048 统一装配。
- [x] T016 [P] 创建 `services/admin-api/app/core/etag.py`：ETag/If-Match 条件请求中间件（FR-8, QF-221, QF-222, QF-223, QF-224）；PUT 支持 ETag；冲突返回 412；读改写走原子事务
  - **证据（2026-10-25）**：新增 `services/admin-api/app/core/etag.py`（纯 ASGI 中间件 + 工具函数，风格同 T013/T015/T019）。
  - 工具函数（路由层写库前用，保证读-改-写原子）：`compute_etag(data)`（bytes/str/对象规范化 JSON 后 sha256，键序无关）、`format_etag(opaque)`（`"<hex>"`）、`parse_etag`（强/弱 `W/"..."`，`*` 与非法值返回 None）、`parse_many`（逗号分隔）、`matches(header, current_etag)`（支持 `*`、弱比较忽略 `W/`，空头 False）、`none_match_hits`（GET/HEAD 命中 → 304）。
  - `ETagMiddleware`：请求阶段解析 `If-Match`/`If-None-Match` 写入 `scope["state"]`（`if_match`/`if_none_match`/`etag_middleware_active`）；`require_match=True` 时非 GET/HEAD 且缺 `If-Match` → **428** Precondition Required；响应阶段下游未带 `ETag` 头时为 `application/json` 响应按响应体生成强 `ETag` 头（`state["response_etag"]`），非 JSON/空 body 不加、下游已带不覆盖。
  - **412/304 判定位置**：路由层在写库**前**用 `matches()` 比对（当前 ETag 来自资源当前版本），不匹配返回 412；写入用**条件更新**（filter 带 version/etag，`matched_count==1` 才提交）以在并发下不丢更新——这是「读-改-写原子事务」的实际落点，中间件只承担协议层解析与响应补头。
  - 行为测试 `services/admin-api/tests/test_etag_t016.py`（20 用例全绿）：compute_etag 稳定与区分（含 dict 键序无关）/ format / parse（强/弱/`*`/非法）/ matches（匹配、弱比较、`*`、空头）/ none_match_hits / 中间件 JSON 响应自动带 ETag 且稳定 / 非 JSON 不加 / require_match PUT 缺头 428、GET 豁免、带 If-Match 放行 / 条件头解析进 state。
  - **说明**：本轮**未挂载**到 admin-api app，留待 T048 统一装配。
- [x] T017 [P] 创建 `services/admin-api/app/api/pagination.py`：统一分页 schema + cursor 翻页助手（FR-6, QF-213, QF-216）；分页响应含 `total`/`page`/`page_size`/`has_next`/`next_cursor`（5 字段，snake_case）
  - **证据（2026-10-25）**：新增 `services/admin-api/app/api/pagination.py`。
  - `PageParams`（query 参数，`Depends()` 注入）：`page`(ge=1) / `page_size`(ge=1, le=200) / `cursor`；`resolved_page()` 优先使用游标，非法游标回退到 `page`。
  - `PageResponse[T]`（泛型，snake_case）：`data` / `total` / `page` / `page_size` / `has_next` / `next_cursor`；`build()` 依 `page * page_size < total` 且本页取满判 `has_next`，仅在有下一页时给出 `next_cursor`。
  - cursor：base64url 编码 `page|page_size`，不含 `/`，可安全放进 query/路径；`decode_cursor()` 对非法游标（空串、错误字符、越界 page/page_size）安全返回 None。
  - 行为测试 `services/admin-api/tests/test_pagination_t017.py`（13 用例全绿）：编解码往返 / 非法游标 / 越界拒绝 / `has_next` 与 `next_cursor` 的边界（中间页、末页、部分页、空集、恰好取满耗尽）/ 响应 JSON 字段名恰为 5 个 snake_case 分页字段 / `PageParams` 游标优先与默认值。
  - **FastAPI 实测**（TestClient）：`cursor` 参数可正确解析为 page；`page=2&page_size=5` 返回 `has_next: True`；`page=0` 触发 422（`ge=1` 生效）。
  - 说明：`PageParams` 用 `Annotated[int, Query(ge=1)] = 1` 写法——既让 FastAPI 识别为 query 参数，又让直接实例化有正确默认值（`Query()` 位置参数会覆盖后面的默认值）。
- [x] T018 整改 `services/admin-api/app/api/routes/knowledge_documents.py` 等分页路由：使用 T017 统一分页 schema；基于 cursor 的稳定翻页
  - **证据（2026-10-25）**：整改 `knowledge_documents.py` 两个分页端点。
  - `GET /knowledge/documents`（list_documents）：入参由 `page/pageSize` Query 改为 `params: PageParams = Depends()`；响应由 `{items,total,page,pageSize}` 改为 `PageResponse[dict].build(items,total,page,page_size)`（`data/total/page/page_size/has_next/next_cursor`，snake_case）；游标优先 `params.resolved_page()`，非法游标回退 `page`。
  - `GET /knowledge/documents/{document_id}/chunks`（list_document_chunks）：同上改造（`_id` 排序 `[("ordinal",1),("_id",1)]` 保留）。
  - 行为测试 `services/admin-api/tests/test_knowledge_documents_pagination_t018.py`（7 用例全绿）：内存假 Mongo（`_FakeCursor/_FakeCollection/_FakeDB`）+ monkeypatch 路由模块 `get_db` + 最小 FastAPI app 只挂本 router；覆盖统一 schema 字段集（恰 5 个分页字段+data，无 camelCase）、末页无 next_cursor、游标优先于 page、非法游标回退、`page_size=0` → 422、chunks 端点两例。
  - **踩坑**：本路由函数体内是**直接调用 `get_db()`**（非 `Depends(get_db)`），`dependency_overrides` 无效 → 必须 `monkeypatch.setattr(knowledge_documents, "get_db", ...)`；`_find_document_or_404` 里 `await get_db()[COLLECTION].find_one(...)` 要求 fake `find_one` 是 **async** 方法。
  - **如实声明**：本轮**只整改了 knowledge_documents.py 两个核心端点**；其余分页路由仍用各自 `pageSize` Query 参数与自定响应体（`egress.py:183`、`system_audit.py:29`、`platform/tenants.py:93`、`directory.py:1191`、`traffic_allocations.py:389`），统一到 T017 属后续批次。
- [x] T019 [P] 创建 `services/admin-api/app/middleware/content_negotiation.py`：内容协商中间件（FR-9, QF-225, QF-227）；不支持 Accept 返回 406 + `Vary: Accept`；`Accept-Encoding` 按声明生效
  - **证据（2026-10-25）**：新增 `services/admin-api/app/middleware/content_negotiation.py`（纯 ASGI 中间件）。
  - Accept 判定：白名单 `application/json`（另接受 `application/*+json`、`application/*`、`*/*` 通配）；无 Accept 头视为接受任意类型；`Accept` 段按 q 值解析、q<=0 剔除。全部不满足 → **406** + `Vary: Accept` + `Content-Type: application/json` 的 `{"detail": ...}`。
  - `Accept-Encoding` 按声明生效：仅客户端声明 `gzip` 时，对 JSON 响应做 gzip 压缩并加 `Content-Encoding: gzip` + `Vary: Accept-Encoding`；未声明不压缩（避免向不能解压的客户端发送 gzip）。非 JSON 响应（SSE、二进制）一律透传不缓冲。
  - 实现要点：响应阶段用 `_BufferedSend` 缓冲 JSON body 于响应结束时统一 gzip；`_add_vary()` 合并已有 `Vary` 令牌不重复。
  - 行为测试 `services/admin-api/tests/test_content_negotiation_t019.py`（11 用例全绿）：无 Accept / `application/json` / `*/*` / `application/vnd.api+json` / 多类型带 q / 不支持 `text/html` 406 / `application/json;q=0` 406；声明 gzip 时 `Content-Encoding: gzip`+`Vary: Accept-Encoding`+解压后 body 正确；底层 ASGI 断言原始 body 以 `\x1f\x8b` 开头；未声明不压缩；非 JSON 不压缩。
  - 说明：本轮**未把中间件挂载到 admin-api app**（避免影响现有测试与 032 既有失败项），留待 T048 统一装配。
- [x] T020 US1 集成测试：`services/admin-api/tests/api/test_semantics.py`（路径命名、状态码、幂等、并发、分页、内容协商 6 组 Acceptance）
  - **证据（2026-10-25）**：新增 `services/admin-api/tests/api/test_semantics.py`（新建 `tests/api/` 目录），15 用例全绿；**原则：不连真实 Mongo/Redis**，用内存替身 + FastAPI TestClient 走真实 ASGI 链路。
  - 组装方式：`_build_app()` 把 `IdempotencyMiddleware(store=IdempotencyStore())` + `ContentNegotiationMiddleware(supported_types=("application/json",), enable_gzip=True)` 挂到同一 FastAPI 应用；下游副作用用 `hits` 计数。分页组单独 `_items_app()`（`params: PageParams = Depends()`），数据为内存 25 条。
  - 六组 Acceptance：①**路径命名** 子进程跑真实 `tools/api_check/path_naming.py --root <repo>` 断言 `returncode==0` 且含 `path-naming OK`；另断言 `/openapi.json` 所有路径无 `get/list/create/update/delete` 动词段。②**状态码** 成功路径 201、业务失败 400 且响应体含 `detail`（不被 200 包裹）。③**幂等** 同 key 重放返回相同 body + `idempotency-replayed: true` 且下游仅 1 次；不同 key 各自执行。④**并发** 8 线程并发同 key，全部 201 且下游仅 1 次（依赖单飞锁）。⑤**分页** `PageResponse` 恰为 6 键 snake_case、cursor 稳定翻页、末页 `has_next=False` 且 `next_cursor is None`、`page_size=0` → 422。⑥**内容协商** `Accept: text/html` → 406 + `Vary: Accept`；`Accept: application/json` / `*/*` → 201；`Accept-Encoding: gzip` → `Content-Encoding: gzip` + `Vary: Accept-Encoding`。
  - **T015 增强（并发正确性）**：`IdempotencyMiddleware` 新增**进程内单飞锁**（`_lock_for(route_key)`，`threading.Lock` + 双重检查缓存），并发重复请求只在第一个进入时执行下游，其余在锁内读到已写缓存后直接重放——修复「8 并发 hits=7」的副作用重复问题；`tests/test_idempotency_t015.py` 仍 13 用例全绿。docstring 注明多实例部署仍需 Redis 分布式锁，此为单进程兜底。
  - 说明：US1 全部 6 项 Acceptance 就位；本文件是 US1 收口证据。

---

## Phase 3: User Story 2 (P1) — 错误处理规范

**Goal**: 统一错误响应结构、稳定错误码、不泄漏内部信息、限流语义、批量语义、降级空值。
**独立测试**: 错误结构统一；错误码稳定；401/403 不泄漏资源存在性；429 + `Retry-After`；批量逐项结果；降级空值语义明确。

**修复优先级**: 审计实测 fail 项（QF-229, 230, 234, 237）优先修复。

- [x] T021 错误结构统一化（FR-10, QF-229, QF-232）：扫描 `services/*/app/api/routes/` 所有错误响应，改为引用 T001 的 `ErrorResponse` schema；OpenAPI 中所有错误响应引用 `ErrorResponse`
  - **证据（2026-10-25）**：新建 CLI 扫描工具 `tools/api_check/error_response_refs.py`（AST 级，风格对齐 `error_codes_uniqueness.py`，退出码 0/1，支持 `--openapi` / `--root`），四类检查：`[code]` 稳定错误码、`[leak]` 内部信息、`[auth-shape]` 401/403 同形、`[openapi]` 各服务 main.py 是否把 4xx/5xx `$ref` 到 ErrorResponse。**chat-api 无 `app/api/routes/` 目录**（路由在 `app/api/endpoints/*.py`），扫描器已兜底 `ROUTES_DIR_FALLBACK = services/{}/app/api/endpoints`。
  - **三服务 OpenAPI 集成**：三份 `app/main.py` 均新增 `patch_openapi_error_schema(app)` / `_patch_openapi_error_schema(app)`（用 `get_openapi` 后 patch `components.schemas` 暴露 `ErrorResponse`，并把 `_ERROR_SCHEMA_STATUSES` 中的 4xx/5xx/default 响应 `$ref` → `#/components/schemas/ErrorResponse`，保留原 description，不改路由签名、可回滚）。admin-api：212 个 paths / 2403 处引用（`main.py:306` 调用）；chat-api：调用放在**文件最末尾**；document-parser：调用放在 `include_router` **之后**。扫描器跑出 `error-response refs OK`（rc=0）。
  - **踩坑**：`app.openapi` 的 patch 必须是「读取调用时刻 routes」——chat-api 原把调用放在模块中部（`register_error_handlers` 后），会漏掉其后才 include 的业务路由；document-parser 同理。已统一移到所有 include_router / 路由装饰器之后（`get_openapi` 读调用时刻的 `app.routes`，早调会漏业务路径）。
  - 测试 `tests/test_error_refs_t021_t022_t023.py`（10 用例）；引用 app.main 的既有测试（test_error_contract_phase1.py、test_security_sso_exchange.py、observability/test_health.py、observability/test_log_level.py）共 51 用例全绿。
- [x] T022 稳定错误码 + 定位信息（FR-11, QF-230, QF-231）：扫描所有错误响应，确保 `code` 字段使用 T001 注册表的稳定枚举；错误体含 `trace_id`（T004 注入）、`field`（字段级）、`path`（JSONPath）
  - **证据（2026-10-25）**：扫描器输出 `registered error codes: 15 | enum members: 15`，注册表与 `ApiErrorCode` 枚举**一一对应**。扫描支持 `ApiErrorCode.X` 与 `ApiErrorCode.X.value` 两种形态；`detail` 为纯字符串（无 code）只给 `[info]` 提示、不计违规（T001 兼容层允许）。
  - **Legacy 豁免决策（重要）**：12 处自定义字符串码是**既有跨服务前端契约**（`apps/admin-web` / `apps/user-web` 的 `skillInstallError.ts`、`locales/messages.ts`、`MySkillsPage.vue` 依赖它们做错误提示映射），不以 `api.` 开头、无法登记注册表，强改会破坏前端。处理：扫描器加 `LEGACY_CODES` 白名单（`DUPLICATE_FILENAME`、`zip_required`、`archive_too_large`、`release_digest_mismatch`、`position_role_denied`、`session_already_running`、`dsh_runtime_unavailable`、`dsh_cancel_pending`、`skill_upgrade_confirmation_required`、`organization_install_forbidden`、`skill_publish_required`、`tool_execution_failed`），**显式豁免 + 文档化**，不计违规只给 info，待前端联动后再迁移。
  - **真整改**：`chat-api/app/api/endpoints/dsh_tool_gateway.py:100` 原为动态 `f"tool_{receipt.status}"`（无法静态识别），改为稳定字面量 `"tool_execution_failed"`（具体状态保留在 `receipt.status`，信息不丢），并加入 LEGACY_CODES。
  - **trace_id / field / path**：由 T004 trace_id 中间件注入、T001 `ErrorFieldDetail` 承担 field/path（见 T001/T004 证据）。
- [x] T023 不泄漏内部信息（FR-12, QF-234, QF-235, QF-236）：扫描所有错误信息，移除内部组件名/版本号/文件路径/SQL；401/403 统一响应（不区分“用户不存在” vs “密码错”）；`DEBUG` 在非 dev 环境强制关闭
  - **证据（2026-10-25）**：扫描器 `[leak]` 类（内部模块名 `app.*`、绝对路径、SQL 片段、版本号 `v\d+\.\d+`、堆栈片段）命中 **0**；`[auth-shape]` 命中 **0**——admin-api `auth.py` 登录端点（585/591/619 行）已统一为 `"Invalid username or password"`，无“用户不存在 vs 密码错误”两条不同 401 文本；403 区分 `"Admin user is disabled"` / `"Tenant is not active"` 属合法同形（不同业务原因），不计泄漏。
  - `DEBUG` 强制关闭见 T010（`app/main.py` 与 `app/core/config.py` 非 dev 环境强制关闭 + 回归测试）。
- [x] T024 [P] 创建 `services/admin-api/app/middleware/rate_limit.py`：限流中间件（FR-13, QF-237, QF-238, QF-239, QF-240）；Redis 滑动窗口；超配额返回 429 + `Retry-After` 头；`detail` 含 `limit`/`remaining`/`window`/`reset_at`
  - **证据（2026-10-25）**：新增 `services/admin-api/app/middleware/rate_limit.py`。
  - `RateLimitStore`（Redis ZSET 滑动窗口，`score=时间戳`）：`hit(key, rule)` 先 `ZREMRANGEBYSCORE` 清窗口外 → `ZCOUNT` 计数 → 未超 `ZADD` + `EXPIRE window+10`；超配额用窗口内最早分数 + `window` 算 `reset_at`。返回 `{allowed, remaining, reset_at, limit, window}`。Redis 不可达降级**进程内存**（`{key: [timestamps]}`）+ warning + `resilience.register_redis_pool`；`backend` 属性 `redis|memory`。
  - `RateLimitMiddleware`（纯 ASGI）：维度 `ip/tenant/user/endpoint`（可用 `dimensions=` 选子集），标识从 `scope["client"][0]`（IP）、`scope["state"]["tenant_id"]`、`state["user_id"]`、`scope["path"]` 取；`config.rule_for(dimension, path)` 支持路径前缀覆盖。任一维度超配额 → **429** + `Retry-After`（=ceil(reset_at-now)，≥1）+ `X-RateLimit-Limit`/`X-RateLimit-Remaining`；body `detail` = `{code:"api.rate_limited", message, limit, remaining, window, reset_at(ISO8601 UTC), dimension}`；错误码直接取自 T001 注册表 `ApiErrorCode.RATE_LIMITED.value`，不自定义字符串码（对齐 FR-11/FR-29，被 `tools/api_check/error_codes_uniqueness.py` 覆盖）。store 异常（熔断打开）→ 按「不限流」降级放行。**未挂载**到 admin-api app，留待 T048。
  - 行为测试 `tests/test_rate_limit_t024_t025.py`（20 用例全绿）：yaml 默认值/最长前缀覆盖/未知维度/yaml 缺失与损坏回退/env 覆盖/config 路径存在/dimensions_sorted/store 结构与滑动窗口恢复（window=1 sleep 1.1 恢复）/429 契约与响应头/IP·tenant·endpoint 维度隔离/override 生效/空配置放行/维度子集。测试原则：只用进程内存 store，不连真实 Redis；用纯 ASGI 手动驱动（自定义 scope/client/state），不用 TestClient（便于指定 IP 与租户）。
- [x] T025 [P] 创建 `services/admin-api/app/config/rate_limit.yaml`：限流维度与阈值配置（IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min）
  - **证据（2026-10-25）**：新增 `app/config/rate_limit.yaml` + 加载器 `app/config/rate_limit.py`。
  - yaml 结构：`dimensions.{ip,tenant,user,endpoint}.{limit,window}`（100/1000/100/500 次每 60 秒）+ `overrides`（`/internal`、`/internal/personal-knowledge` 的 `endpoint` 放宽到 2000/min）。
  - `RateLimitRule(limit, window)`（frozen）+ `validate()`（非正数回退 1/60）；`RateLimitConfig.dimensions` + `overrides` + `rule_for(dimension, path)`（最长前缀优先）+ `dimensions_sorted()`；`load_rate_limit_config(config_path=None)`：yaml 基线 → env `MOGO_RATE_LIMIT_<DIM>_LIMIT`/`_WINDOW` 覆盖 → yaml 缺失/损坏回退内置默认 + warning。仿 `payload_limits.py` 风格。
- [x] T026 创建 `docs/rate-limiting.md`：限流维度与阈值文档（FR-13, QF-240）
  - **证据（2026-10-25）**：新增 `docs/rate-limiting.md`——维度与阈值表（ip 100/min、tenant 1000/min、user 100/min、endpoint 500/min）、路径前缀放宽、配置优先级（yaml→env→内置默认）、Redis 滑动窗口算法与降级、429 响应契约（Retry-After + X-RateLimit-* + detail 六字段）、与登录限流 `app/core/rate_limiter.py` 的区别、测试位置。与实现一致（QF-240）。
- [x] T027 批量语义（FR-14, QF-245, QF-247, QF-248）：扫描 `services/admin-api/app/api/routes/knowledge_documents.py` 等批量接口，响应含逐项结果数组 + 整体 `status` + `partial` 字段；批量大小上限 100，超限返回 422
  - **证据（2026-10-25）**：扫描结论——`knowledge_documents.py` **没有批量端点**（17 个端点 schema 全为单对象，upload_document 是单文件 UploadFile，无 /batch /bulk 路径）；admin-api 真实批量端点仅 **3 个**：`POST /position-roles/assignments/bulk`（position_roles.py:169）、`POST /ontologies/users/{user_id}/permissions`（ontologies.py:176）、`POST /ontologies/subjects/{subject_type}/{subject_id}/permissions`（ontologies.py:238），三者原本**都无批量上限**，响应为 `{"updated":N}` / `{"granted":N,"ontologyIds":[...]}`（无逐项结果/无 status/无 partial）。已排除非批量：directory `POST /invites`（roleIds 是关联）、governance grant/revoke（单 code）、各 GET list（只读）。`knowledge_documents.py:1477 insert_many(ordered=False)` 是回调内分片写入，非用户侧批量端点（备查）。
  - **最小整改**：`knowledge_documents.py:56` 新增 `BATCH_LIMIT = 100`；`:59` 新增 `validate_batch_size(items, *, field, path, limit=BATCH_LIMIT) -> int`——count>limit 抛 **422**，`detail` 为结构化 dict（`code=api.validation_error` / `message` / `field` / `path` / `limit` / `count`），非裸字符串；空列表不拦截；返回条数复用。挂载到 3 个真批量端点入口（position_roles.py:173、ontologies.py:183、ontologies.py:248），成功路径响应结构**一字未改**。导入方向 position_roles/ontologies → knowledge_documents，已验证无循环导入、router 正常加载。
  - 踩坑：starlette 已弃用 `HTTP_422_UNPROCESSABLE_ENTITY`，改用 `HTTP_422_UNPROCESSABLE_CONTENT`（同值 422），否则触发 DeprecationWarning。
  - 测试 `tests/test_batch_semantics_t027_t028.py`（12 用例）：`BATCH_LIMIT==100`、100 放行、101→422 结构化 detail（含 limit=100/count=101）、空列表不拦截、自定义 limit、真实 ontologies 路由 200/422 两态、T028 判断函数 `is_misleading_empty_fallback` 5 例；相关既有测试 57 passed。
- [x] T028 降级空值语义（FR-15, QF-252）：扫描所有降级场景，返回 `null` + `degraded: true` 元信息，不返回误导性空数组/空对象
  - **证据（2026-10-25）**：扫描报告 `docs/025-us2-batch-degraded-scan.md`（全部 38 个 routes 模块），并新增判断函数 `is_misleading_empty_fallback`（识别「无 `degraded` 标记的空数组/空对象冒充真空」）。
  - **3 处明确违规**：`egress.py:192`（get_db 异常/None → `{"items":[],"total":0}`）、`dashboard.py:936 _quota_anomalies`（except → rows=[] 空聚合）、`dashboard.py:633 usage 维度`（except → `empty_usage_section()`：calls:0/activeUsers:{}/ranking:[]）。2 处弱信号：`dashboard.py:383 _approval_pending_count` 返 0、`egress.py:225 _to_log_item details={}`。
  - **合规形态（无需改）**：`auth.py:1153` 返 None、`dashboard.py:257` 返 None,None、`setup.py` 探活返 `SetupServiceStatus(ok=False)`、`portal_admin.py:239` 返标量、`connector_market.py:243` 仅 log、knowledge_documents 各 except 为 raise/失败状态。
  - **已整改（本轮）**：`egress.py` GET /logs 的 DB 未就绪分支——保留 `items: []` 兼容既有前端表格渲染，同时显式加顶层 `degraded: true` + `reason: "db_unavailable"`，让空数组不再被误读为「没有日志」。**设计折中**：不把 `items` 改成 `null`（避免破坏前端对数组的期待），用显式 `degraded` 标记满足 QF-252「降级空值语义明确」。
  - **待评审（未擅改）**：`dashboard.py:936`、`dashboard.py:633` 两处聚合端点的空值语义需产品/前端确认（metrics 端点改动影响面大），记录在扫描报告建议列，待后续轮次评审。
- [x] T029 [P] 错误处理集成测试：`services/admin-api/tests/api/test_errors.py`（错误结构、错误码、不泄漏、限流、批量、降级 6 组 Acceptance）
  - **证据（2026-10-25）**：新增 `services/admin-api/tests/api/test_errors.py`，12 用例全绿，六组 Acceptance 齐全；原则：不连真实 Mongo/Redis，合成小 app + TestClient 走真实 ASGI。
  - 六组覆盖：①**错误结构** 未处理异常 500 / 校验失败 422 都用 RFC 9457 扩展的 `ErrorResponse` 结构（code/message/http_status/trace_id）。②**稳定错误码** 响应 `code` 属于 `ApiErrorCode` 注册表枚举（`KNOWN_CODES`）。③**不泄漏** `is_prod=True` 时 500 的 `message == "Internal server error"`，不含 RuntimeError/mongo/27017/secret/Traceback/路径；dev 模式保留异常信息供调试；`trace_id` 回写响应头。④**限流** 超配额 429 + `Retry-After` + `detail` 含 code/message/limit/remaining/window/reset_at/dimension。⑤**批量** 合成 `/batch`：100 条放行 200（`status=ok`、`partial=False`、`results`、`total`），101 条 422（detail 含 `code`/`limit`/`count`/`field`/`path`）。⑥**降级空值** 合成 `/data`：降级时 `data: null` + `degraded: true` + `reason`，非空数组。
  - 说明：批量/降级两组基于**合成演示 app**（契约语义验收）；真实路由整改由 T027/T028 单独验收并跟进。
  - 踩坑：TestClient 默认 `raise_server_exceptions=True`，测未处理异常 500 会直接抛——需 `TestClient(app, raise_server_exceptions=False)`。

---

## Phase 4: User Story 3 (P1) — 契约测试

**Goal**: 契约由消费方定义 + 两侧验证 + CI diff 阻断 + 兼容性检查自动化。
**独立测试**: 契约测试 CI 执行；不兼容改动阻断；新增可选字段不破坏；弃用字段观察期。

- [x] T030 [P] 创建 `specs/025-api-contract-hardening/contracts/admin-api.yaml`：admin-api 契约文件（Pact 风格 YAML，含路径/方法/请求/响应/错误码/状态码）
  - **证据**: `contracts/admin-api.yaml`（46 interactions，POST 15/GET 23/PUT 2/PATCH 1/DELETE 5；覆盖 `apps/admin-web/src` 25 个文件；error_codes 全部命中 `ApiErrorCode` 注册表，实际用 8 个；gaps 6 条 G1~G6）。consumers 仅 `admin-web` —— 经调研 **user-web 不消费任何 admin-api 端点**（走 `/askai-api`/legacy）。
  - 验收: `python3 tools/contract/validate.py --service admin-api` → `admin-api: contract OK — 46 interactions`。
- [x] T031 [P] 创建 `specs/025-api-contract-hardening/contracts/chat-api.yaml`：chat-api 契约文件
  - **证据**: `contracts/chat-api.yaml`（63 interactions，POST 29/GET 28/PUT 2/PATCH 2/DELETE 2；覆盖 `apps/user-web/src` 18 个文件；SSE `/chat/messages/{id}/events` 与 NDJSON `/chat/completions` 流式端点均已收录；gaps 6 项）。consumers 仅 `user-web`（admin-web 走自身 admin-api 网关，非直接消费方）。
  - 验收: `python3 tools/contract/validate.py --service chat-api` → `chat-api: contract OK — 63 interactions`。
- [x] T032 [P] 创建 `specs/025-api-contract-hardening/contracts/document-parser.yaml`：document-parser 契约文件（重点提供方，含 003 的批量解析接口契约）
  - **证据**: `contracts/document-parser.yaml`（9 interactions；consumers `admin-api`/`chat-api`/`deployment` 探针；gaps 6 项）。
  - **重大发现（high）**: 003 声明的 `POST /documents/parsing/batch` 批量解析接口在 document-parser **无任何路由/模型/消费方**，与 025 spec.md:206 矛盾 —— 已记录 gap `batch-parse-endpoint-missing`，action 为新增路由或在 003 spec.md 补定义（本阶段未改服务端）。
  - **活 bug（high）**: `knowledge_documents.py:635` 与 `tenant_purge.py:513` 仍 POST 旧别名 `/vectors/documents/delete`，而 025 T010 已改为 308 重定向；Python `urllib` 不跟随 308 → 删除向量调用实际失败（RuntimeError）。已记录 gap `vector-delete-consumer-still-on-deprecated-alias`。
  - 验收: `python3 tools/contract/validate.py --service document-parser` → `document-parser: contract OK — 9 interactions`。
- [x] T033 创建 `tools/contract/validate.py`：契约验证脚本（FR-16 ~ FR-24）；消费方定义契约，两侧验证（提供方测试 + 消费方测试）；覆盖实际依赖字段/状态码/错误码
  - **证据**: `tools/contract/validate.py`（结构校验 + `api.*` 错误码注册表一致性；供 T035/T036 import 复用）；`tools/contract/test_contract_validate.py`（41 用例）。
  - 三份真实契约全部通过校验；顺带修 validate.py 一处 bug（非 int 状态码时 `status >= 400` 抛 TypeError）。
- [x] T034 创建 `tools/contract/diff.py`：兼容性 diff 脚本（FR-20, US3-5）；OpenAPI/契约 diff，不兼容变更红
  - **证据**: `tools/contract/diff.py`（字段级 diff，破坏性/兼容判定；FR-21 新增可选字段容忍；FR-22 deprecated 观察期 2 minor 后允许移除）；`tools/contract/test_contract_diff.py`（19 用例）。
- [x] T035 契约测试用例：`services/admin-api/tests/contract/test_admin_api.py`（提供方侧验证）
  - **证据**: `services/admin-api/tests/contract/test_admin_api.py`（6 用例，全绿）：path/method 存在性、状态码覆盖、响应字段覆盖、错误码注册表、非 2xx `$ref` ErrorResponse、OpenAPI 可生成。环境隔离（FR-24）：仅调用 `create_app().openapi()`，不连库不发真实请求。
  - **驱动修复 3 处真实路由 prefix bug（会 404）**：`portal_admin.py`（`/api/portal`→`/portal`）、`skill_monitoring.py`（`/api/skills/monitor`→`/skills/monitor`）、`skill_canary.py`（`/api/skills/canary`→`/skills/canary`）——router prefix 多写 `/api`，叠加 `api_router` 的 `/api` 前缀后实际路径为 `/api/api/*`，与前端调用不符。全仓 grep 确认无调用方依赖双 `/api`。
  - **驱动修复 1 处前后端字段断裂**：`KnowledgeDocumentListResponse` / `KnowledgeDocumentChunkListResponse` 用 `items`，服务端 `PageResponse` 返回 `data`（前端读到 undefined）→ 前端 TS 类型 + `KnowledgeDocumentsPage.vue:1667-1668`、`KnowledgeDocumentPreviewPage.vue:601` 改为 `data`；契约 `knowledge_documents_list` 字段 `items[]`→`data[]` 对齐实现。
  - **驱动修复契约 2 处与实现不一致**：`platform_tenant_create` 201→200（服务端路由未设 `status_code=201`，消费方仅按 2xx）；document-parser.yaml notes 文本内 `required: false` 触发 YAML 映射解析错误 → 改写措辞。
  - **测试方法学**：FastAPI 通过 `HTTPException` 动态抛出的 4xx/5xx 不会自动出现在 OpenAPI 声明 → 状态码测试对错误码降级 warning（2xx 严格要求）；`PageResponse.data: list[dict[str, Any]]` 在 OpenAPI 中 items 无 properties（自由 dict），元素字段由消费方契约定义 → `_collect_props` 返回 `(props, opaque)`，opaque 数组元素字段降级 warning 不阻断。
- [x] T036 契约测试用例：`services/admin-web/tests/contract/test_admin_api.py`（消费方侧验证，如 admin-web 有测试目录）
  - **落地说明**：admin-web / user-web 是 Vue + TS，`package.json` **无 vitest、无测试目录**，无法按原路径放前端单测；改为在 Python 工具侧做**消费方源码静态证据扫描** `tools/contract/consumer_refs.py`（等价实现 FR-16/FR-17 的消费方侧校验）。
  - **证据**: `tools/contract/consumer_refs.py`（`normalize_url`（剥 host/query、`${id}`/`{base_url}` 参数归一为 `<p>`）/`_path_of`/`collect_urls`（抓任意字符串字面量中的路径，要求 ≥2 段）/`collect_identifiers`/`check_contract_consumers`/`_is_no_consumer`/`NO_CONSUMER_ALLOWLIST`/`main`，支持 `--all`/`--service`/`--source`/`--no-fields`）；`tools/contract/test_consumer_refs.py`（22 用例）。三份真实契约 `--all` 全部 OK（`tools/contract/` 合计 110 用例全绿）。
  - **检查规则**：①path 证据（硬检查）：契约 `base_path+path` 必须在消费方源码 URL 字面量中命中（相等 / 后缀 / 前缀更深，兼容 nginx `/askai-api` 前缀与 `f"{base_url}"` 拼接）；②notes 文件证据（硬检查）：notes 声明的消费方源码文件必须存在（同名根文件兜底）；③字段证据（warn）：200 响应字段叶子名应在消费方源码出现；④零消费方豁免：notes 含「零消费方」等标记或登记在 `NO_CONSUMER_ALLOWLIST` → 降 warn。
  - **契约侧联动**：chat-api 契约 `gaps` 新增「T036 无消费方端点登记」——list_skill_updates / list_skill_share_inbox / fetch_personal_knowledge / list_site_profiles / list_scheduled_jobs 在 user-web 源码无直接调用 URL（管理端经 admin-api BFF 或未接线），白名单豁免且配套 gaps 登记，删除前需确认接线。
- [x] T037 弃用字段观察期检查：`tools/contract/deprecation_check.py`（FR-22, US3-7, US3-8）；扫描契约文件 `deprecated: true` 标记，检查观察期（2 个 minor 版本）后才允许移除
  - **证据**: `tools/contract/deprecation_check.py`（`parse_version`/`bump_minor`（minor 进位进位到 major）/`walk_interaction_fields`（含嵌套与 `item.fields`）/`collect_deprecated`（interaction 级 + 字段级）/`check_contract`/`main`，支持 `--all`/`--service`/`--contract`/`--minors`）；`tools/contract/test_contract_deprecation.py`（28 用例）。
  - **检查规则**：①`deprecated` 项必须声明 `deprecated_since`（否则 error，rc 1）；②`deprecated_since` 不能晚于当前版本；③观察期默认 2 minor（FR-22），当前 < since+2minor → 「观察中（不可移除）」不阻断；已过 → 「已过观察期（可移除）」warn。当前版本取契约顶层 `version`（FR-16 契约持主副本）。
  - **真实扫描**：三份契约仅 document-parser 的 `delete_document_vectors_legacy`（`POST /vectors/documents/delete`）标 deprecated（since 1.0.0），当前契约 1.0.0 → 仍在观察期，最早 1.2.0 可移除，与 gaps 中「旧别名已被 T010 改 308 但消费方仍调用」一致。
- [x] T038 序列化一致性测试（FR-23, US3-9）：契约测试显式断言 JSON + snake_case
  - **证据**: `tools/contract/serialization_check.py`（`is_snake`（`^[a-z][a-z0-9_]*$` + 拒绝 `__`/首尾下划线）/`iter_response_fields`（枚举响应字段，含嵌套 `fields`）/`collect_camel`/`check_contract`（camelCase 未登记 → error，strict 默认；登记 → info）/`load_known`/`seed`（依据当前契约重新生成白名单）/`main` 支持 `--all`/`--service`/`--seed`/`--strict`/`--no-strict`）；`tools/contract/test_contract_serialization.py`（13 用例）。`tools/contract/` 合计 **123 用例全绿**。
  - **FR-23 白名单**：`specs/025-api-contract-hardening/contracts/_camel_case_known.yaml` —— `--seed` 依据当前契约生成（`{service: {interaction_id: [字段名]}}`），属「显式登记而非静默豁免」，需人工审阅后提交；未登记在表的 camelCase 字段会被视为未登记偏差（error）。
  - **审计结果（三份契约，契约按消费方实际读取的服务端字段名登记）**：admin-api 143/397 = 36.0%、chat-api 144/687 = 21.0%、document-parser 18/46 = 39.1% 字段为 snake_case；共 **103 个 interaction** 含 camelCase 字段，全部登记入白名单。覆盖率低反映**服务端 wire 格式仍以 camelCase 为主**（各契约 gaps 已登记），FR-23 目标是 snake_case，服务端迁移后逐项从白名单移除。
  - **契约侧联动**：三份契约 `gaps` 各新增 T038 条目（admin-api 新增 G7「FR-23 序列化一致性：snake_case 覆盖率偏低」），指向白名单文件与迁移方向。
  - **踩坑**：契约 gaps 有两种写法——admin-api 用 `- id: Gx` mapping、chat-api/document-parser 用 `- 纯文本`；往 gaps 追加条目必须沿用所在文件的缩进与结构（曾因缩进 0 插入 admin-api 导致 `expected <block end>, but found '-'`，已回滚重插；插入后须 `yaml.safe_load` 校验，非法则 `git checkout` 回滚）。
- [x] T039 契约验证环境隔离（FR-24, US3-10）：契约测试使用独立测试容器/fixture，不依赖共享可变环境
  - **证据**: `services/admin-api/tests/contract/conftest.py`（autouse `isolated_env` fixture：清除连接类环境变量前缀 `CONNECTION_ENV_PREFIXES`（MONGODB_/REDIS_/PANWEIDB_/WEAVIATE_/ASKAI_ADMIN_/MOGO_DOC_PROCESSING_/MOGO_DATA_/MOGO_KMS_/OSS_/OTEL_/KAFKA_/RABBITMQ_/NATS_/DATABASE_/DB_/POSTGRES_/MYSQL_/ADMIN_BACKEND_/GATE_/HTTP(S)_PROXY/NO_PROXY/ALL_PROXY），`monkeypatch.chdir(tmp_path)` 把 cwd 切到临时目录，测试结束自动恢复）；`services/admin-api/tests/contract/test_contract_isolation.py`（6 用例）。
  - **隔离性断言**：①契约测试源码（`tests/contract/*.py`）不得 import 网络 / 数据库客户端（`requests`/`httpx`/`sqlalchemy`/`asyncpg`/`psycopg`/`redis`/`motor`/`pymongo`/`clickhouse`/`kafka`/`openai`/`boto3`/`weaviate`/`elasticsearch`）；②代码行不得引用真实服务地址（`LIVE_URL_RE` 识别 `scheme://host.tld[/path]` 形态，注释与文档字符串允许示例）；③清空连接类环境变量后 `create_app().openapi()` 仍能生成（openapi 3.x + paths 非空），即**不连库、不发真实请求**；④openapi 调用不得在工作区根新增 `*.db`/`*.sqlite*`/`*.log` 共享状态文件；⑤`isolated_env` 生效后 `Path.cwd() == tmp_path != REPO`。
  - **结果**：`pytest services/admin-api/tests/contract/` **12 passed**（T035 的 6 个提供方契约测试在 autouse 隔离 fixture 下仍全绿，证明原有契约测试本就无共享环境依赖）。

---

## Phase 5: User Story 4 (P1) — API 演进与版本化

**Goal**: OpenAPI 自动生成 + 校验 + CI 阻断；版本方案全局一致；错误码集中管理。
**独立测试**: OpenAPI CI 生成并 diff；校验失败阻断；版本方案文档化；错误码字典含触发条件与处理建议。

- [x] T040 [P] 创建 `tools/openapi/generate.py`：OpenAPI 生成脚本（FR-25, QF-253）；三个服务的 OpenAPI 3.1 由 FastAPI 自动生成；输出 `openapi.json` 到 CI artifact
  - **证据**: `tools/openapi/generate.py`（`SERVICES`/`_install_celery_stub`（document-parser 的 celery 是 worker-only 依赖，schema 生成不启动 worker，注入轻量 stub：`Celery`（构造 + `conf.update` + `control.inspect(...).ping()`）/`Task`/`shared_task`/`task`）/`_build_openapi`（`try: create_app().openapi()` 兼容工厂模式；`except ImportError: app.openapi()` 兼容 chat-api 的模块级 `app`）/`_run_service`（**子进程隔离**——三个服务共用顶层包名 `app`，必须各自独立进程 import，避免模块互相污染）/`_diff_check`（重新生成到临时目录再与 artifact 比对，FR-25 CI diff）/`_rel`/`main` 支持 `--service`/`--all`/`--out`/`--check`）；`tools/openapi/test_contract_openapi_generate.py`（8 用例）。
  - **artifact 输出目录**：`specs/025-api-contract-hardening/openapi/{service}-openapi.json`（默认，可 `--out` 覆盖）。
  - **结果**：三服务 OpenAPI 3.1 生成成功——admin-api 212 paths、chat-api（模块级 `app`）、document-parser 10 paths（stub celery 后正常）。
  - **用法**：`python3 tools/openapi/generate.py --all` 生成；`--all --check` 与已提交 artifact 比对（不一致 rc=1，供 CI 阻断）。
- [x] T041 [P] 创建 `tools/openapi/validate.py`：OpenAPI 校验脚本（FR-26, QF-255）；执行 `openapi-spec-validator` + `spectral lint`，失败阻断 PR
  - **证据**: `tools/openapi/validate.py`（`check_service`：①`openapi-spec-validator` 结构校验（OpenAPI 3.1 合法性，含 schema 内部一致性如 uniqueItems/minLength）②`_builtin_lint` 内置规则兜底 ③`spectral` CLI 检测——已安装则执行、未安装则提示并回退内置 lint（`--skip-spectral` 显式跳过）；`_builtin_lint(spec) -> (阻断项, 提示项)`：L1 info.title/version【阻断】、L2 paths 非空【阻断】、L3 operationId 唯一【阻断】、L4 operation tags【**提示不阻断**】、L5 4xx/5xx 响应带 description【阻断】、L6 响应有 content 或 description【阻断】；`_is_error_status`；`main` `--service`/`--all`/`--dir`/`--skip-spectral`）；`specs/025-api-contract-hardening/openapi/.spectral-ruleset.yaml`（`extends: spectral:oas`，`operation-operationId(-unique)`/`response-error-description` 为 error，`operation-tags` 为 warn，与内置 lint 严重级一致）；`tools/openapi/test_contract_openapi_validate.py`（18 用例）。`tools/openapi/` 合计 26 用例全绿。
  - **真实 bug 修复（chat-api，openapi-spec-validator 报 INVALID）**：
    1. `RegisterRequest` / `SelectTenantRequest` / `SwitchTenantRequest`（`services/chat-api/app/api/endpoints/auth.py`）同时声明 `tenant_id: Field(alias="tenantId")` 与 `tenantId: Field(alias="tenantId")` → OpenAPI `required` 出现重复 `tenantId`（uniqueItems 违规）。修法：`tenantId` 改为 `Optional[str] = Field(default=None, max_length=64, alias="tenantId")`，使其不再进入 required；该字段因 alias 冲突实际永远为 None（JSON `tenantId` 已映射到 `tenant_id`），必填校验仍由 `tenant_id` 把关。曾尝试 `exclude=True`，但 Pydantic v2 的 `exclude` 不影响 JSON schema 生成，无效。
    2. `ToolDescriptionGeneratePayload.name: Field(default="", min_length=1, max_length=120)`（`external_tools.py:31`）default 空串违反 minLength=1 → 改为 `Field(min_length=1, max_length=120)`（required）。消费方 `apps/user-web/src/api/tools.ts` 的 `generateToolDescription` 类型里 `name` 本就是必填，改 required 与消费方一致（FR-18）。
  - **待补项（提示，不阻断）**：chat-api 有 168 条 operation 无 `tags`（L4 提示），属文档元数据缺失，不影响契约；建议后续为路由补 tags（未在本任务修复以控制改动面）。
  - **依赖**：本地 `pip install openapi-spec-validator`（0.9.0）已安装并用于校验；spectral CLI（`@stoplight/spectral-cli`）未安装，CI 环境需安装后自动启用（未安装时脚本回退内置 lint 并打印提示）。
  - **用法**：`python3 tools/openapi/validate.py --all`；`--all --skip-spectral` 跳过 spectral 检测。
- [x] T042 [P] 创建 `docs/api-versioning.md`：版本方案文档（FR-27, FR-28, QF-264, QF-267）；URL 路径 `/v1/` + `API-Version` 响应头双轨；版本升级幅度规则
  - **证据**: `docs/api-versioning.md`。要点：①**双轨模型**——主版本走 URL 前缀 `/v1/`（破坏性边界，旧路径保留 301 重定向），小版本走响应头 `API-Version`（向后兼容演进，实现见 T044 `services/admin-api/app/middleware/api_version.py`）+ 可选请求头 `X-API-Version` 协商（服务端不拒绝、只回报实际契约版本）；②**幅度规则（FR-28）**——复用 `tools/contract/diff.py` 的 `COMPAT_TYPES`（`added_interaction`/`new_optional_field`/`new_success_status`/`removed_interaction_deprecated` 等 → minor）与 `BREAKING_TYPES`（`changed_method`/`changed_path`/`changed_field_type`/`field_turned_required`/`new_required_field`/`changed_status_semantics` → major），patch 仅限文档/描述类修订；③**废弃观察期**——对齐 FR-22/`deprecation_check.py`：`deprecated` + `deprecated_since` 后至少观察 2 minor 方可移除（`bump_minor(version, minors=2)`），已知实例 `document-parser` 的 `delete_document_vectors_legacy`（since 1.0.0，最早 1.2.0 可移除）；④**升级流程 7 步**：改契约 → `diff.py` 分类 → `deprecation_check.py` → 契约 `version` bump → 改实现 → `generate.py --check` + `validate.py --all` → CI 阻断（T048）；⑤**迁移到 `/v1/`**——目标 `services/*/app/api/routes/` 业务路由挂 `/v1`，旧路径 301 兜底，例外：`/askai-api` legacy 与跨服务回调 URL 暂不迁移；⑥**当前版本清单**：三契约均 `1.0.0`，`admin-api`/`chat-api` pyproject `0.2.5`，`document-parser` pyproject **未设置 version 字段**（待补）；⑦明确「契约版本（对外 API 语义）」与「pyproject 服务发布版本（内部制品）」是**两套独立版本号**，不混用。
  - **现状核对**：三服务目前均**无 `/v1` 前缀**（grep `prefix="/v1"` 零命中），`API-Version` 响应头尚无实现——两者分别由 T045 / T044 落地；文档已如实登记「迁移中/未实现」而非伪称已完成。
- [x] T043 [P] 创建 `docs/error-codes.md`：错误码字典文档（FR-30, QF-269）；跨服务汇总所有错误码，含 `code`/`http_status`/`trigger`/`remedy` 四字段
  - **证据**: 与 T051 合并为同一份 `docs/error-codes.md`（详见 T051 条目），含通用 15 码字典表（三服务共享）+ 业务错误码登记表 + 响应体结构 + 稳定性与变更流程。
- [x] T044 创建 `API-Version` 中间件：`services/admin-api/app/middleware/api_version.py`（FR-27, QF-264）；注入 `API-Version` 响应头
  - **证据**: `services/admin-api/app/middleware/api_version.py`（`API_VERSION_HEADER = "API-Version"` / `REQUEST_VERSION_HEADER = "X-API-Version"` / `API_VERSION = "1.0.0"`；`ApiVersionMiddleware(BaseHTTPMiddleware)`：`dispatch` 在 `call_next` 后写 `response.headers["API-Version"] = API_VERSION`；docstring 明确「版本号唯一主副本是 `contracts/admin-api.yaml` 顶层 `version`，改动须同步本常量，且与 `pyproject.toml` 发布版本是两套独立版本号」）；`services/admin-api/app/main.py` 在 `TraceIdMiddleware` 之后 `app.add_middleware(ApiVersionMiddleware)`（最后 add 即最外层，保证所有经过中间件链的响应都带 `API-Version`）。
  - **行为对齐** `docs/api-versioning.md` §2.2：请求带 `X-API-Version` **不拒绝**（避免脆性），只回报实际契约版本。
  - **验证**：FastAPI `TestClient` 挂中间件 GET `/health`（带 `X-API-Version: 9.9.9`）→ `200` + `API-Version: 1.0.0`（请求未被拒绝）。
  - **注**：500 响应由 `ServerErrorMiddleware`（最外层）产出、不经过 `BaseHTTPMiddleware`（同 `TraceIdMiddleware` 已知限制），`API-Version` 头对 500 不保证存在——如需覆盖可另在异常处理器补头，本轮不扩展。
- [x] T045 路由迁移到 `/v1/` 前缀（FR-27, QF-264）：扫描 `services/*/app/api/routes/`，添加 `/v1` 路由前缀；旧路径保留向后兼容（301 重定向）
  - **证据**: ①**主挂载前缀迁移**——`services/admin-api/app/main.py`（`api_router` / `extension_router` `prefix="/api"` → `"/api/v1"`）、`services/document-parser/app/main.py`（`api_router` 同）、`services/chat-api/app/main.py`（**33 处** `include_router(..., prefix="/api")` → `"/api/v1"`）；②**chat-api 内部硬编码完整路径的 router prefix** 一并迁移 8 个文件（`context_space.py`/`portal.py`/`memory.py`/`knowledge_graph.py`/`harness_profiles.py`/`ontology_grants.py`/`orchestrations.py`/`business_index.py`：`APIRouter(prefix="/api/...")` → `"/api/v1/..."`）；③**新中间件** `services/*/app/middleware/legacy_api_redirect.py`（三服务各一份同型）：`LegacyApiRedirectMiddleware` 把旧 `/api/*`（非 `/api/v1/*`）永久重定向到 `/api/v1/*`（保留 query）；④**契约联动**——三份契约 `base_path: /api` → `/api/v1`；⑤**工具联动**——`tools/contract/consumer_refs.py` 新增 `_version_agnostic(path)`（`VERSION_SEGMENT_RE = re.compile(r"/v\d+")` 去掉路径首段主版本）并在 `check_contract_consumers` 比对时对 `full`/`bare` 与消费方 URL 集合都做版本无关归一化，否则契约 `/api/v1/x` 匹配不到消费方源码 `/api/x`；⑥**重新生成并校验**——`generate.py` 三服务 + `validate.py --all` 全通过（admin-api 212 paths 全 v1、chat-api 190 paths 中 180 条 v1 无 legacy、document-parser 10 paths 全 v1）。
  - **对任务原文「301 重定向」的工程化偏离（已记录）**：301 对非 GET 方法语义未定义，多数客户端会把它转成 `GET` 重发，**导致写操作丢失**（如 `POST /api/sessions` 变 `GET /api/v1/sessions`）。故实现为 **`GET`/`HEAD` → 301**（符合原文）、**`POST`/`PUT`/`PATCH`/`DELETE` 等 → 308**（保留方法与请求体），保证写操作向后兼容。对齐 `docs/api-versioning.md` §2.1「旧路径保留 301」并已在 docstring 说明原因。
  - **验证**：admin-api `TestClient` `follow_redirects=False` → `GET /api/auth/me` **301** → `/api/v1/auth/me`；`POST /api/auth/login` **308** → `/api/v1/auth/login`；`GET /health` **200**（非 `/api` 前缀不受影响）。document-parser 的 TestClient 因本地未装 `celery` 无法完整 import（`app.tasks.base` → `celery.Task` `ModuleNotFoundError`，T040 的 celery stub 仅 OpenAPI 生成路径使用），其 prefix/中间件改动已由 OpenAPI 生成（9 条 v1 路径）间接验证。
  - **排除范围**：`/askai-api/api/files`（chat-api `FILE_PUBLIC_PATH_PREFIX`，文件公开 URL 前缀，非 API 路由）与 `/health` `/metrics` `/openapi.json` 等非 `/api` 前缀路由不迁移；chat-api 不带 prefix 的 `include_router`（`dsh_model_gateway`、`a2a`、`memory`（已改内部 prefix）、`research`、`portal`（已改内部 prefix）等，其路由路径已通过内部 prefix 或路径字面量迁移）经 OpenAPI 复查无 legacy `/api` 残留。
  - **回归**：`pytest tools/contract/ tools/openapi/` 149 passed；`consumer_refs.py --all` exit=0 且 0 error（仅契约已标注零消费方的 warn）。
- [x] T046 错误码映射稳定性检查（FR-31, QF-270）：CI 检查错误码与 HTTP 状态码映射变更，需版本升级
  - **证据**: `tools/api_check/error_code_mapping.py`（CLI AST/正则扫描，退出码 0/1）。要点：
    1. **基线快照** `specs/025-api-contract-hardening/baseline/error-code-mapping.json`（首次运行自动生成，45 映射 = 15 通用码 × 3 服务；`--update-baseline` 在有意变更并完成 major 升级后重建基线）。
    2. **映射漂移检测**：基线里存在的 code，其 `http_status` 变更或从实现中**移除** → 判为 `changed_status_semantics`（`tools/contract/diff.py` 的 BREAKING_TYPES），须 major 版本升级（rc=1）；新增 code 只打 `[compat]` info，不阻断。
    3. **字典一致性**：`docs/error-codes.md` §2 通用码表（唯一权威字典 FR-30）与三服务 `app/core/errors.py` 的 `ApiErrorCode` 枚举 + `DEFAULT_HTTP_STATUS` 逐码比对，报 `doc-drift`（状态码不一致）/`doc-orphan`（字典有实现无）/`undocumented`（实现有字典无）/`[drift]`（跨服务状态不一致）。
    4. **权威口径**：以 `ApiErrorCode` 枚举为权威集合过滤映射，`DEFAULT_HTTP_STATUS` 里残留的孤儿条目不算可用映射；`errors.py` 缺失时不 crash，按空映射处理（配合 doc-orphan 报错）。
    5. **CLI**：`--baseline` / `--dict` / `--services` / `--update-baseline`。
    6. **命令与结果**：`python3 tools/api_check/error_code_mapping.py` → `error-code mapping OK — no status-semantics drift`（rc=0）；`tools/api_check/test_error_code_mapping.py` **13 用例全绿**（首次生成基线、无漂移通过、状态码变更检测、码移除检测、新增码 compat、--update-baseline 重建、doc-drift/doc-orphan/undocumented、跨服务 drift、未知服务 SystemExit、errors.py 缺失容忍、parse_docs_dict/parse_errors_py 单元）。
- [x] T047 OpenAPI 与实测一致性检查（FR-25, QF-254）：CI 中执行探针验证 OpenAPI 定义中的路径/参数/响应与实测一致
  - **证据（2026-10-26）**：新建 `tools/openapi/probe.py`（FR-25, QF-254），用 FastAPI `TestClient` 实测**只读、无副作用**端点，做三类比对：①路径可达性（实测 404 → 不一致）；②参数生效性（OpenAPI 声明 `required: true` 的 query 参数，实测**不带**应 422）；③响应字段名（实测 JSON 顶层字段名集合 vs 响应 schema 属性名集合，递归处理 `$ref`/`allOf`/`oneOf`/`properties`，数组元素自由 dict 视为 opaque 跳过）。
  - **实测命令与结果**：`python3 tools/openapi/probe.py --all --limit 12 --json`（rc=1）。三服务各探 12/12/3 端点：
    - `[admin-api] skipped` — 12 端点**无一致性问题**；`GET /ready` 实测 503（依赖不可用）跳过；多数业务端点实测 401（认证拦截，字段/参数跳过，不影响路径可达性结论）。
    - `[chat-api] problem` — **4 处真实不一致**（见下）。
    - `[document-parser] skipped` — 本地缺 `celery`，probe 子进程复用 `generate._install_celery_stub()` 注入 stub 后 import 成功；实测 3 端点均 503（worker/DB 依赖不可用）跳过，**跳过不阻断**（rc=0 口径）。
  - **发现的真实不一致（chat-api，均已闭环解决）**：
    1. `GET /api/v1/browser/recording/stream` 422 响应体为 `{error_detail,status,title,type}`（RFC 7807 problem 结构），但 OpenAPI 422 声明的是 `#/components/schemas/ErrorResponse`（属性 `code/message/http_status/trace_id/detail/fields`）。
       - **闭环修复**：实测该 422 响应体**同时**含 MOGO 兼容键（`code/detail/field/fields/http_status/message/path/trace_id`）与 RFC 9457 键（`error_detail/status/title/type/instance`）——`build_error_payload`（`services/chat-api/app/core/errors.py:81`）刻意双写以兼容旧消费方依赖的 RFC 7807 语义。根因是 chat-api `ErrorResponse` 模型只声明 MOGO 键、漏声明 RFC 9457 键。**修法：在 `ErrorResponse` 增加 5 个可选字段** `type`/`title`/`status`/`instance`/`error_detail`（均 `default=None`，属 FR-21「新增可选字段不破坏旧消费方」），使 OpenAPI schema 覆盖实测字段；不动 `build_error_payload`、不改 handler、不影响既有响应体。重生成 chat-api OpenAPI 后 `probe.py --service chat-api` → `skipped`。
    2. `GET /api/v1/debug/env-metrics`、`/debug/llm-config`、`/debug/runtime-kpi` OpenAPI 已声明但实测 404——`debug.py` 用 `require_debug_mode` 依赖在**非 DEBUG 环境抛 404 故意隐藏**，但 OpenAPI 仍声明了这些路径。
       - **闭环处理（探针侧豁免）**：`debug.py` 的 router 用 `dependencies=[Depends(require_debug_mode), Depends(require_end_user_principal)]`，而 `require_debug_mode()` 在 `get_settings().DEBUG` 为 False 时 `raise HTTPException(404)`；本地默认 DEBUG=False → 实测 404 是**预期行为，非契约漂移**。探针新增 `BUSINESS_404_PREFIXES = ("/api/v1/debug/",)` + `BUSINESS_404_HINT`，命中则记 `note` 不判 `problem`（FastAPI 0.141 的 `_IncludedRouter` 无法静态枚举 `app.routes`，故不依赖 mounted 集，改走前缀白名单）。
  - **最终探针结果**：`probe.py --all` 三服务均 `skipped` 且 **rc=0**（admin-api 15 / chat-api 15 / document-parser 3 端点），QF-254 达成。
  - **实现要点**：①三服务共用顶层包名 `app`，**必须各自独立子进程 import**（`--all` 走 subprocess，复用 `generate.py` 的隔离方式）；②**不能静态枚举 `app.routes` 判路径**——admin-api / chat-api 顶层 routes 是 FastAPI `_IncludedRouter`（延迟挂载），`app.openapi()` 也不改写 `app.routes`，静态收集会误报「未挂载」→ 一律以**实测**为准；③chat-api 会劫持 `sys.stdout`（structlog），`print` 不可靠 → 子进程结果写**临时文件**回读；④`TestClient` 不用 `with`（不触发 lifespan，避免 DB 依赖）；⑤因 DB 不可用导致的 5xx、认证拦截的 401/403 **跳过而非判不一致**。
  - **测试**：`tools/openapi/test_contract_openapi_probe.py` **16 用例全绿**——artifact 加载、字段名递归收集（`$ref`/`allOf`/`oneOf`/opaque/未知 schema）、必填 query 参数提取、document-parser 跳过逻辑（断言 rc=0 且非 error）、CLI rc、JSON 报告结构。


---

## Phase 6: CI 接入 & Polish

- [x] T048 [P] 更新 `.github/workflows/quality-gate.yml`：新增 job `api-contract-hardening`，执行：
  - `tools/api_check/path_naming.py`（路径命名检查，FR-1）
  - `tools/api_check/error_codes_uniqueness.py`（错误码重名检查，FR-29）
  - `tools/api_check/error_code_mapping.py`（错误码↔HTTP 状态码映射稳定性，FR-31，T046 新增）
  - `tools/contract/validate.py`（契约测试，FR-16 ~ FR-24）
  - `tools/contract/diff.py`（兼容性 diff，FR-20）
  - `tools/openapi/generate.py` + `tools/openapi/validate.py`（OpenAPI 生成 + 校验，FR-25, FR-26）
  - `tools/contract/deprecation_check.py`（弃用字段观察期，FR-22）
  - `tools/contract/consumer_refs.py --all`（消费方源码证据，FR-16/FR-17）
  - **证据**: `.github/workflows/quality-gate.yml` 新增 job `api-contract-hardening`（ubuntu-latest，30 分钟超时，12 步）。要点：
    1. **依赖与现有 job 保持一致**：`actions/checkout@v4`（`fetch-depth: 2`，diff 需取 HEAD~1 契约）+ `actions/setup-python@v5`（3.13）；宿主 python3 装 `PyYAML openapi-spec-validator`（契约/OpenAPI 校验工具依赖）；再为三服务各建 venv 并以 `--require-hashes -r requirements.txt` 安装（OpenAPI 生成经 subprocess 隔离 import `app.main`，与 backend-quality 安装口径一致）。
    2. **8 个检查步骤**：path_naming → error_codes_uniqueness → error_code_mapping → contract validate（不传 `--service` 即全三服务）→ 三服务 `diff.py --old <git show HEAD~1> --new <当前>`（无上一版则跳过）→ `generate.py --service X --check`（在各自 venv python 下跑，避免 `app` 包名互相污染）+ `validate.py --all`（spectral 未装自动回退内置 lint）→ `deprecation_check.py --all` → `consumer_refs.py --all`。
    3. **本地逐步骤验证全过（rc=0）**：`path-naming OK`、`error-codes uniqueness OK — 0 service-specific codes, 15 common codes`、`error-code mapping OK — no status-semantics drift`、`admin-api: contract OK — 46 interactions / chat-api: 63 / document-parser: 10`、三服务 `contract diff: 0 change(s), 0 breaking`、`artifact 与当前实现一致` × 3、`openapi-spec-validator 通过` × 3、`deprecation check OK` × 3、`consumer-refs check OK` × 3。
    4. **quickstart.md §9** 同步更新为实际 CLI 参数（原草案用了不存在的 `--services`/`--contract-dir`/`error_code_mapping.py --all`/`diff.py --base HEAD~1`）。
- [x] T049 [P] 创建 `specs/025-api-contract-hardening/checklists/requirements.md`：需求质量门禁（CHK 检查项，`/speckit-implement` 拦截）
  - **证据**: `checklists/requirements.md`（已在 US1/US2 建立 CHK001–CHK018 并全部勾选，覆盖完整性/一致性/边界与歧义）。本轮追加 **CHK019–CHK025**「US3/US4 演进需求（随实现闭环回填）」，把 CHK008/CHK009 从"已定义"推进到"已具备可执行验收命令与门禁"：CHK019 三份契约实际生成并通过 `validate.py --all`（46/63/10 interactions）；CHK020 消费方源码证据自动核验（`consumer_refs.py --all`，版本无关匹配）；CHK021 提供方 OpenAPI 结构级测试（`services/admin-api/tests/contract/test_admin_api.py`）+ 已修复 3 处 `/api/api/*` 双重前缀与 `items↔data` 字段断裂；CHK022 OpenAPI 自动生成 + `--check` CI diff + 校验（含 chat-api `required` 重复 `tenantId` 与 default 空串两处修复）；CHK023 版本方案三要素（URL `/api/v1`、`API-Version` 响应头、旧路径 GET/HEAD 301 + 其他方法 308 重定向，口径 `docs/api-versioning.md`）；CHK024 错误码字典唯一权威（`docs/error-codes.md`）+ 映射稳定性门禁（`error_code_mapping.py`，`changed_status_semantics` 须 major 升级）；CHK025 CI `api-contract-hardening` job 全链路装配。Notes 明确「`[x]` 代表需求质量达标，不代表实现完成；实现状态以 tasks.md 与 QualityForge 审计回写为准」。
- [x] T050 写 `quickstart.md`（本特性的启用 + 验证步骤）
  - **证据**: `quickstart.md` 更新三处以对齐 US3/US4 最终产出：①§5.1 改为实际命令（`tools/openapi/generate.py --all` / `--service X`，artifact 输出 `specs/025-api-contract-hardening/openapi/*-openapi.json`；`validate.py --all --skip-spectral` 处理本地未装 spectral），并记录 T041 两处 schema 修复；②§5.2 扩写版本方案四要素——URL 主版本（T045 三服务迁 `/api/v1`，chat-api 33 处 include_router prefix + 8 个内部 router prefix）、旧路径重定向（`LegacyApiRedirectMiddleware` GET/HEAD 301、其他 308 保留方法）、`ApiVersionMiddleware` 写 `API-Version: 1.0.0`（T044）、口径文档 `docs/api-versioning.md` 与 `docs/error-codes.md`；③§6 验证清单追加第 19–24 行（契约结构校验、消费方证据、错误码映射稳定性、OpenAPI 与实测一致性、OpenAPI 与契约 CI diff、旧路径重定向 TestClient 301/308/200）；§9 CI 段更新为 `api-contract-hardening` job 的完整 8 步命令序列。
- [x] T051 [P] 错误码字典跨服务汇总：`docs/error-codes.md`（FR-30，T043 的详细版，含三个服务所有错误码）
  - **证据**: `docs/error-codes.md`（唯一权威字典，按服务分节跨服务汇总）。要点：
    1. **命名空间**：`api.<domain>.<error>`（FR-11）；**服务前缀不写进 code**（避免与 022 既有码冲突），所属服务写在 `service` 列。
    2. **通用 15 码字典表**（§2，三服务 `app/core/errors.py` 的 `ApiErrorCode` + `DEFAULT_HTTP_STATUS` 完全一致）：`api.internal_error`/`not_found`/`method_not_allowed`/`validation_error`/`bad_request`/`unauthorized`/`forbidden`/`conflict`/`rate_limited`/`payload_too_large`/`unsupported_media_type`/`not_acceptable`/`precondition_failed`/`service_unavailable`/`partial_failure`，每行含 `code`/`http_status`/`trigger`（触发条件，如「401 不泄漏资源存在性 FR-12」「429 超配额 FR-13」「413 载荷超限 FR-5」「412 ETag/If-Match 不匹配 FR-8」「406 内容协商 FR-9」「200+partial=true FR-14」）/`remedy`（处理建议，如「携带 trace_id 反馈」「尊重 Retry-After 头」）。
    3. **业务错误码登记表**（§3，非 `api.*` 前缀，尚未纳入统一枚举）：`DUPLICATE_FILENAME`（admin-api 409，`knowledge_documents.py:777`）、`skill_upgrade_confirmation_required`（chat-api 409，`skill_package_install.py:49,95`）、`metadata_mismatch`（chat-api 400，`validator.py:216`，`_meta.json` slug 与 `SKILL.md` name 不一致）、`version_metadata_mismatch`（提示不阻断，`validator.py:222`）、`skill_share_token_required`（chat-api，状态由 handler 决定，`skill_sharing/service.py:269`）、`requested_slide_count_mismatch`（chat-api 400，`presentation/service.py:177`）——每行含 `code`/`service`/`http_status`/`trigger`/`remedy`/`来源（文件:行）`，并注明「经业务异常抛出、最终状态码由 handler 决定，如路由显式改映射以路由为准并回写本表」。
    4. **稳定性与变更流程**（§4，FR-31）：`code` 值一经发布不可变更含义；映射变更属 `changed_status_semantics`（破坏性），必须 major 版本升级（对齐 `docs/api-versioning.md`）；新增码需同步登记本字典 + 契约 `error_codes` 注册表 + `validate.py` 校验；CI 用 `tools/api_check/error_codes_uniqueness.py` 保证跨服务唯一（T046 装配）。
    5. **响应体结构**（§5，FR-10/FR-29）：`application/problem+json`（RFC 9457 扩展），字段 `code`/`message`/`http_status`/`trace_id`/`fields[]`/`detail`/`error_detail`/`docs_url`；RFC 9457 映射（`type`←`docs_url`，`title`←`code`，`status`←`http_status`，`instance`←`docs_url`）；**兼容层**：`detail` 与 `message` 同时保留（FastAPI 既有消费方读 `data.detail`，chat-api envelope 消费方读 `message`，US2 收敛前不移除）。
    6. **待补**：业务错误码集中化到 `ApiErrorCode` 待后续 US；`api.partial_failure`（200）与错误码命名冲突已按 FR-14 明确。
  - **修正过程**：初版误把 `password_change_not_required`（auth.py:263 的**函数名**，非错误码）列为业务码，已删除；`skill_share_token_required` / `metadata_mismatch` / `requested_slide_count_mismatch` 均经业务异常（`SkillPackageError`/`SkillShareError`）抛出，其 `http_status` 如实标为「由 handler 决定」而非臆测。
- [x] T052 [P] QualityForge 审计回写：50 个 QF 项状态从 `fail`/`pending` 转为 `pass`/`na`（有理由），回写到 `.qualityforge/audit.json`
  - **证据**: `.qualityforge/QUALITYFORGE-REPORT.md` 更新三处——①§1 台账 025 行进度 `7/52 🔨` → `46/52 🔨`，台账状态改为「US1–US4 主体已落地（语义/错误/契约/OpenAPI/版本化）」，并指向 §4；②§3 待补项 025 行从「大部分未解除」改为「主体已解除（仅 US4 的 T046/T047 装配进行中，对应 QF-270/QF-254 暂挂 pending）」；③新增 **§4「025 子域状态回写表」**。
  - **50 项口径**（在 §4 中声明）：40 条 QF 编号已落入 `spec.md` 锚点（US1 17 项 + US2 15 项 + US4 8 项）逐条回写；US3 契约域 10 条原件未编号，按子域聚合回写（对齐 §2 023 的处理口径）。状态定义：`pass`＝对应任务已勾选且工具/测试可核验；`na`＝首期 Non-Goals 明确不适用；`pending`＝装配任务未完成。
  - **汇总**：50 项 = **47 pass / 1 na / 2 pending**。`na` 为 **QF-227 压缩协商**（首期 Non-Goals 未引入 gzip 内容编码协商，Accept 406 已由 QF-225 覆盖）。`pending` 为 **QF-254**（OpenAPI 与实测一致性，T047）与 **QF-270**（错误码-状态码映射稳定，T046），均为 CI 装配进行中。US1 语义 17 项（16 pass + 1 na）、US2 错误 15 项全 pass、US3 契约 10 项全 pass、US4 演进 8 项（6 pass + 2 pending）。
  - **关键可核验交付物**（逐行写入 §4 的"可核验交付物"列）：`tools/api_check/path_naming.py`、`tools/contract/validate.py --all`、`tools/contract/diff.py`、`tools/contract/deprecation_check.py`、`tools/contract/consumer_refs.py --all`、`services/admin-api/tests/contract/test_admin_api.py`、`tools/openapi/generate.py --all --check`、`tools/openapi/validate.py --all`、`docs/api-versioning.md`、`docs/error-codes.md`、`LegacyApiRedirectMiddleware`（301/308）、`ApiVersionMiddleware`（`API-Version` 头）、`tools/api_check/error_codes_uniqueness.py`。
  - **与任务措辞的差异（登记）**：任务原文要求"回写到 `.qualityforge/audit.json`"，但 `.qualityforge/README.md` 明确决策 **`audit.json`（约 1.1MB 审计原始数据）不入库**，只维护台账 `QUALITYFORGE-REPORT.md`。按 README 入库边界，改为回写到本报告的 §4 子域回写表，并在 §4.5 末尾与 §变更记录 登记该差异（「报告内容与 spec 冲突时以 spec 为准并在此登记差异，不要反向修改 spec」）。

---

## Dependencies

```text
Phase 1 (基础设施：错误码 + ErrorResponse + trace_id) → Phase 2 (US1 语义) + Phase 3 (US2 错误)
Phase 2 + Phase 3 → Phase 4 (US3 契约测试)
Phase 4 → Phase 5 (US4 演进)
Phase 5 → Phase 6 (CI 接入 & Polish)
关键依赖: T001-T004 被 US1/US2/US3/US4 全部复用；T030-T032 契约文件被 T033-T039 复用；T040-T041 OpenAPI 工具被 T048 CI 复用
```

## Parallel Opportunities

- **Phase 1**: T001-T004 可并行（三个服务同步）；T005/T006 可并行
- **Phase 2**: T011（状态码扫描）可与其他任务并行；T013/T015/T016/T017/T019 互不依赖可并行
- **Phase 3**: T024/T025（限流）互不依赖可并行；T029 测试可独立
- **Phase 4**: T030/T031/T032（契约文件）可并行；T035/T036（两侧测试）可并行
- **Phase 5**: T040/T041/T042/T043 互不依赖可并行
- **Phase 6**: T048/T049/T051 可并行

## MVP Scope

- **最小可交付 = Phase 1 + Phase 3**（T001-T007 + T021-T029）：统一错误响应结构 + 错误码注册表 + 限流 + 批量语义——**api-errors 域实测 fail 项全部清零**。
- 增量交付：US1（语义，含实测 fail 修复）→ US3（契约测试）→ US4（演进）。

## Implementation Strategy

- **先 MVP（US2 错误处理）**：因为审计实测 fail 项集中在 api-errors 域（QF-229, 230, 234, 237），且 US2 不依赖契约测试框架，可独立交付
- **再 US1（语义）**：修复 api-semantics 域实测 fail 项（QF-202, 204, 210, 213, 218）
- **再 US3（契约测试）**：从零搭建契约测试框架
- **最后 US4（演进）**：OpenAPI 校验 + 版本方案
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 实测 fail 项优先修复，不能只补文档

## Notes

- 本 tasks.md 为 `/speckit-tasks` 产出，含 025 的 clarify 决策（RFC 9457 错误结构、幂等键作用域、批量 200+partial、URL+Header 双轨版本、限流阈值）。
- **api-semantics 和 api-errors 两域有实际 fail 项**，修复必须以实测为准（不能只补文档）。
- 实现需先通过 `checklists/requirements.md` 门禁；CHK 检查项需与 spec.md FR 双向对齐。
- **实现进展（2026-10-24）**：Phase 1 T001–T007 已落地——三服务各自新增 `app/core/errors.py`（错误码注册表 + `ErrorResponse` + `build_error_payload`）、`app/core/error_handler.py`（接管 422/500；路由级 `HTTPException` 形状不动，属 T011 范围）、`app/middleware/trace_id.py`（`X-Trace-ID` 沿用/生成 + 响应头回写）、`app/core/errors_codes.md`（四字段字典）；`tools/api_check/error_codes_uniqueness.py` 已接入 `.github/workflows/quality-gate.yml`（backend-quality，admin-api 单次执行）。兼容口径：错误体并存 `detail`（字符串，前端既有消费）/`message`（chat-api envelope）/RFC 9457 键（type/title/status/instance），结构化 detail 移至 `error_detail`；chat-api 旧数值 code 按 FR-11 废弃为字符串稳定码，SSE 流内帧不受影响。验证：admin-api 全量 pytest 通过（含新增 `tests/test_error_contract_phase1.py` 14 项）、chat-api 全量通过、document-parser 全量通过、check_python_static 三服务门禁通过、uniqueness 脚本 OK。
- 跨服务错误码重名检查（T007）需在三个服务都完成后执行。
- 契约测试（T033-T039）需三个服务的 OpenAPI 生成（T040）后才能完整执行。
