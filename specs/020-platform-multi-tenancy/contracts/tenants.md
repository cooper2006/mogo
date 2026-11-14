# Contract: 平台租户管理 API（020）

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

全部端点前缀 `/api/platform`，均要求平台管理员身份（专用保留租户标识）。租户内业务接口一律拒绝该标识。

---

## 1. 数据契约

### 1.1 `tenants` 集合

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | string | uuid4 hex |
| `tenant_id` | string | 租户标识，唯一索引 |
| `name` | string | 企业名称 |
| `status` | enum | `active` \| `disabled` \| `archived` \| `purged` |
| `edition` | string | `community` \| `enterprise` |
| `admin_username` | string | 租户内管理员账号名（供重置密码） |
| `member_limit` | int? | `null` = 不限 |
| `created_by` | string | `platform-admin` \| `setup-wizard` \| `migration` |
| `created_at` | datetime | |
| `updated_at` | datetime | |
| `archived_at` | datetime? | |
| `archive_reason` | string | |
| `purged_at` | datetime? | 墓碑记录；满 1 个月自动删除 |

索引：

```
{tenant_id: 1}                    unique
{status: 1, created_at: -1}
```

### 1.2 配额策略新增字段

| 集合 | 新增字段 | 默认 | 适用路径 |
|---|---|---|---|
| `org_quota_policies` | `unlimited: bool` | `true` | 企业空间 |
| `organizations` | `points_unlimited: bool` | `true` | 个人 / 社区空间 |

额度查询响应新增 `unlimited: bool`；`unlimited=true` 时 `remainingPoints` 返回 `-1`，**前端须依 `unlimited` 渲染"不限额"，不得对 `-1` 做算术**。

---

## 2. 引导流程（系统级，非平台前缀）

### `GET /api/setup/status`

返回引导状态与服务健康。

```jsonc
{
  "completed": false,          // 平台超管是否已创建
  "orgName": "",
  "tenantId": "",
  "initializedAt": "",
  "ready": true,               // 仅由核心服务决定
  "platformAdminMissing": true,// 存量升级未配置凭据时为 true（告警）
  "services": [
    { "key": "mongo", "label": "MongoDB", "ok": true, "message": "已就绪", "core": true },
    { "key": "weaviate", "label": "Weaviate", "ok": false, "message": "...", "core": false }
  ],
  "urls": { "userWeb": "", "adminWeb": "", "desktopService": "", "agentWebSocket": "" }
}
```

- `core: true` 仅 MongoDB；其 `ok=false` 阻止继续
- 其余服务 `ok=false` 仅告警

### `POST /api/setup/platform-admin`

创建平台超级管理员。仅当尚不存在时可用（已存在返回 409）。

```jsonc
// request
{ "username": "platform", "password": "...", "displayName": "平台管理员" }

// response
{ "completed": true, "tenantId": "__platform__", "username": "platform" }
```

---

## 3. 租户管理

### `POST /api/platform/tenants`

创建租户。

```jsonc
// request —— 仅三项必填
{
  "orgName": "示例科技有限公司",
  "adminUsername": "admin",
  "adminPassword": "...",
  // 以下全部可选
  "adminDisplayName": "系统管理员",
  "employee": { "username": "user01", "password": "...", "name": "张三" },
  "model": { "providerId": "", "displayName": "", "modelName": "", "baseUrl": "", "apiVersion": "", "apiKey": "", "capability": "chat" },
  "additionalModels": [],
  "externalSearch": null,
  "quota": null            // null = 不限额
}

// response —— snake_case（ProvisionResult 未配 alias，序列化即蛇形）
{ "tenant_id": "acme-9f3c...", "org_name": "示例科技有限公司", "model_instance_id": null, "additional_model_instance_ids": [] }
```

**契约要点**：`model` / `additionalModels` / `externalSearch` / `quota` / `employee` 全部可省略；省略时跳过对应配置且不校验其连通性。创建过程**不做任何服务就绪校验**。

**字段命名边界**（易错，勿再混淆）：请求体与列表/详情视图一律 **camelCase**；仅本端点响应因直接返回 `ProvisionResult` 数据类（未配 alias）而为 **snake_case**。前端 `apps/admin-web/src/api/platform.ts` 的 `TenantCreateResult` 已按 snake_case 声明，两侧一致。

### `GET /api/platform/tenants`

查询参数：`page`、`pageSize`、`keyword`、`status`。

返回**仅生命周期字段**，`members`/`usage`/`knowledgeCount` 等业务指标一律不返回。

```jsonc
{
  "items": [
    { "tenantId": "...", "name": "...", "status": "active", "edition": "community",
      "adminUsername": "admin", "memberLimit": null, "createdAt": "...", "createdBy": "platform-admin" }
  ],
  "total": 12
}
```

### `GET /api/platform/tenants/{tenant_id}`

同上字段，附带 `archivedAt` / `archiveReason` / `purgedAt`。

### `PATCH /api/platform/tenants/{tenant_id}`

可改：`name`、`status`（`active` ↔ `disabled`）、`memberLimit`。

#### 生效语义（易错：不写 `organizations`）

`memberLimit` 只写 `tenants.member_limit`（平台侧记录），**不会**同步到库内 `organizations.user_limit`
（该字段是版本默认，由 edition 决定）。成员上限的**最终取值**由
`app.core.product_edition.resolve_member_limit(tenant_id)` 解析：

```
organizations 是 community  →  无限（community 版为无限成员版本）
tenants.member_limit is None  →  回退 organizations.user_limit（版本默认）
否则                          →  取 tenants.member_limit（平台显式设置优先）
非法值（非数字）              → 告警后回退版本默认
```

该解析函数是**唯一**取值入口，三处消费方必须都走它：

| 消费方 | 位置 | 用途 |
|---|---|---|
| 容量闸门 | `product_edition.assert_member_capacity` | `POST /api/users`、邀请接受创建成员前拦截（403） |
| 租户概览 | `routes/dashboard.py` → `userLimit` | 仪表盘展示 |
| 组织概览 | `routes/organizations.py` → `userLimit` | 组织设置展示 |

`tenants` 行缺失（存量未迁移部署）时回退版本默认，**不得**因缺行锁死成员创建。

清除上限用 `"memberLimit": null`（或字符串 `"null"`），语义为「回退版本默认」，
**不等于**「无限」——若该版本默认本身有限，清除后仍然受限。

#### community 租户：写入侧拒绝，不静默忽略

community 版的 `user_limit` 为 `None`，含义是**按版本无限**，而不是「一个可以被平台覆盖的默认值」。
因此对 community 租户设置 `memberLimit`（非 null）会**在写入侧**直接失败：

```jsonc
// PATCH /api/platform/tenants/{tenant_id}   { "memberLimit": 3 }
// 409
{ "detail": "community 版为无限成员版本，不支持设置成员上限" }
```

**为什么是拒绝而不是读取侧忽略**：设了上限却被忽略，正是本项目刚修好的那类缺陷的形态——
「写入了、审计了、列表里显示了，但语义没人认账」。拒绝让调用方当场知道不该设。

配套的两半都要在：

- **写入侧** `product_edition.assert_member_limit_settable`（由 `tenant_lifecycle.update_tenant` 调用）→ 409；
- **读取侧** `resolve_member_limit` 对 community 短路 → 忽略**存量** override。

只加守卫会让守卫出现前写下的旧数据继续与版本语义矛盾；只改读取侧就是上面说的静默忽略。

清除上限（`"null"`）**始终允许**——它是回到版本默认，而 community 的默认本就是无限。

### `POST /api/platform/tenants/{tenant_id}/admin/reset-password`

```jsonc
// request
{ "newPassword": "..." }
// response
{ "success": true }
```

重置后**不强制**该管理员首次登录改密。

### `DELETE /api/platform/tenants/{tenant_id}`

软归档。

```jsonc
// request（可选）
{ "reason": "客户合同终止" }
// response
{ "status": "archived", "archivedAt": "..." }
```

副作用：同步置 `organizations` / `org_quota_policies` 为 `disabled`；该租户所有账号登录被拒。

### `POST /api/platform/tenants/{tenant_id}/restore`

恢复。仅 `archived` 可执行。恢复 `organizations` / `org_quota_policies` 为 `active`。

### `POST /api/platform/tenants/{tenant_id}/purge`

彻底清理。**仅 `archived` 可执行**（未归档返回 409）。

```jsonc
// request —— 二次确认
{ "confirmName": "示例科技有限公司" }
// response
{ "taskId": "...", "status": "running" }
```

`confirmName` 必须与该租户 `name` 完全一致，否则 400。**无需第二人审批**。

### `GET /api/platform/tenants/{tenant_id}/purge-status`

```jsonc
{ "taskId": "...", "status": "running", "progress": { "mongo": "done", "vectors": "running", "files": "pending" }, "error": "" }
```

失败时 `status = "failed"`，租户保持 `archived` 并保留 `error`。

### `GET /api/platform/system/health`

服务健康只读展示，结构同 `/api/setup/status` 的 `services`。

---

## 4. 登录契约变更

### `POST /api/auth/login`

```jsonc
// request
{ "username": "admin", "password": "...", "tenantId": "acme-9f3c..." }  // tenantId 可选
```

- 携带 `tenantId` → 直接校验该租户
- 未携带且账号唯一 → 直接进入
- 未携带且账号属于多个租户 → 返回 `candidates` + `challengeToken`，前端选租户后调 `/login/select-tenant`
- **移除**：原"用引导状态中的租户标识兜底"行为
- 租户 `status != active` → 403

---

## 5. 约定与边界

| 约定 | 值 |
|---|---|
| 平台管理员保留标识 | `__platform__` |
| 归档租户登录 | 禁止 |
| 归档租户计入授权数 | 否 |
| 墓碑记录保留期 | 1 个月 |
| 平台管理员数量 | 1 |
| 配额默认值 | 不限额 |
| 彻底清理审批 | 无需（单人 + 名称确认） |
