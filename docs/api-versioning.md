# API 版本方案（025 契约硬化 · FR-27 / FR-28）

> 本文档是全仓库 API 版本化的**唯一权威定义**，对应验收项 FR-27（版本双轨）、FR-28（幅度规则）与 QF-264 / QF-267。配套工具：`tools/contract/deprecation_check.py`（观察期，FR-22）、`tools/contract/diff.py`（幅度分类）、`tools/openapi/generate.py` / `validate.py`（生成与校验）。

## 1. 目标

- 客户端**不需要**跟着我们的内部发布节奏改代码：向后兼容的改动永远以 minor 发布，客户端可继续用旧版本。
- 破坏性改动必须显式升级主版本，并在迁移期保留旧路径（301 重定向）。
- 客户端能随时知道当前响应对应的 API 版本（通过响应头），避免把「新版字段」当「旧版不存在」或反之。

## 2. 双轨版本模型

每个接口同时携带两个版本维度，二者职责不重叠：

| 维度 | 载体 | 作用 | 变化频率 |
|---|---|---|---|
| **主版本** | URL 路径前缀 `/v1/`、`/v2/` … | 破坏性变动的边界；主版本不同=不兼容 | 极低（只在破坏性变更时 bump） |
| **小版本** | 响应头 `API-Version`；可选请求头 `X-API-Version` 协商 | 向后兼容的演进（新增字段/端点/成功响应分支） | minor 级 |

### 2.1 主版本（URL 前缀）

- 各服务的主版本按 §6 迁移到 **v1**（`/api/v1/...`）；迁移完成前路由暂挂在 `/api/...`（现状，T045 未完成）。
- 主版本提升（`v1 → v2`）只发生在破坏性变更，且**旧路径保留**：旧 `/api/v1/...` 仍可访问，服务端返回 `301 Moved Permanently` 重定向到 `/api/v2/...`，给消费方一个 minor 级观察期迁移（对齐 FR-22 的 2 minor 观察期）。
- 消费方**禁止**在代码里硬编码主版本号之外的版本信息；升级主版本时由运维统一更新 base path。

### 2.2 小版本（响应头）

- 每个服务在响应中注入响应头 `API-Version: <service-contract-version>`（例如 `API-Version: 1.2.0`）。实现见 T044 `services/admin-api/app/middleware/api_version.py`（其余服务同型）。
- 契约版本号以 `contracts/<service>-api.yaml` 顶层 `version` 字段为**唯一主副本**（FR-16）。当前三个服务契约版本均为 `1.0.0`。
- 客户端可选发送 `X-API-Version: <wanted>` 请求头声明期望的 minor 版本；服务端**不因此拒绝请求**（避免脆性），只在返回响应时保证 `API-Version` 头反映服务端实际契约版本，供客户端自行比对。

## 3. 幅度规则（FR-28）

版本号的语义变更，由 `tools/contract/diff.py` 的契约 diff 分类器决定。**契约是消费方视角**，所以方向与直觉相反：

### 3.1 向后兼容（→ minor bump）

- `added_interaction`：新增端点
- `new_optional_field`：新增可选字段
- `new_success_status`：新增成功响应分支（如 `200` 外新增 `201`）
- `removed_interaction_deprecated`：删除已过观察期的 `deprecated` 端点
- `removed_field` / `removed_interaction` / `removed_error_status` / `removed_error_code`（非 deprecated 端点上的删除，理论上消费方不受影响，仍按兼容处理）

### 3.2 向后不兼容（→ major bump）

- `changed_method`：HTTP 方法变更
- `changed_path`：路径变更
- `changed_field_type`：字段类型变更（`number → string`、`id(int) → id(str)` 等）
- `field_turned_required`：可选字段改为必填
- `new_required_field`：新增必填字段
- `changed_status_semantics`：响应状态码语义变化（同一 code 含义改变）

任何一次 major bump 都要求：
1. 更新契约版本号（`1.x.y → 2.0.0`）与 URL 前缀（`/api/v1/` → `/api/v2/`）；
2. **旧路径保留**并 301 重定向（§2.1）；
3. 在 `contracts/<service>-api.yaml` 的 `gaps` 或 changelog 里登记变更点。

### 3.3 补丁版本（patch bump）

仅用于**文档/注释修订、错误描述补充**等不影响行为面的改动，`X.Y.Z` 的 Z 递增。

## 4. 废弃与观察期（FR-22）

- 端点或字段可用 `deprecated: true` + `deprecated_since: "<version>"` 标记废弃。
- 废弃后**至少观察 2 个 minor 版本**方可移除（`tools/contract/deprecation_check.py` 的 `bump_minor(version, minors=2)` 计算最早可移除版本）。
- 例：契约 `1.0.0` 里废弃的端点，最早可在 `1.2.0` 移除；`1.2.0` 移除属兼容变更（`removed_interaction_deprecated`）。
- 已知实例：`document-parser.yaml` 的 `delete_document_vectors_legacy`（`POST /vectors/documents/delete`，deprecated since `1.0.0`），最早 `1.2.0` 可移除。

## 5. 版本升级流程（执行顺序）

1. **改契约**：在 `contracts/<service>-api.yaml` 增删改 interaction，标注 `deprecated` / `deprecated_since`。
2. **跑 diff**：`python3 tools/contract/diff.py --service <svc>`，看分类（兼容/破坏性）。
3. **跑观察期**：`python3 tools/contract/deprecation_check.py --service <svc>`，确认移除项已过观察期。
4. **改契约版本号**：顶层 `version` 按 §3 幅度规则 bump。
5. **改实现**：路由/模型/错误码随契约调整（FR-16 实现必须满足契约）。
6. **重新生成并校验 OpenAPI**：`python3 tools/openapi/generate.py --all --check` + `python3 tools/openapi/validate.py --all`。
7. **CI 阻断**：以上步骤任一失败即阻断 PR（T048 装配）。

## 6. 迁移到 `/v1/` 前缀（FR-27, QF-264）

- **目标**：`services/*/app/api/routes/` 下的业务路由统一挂 `/v1` 前缀（成为 `/api/v1/...`），旧 `/api/...` 路径保留并 301 重定向到新路径（T045）。
- **消费方影响**：`apps/admin-web` / `apps/user-web` / `deployment` 探针的 base url 已含 `/api`，迁移后请求落到 `/api/v1/...`；旧路径由服务端重定向兜底，消费方无需在迁移窗口内改动。
- **例外**：`/askai-api` legacy 前缀、跨服务回调 URL（document-parser 的 `{base_url}/api/...`）暂不纳入 `/v1` 迁移，另行登记。

## 7. 当前版本清单

| 服务 | 契约版本（`contracts/`） | `pyproject.toml` | 主版本前缀 |
|---|---|---|---|
| `admin-api` | `1.0.0` | `0.2.5` | `/api/v1/`（迁移中，见 §6） |
| `chat-api` | `1.0.0` | `0.2.5` | `/api/v1/`（迁移中，见 §6） |
| `document-parser` | `1.0.0` | 未设置 `version`（待补） | `/api/v1/`（迁移中，见 §6） |

> 注：契约版本（对外 API 语义）与 `pyproject.toml` 服务发布版本（内部制品版本）是**两套独立版本号**，不要混淆。后者不随 minor bump 自动变化。

## 8. 待办与已知不一致

- `services/document-parser/pyproject.toml` 版本字段未统一（登记待补）。
- chat-api 大量 operation 未设置 `tags`（OpenAPI lint 提示项，168 条，不阻断；见 tasks.md T041）。
- `/askai-api` legacy 前缀与跨服务回调 URL 的 `/v1` 迁移未纳入本轮（§6 例外）。
