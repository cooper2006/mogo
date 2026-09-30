# 平台化多租户改造方案 v4

> 状态：**15 项决策已全部确认**，待开始实施。本文只包含设计，未改动任何代码。

## 0. 决策记录

| # | 议题 | 决策 |
| - | ---- | ---- |
| 1 | 平台超管形态 | 复用 `admin_accounts`，`main_id` 用保留值 `__platform__` |
| 2 | 租户主表 | **新增 `tenants` 集合**（不复用 `organizations`） |
| 3 | 删除租户 | **软归档**，且**允许恢复**（`archived → active`） |
| 4 | 配额默认值 | **不限额**（新租户默认不限额） |
| 5 | 平台超管初始化 | **首次启动向导为主** + **环境变量预置为辅**（headless / 存量部署补建） |
| 6 | 既有 `bootstrap_admin_*` 命名 | **重命名为 `tenant_bootstrap_admin_*`** |
| 7 | 平台超管数据权限 | **仅管理租户生命周期**，不查看租户内业务数据；业务数据由租户管理员查看 |
| 8 | Community edition 的 personal 分支 | **也需要"不限额"** |
| 9 | 初始化简化与创建租户向导的关系 | **合并为同一个租户创建表单**（§2.3） |
| 10 | 部署检测与创建超级管理员 | **合并为"平台引导向导"**；租户创建表单**独立**出来（§2.1） |
| 11 | 阶段一是否顺带创建第一个租户 | **不创建**，保持两段分离，用控制台空状态引导替代 |
| 12 | `/setup` 在已配置 `platform_admin_password` 时 | **保留但降级为快捷入口**；未配置平台超管时作为唯一引导入口 |
| 13 | 归档租户的 `admin_username` 能否登录 | **禁止** |
| 14 | 平台超管重置租户管理员密码后是否强制改密 | **不强制** |
| 15 | 归档数据的保留与清理 | 租户管理中**同时提供"归档"与"彻底清理"（物理删）** |
| 16 | 彻底清理是否需要二次审批 | **不需要**。平台超管权限本身即门禁，单人 + 输入企业名确认即可 |
| 17 | `tenants.purged` 墓碑记录保留时长 | **1 个月**，到期由清理任务删除 |
| 18 | 归档租户是否计入授权 / 许可配额 | **不计入** |
| 19 | 平台超管账号数量 | **仅一个**（环境变量预置，不支持多个） |

---

## 1. 现状结论

数据层与认证层已具备多租户能力，唯一缺口是"租户供给"。

| 层 | 状态 | 依据 |
| - | ---- | ---- |
| 数据层 | 已就绪 | 全部集合带 `main_id`，复合索引齐全；admin-api 与 chat-api 双端隔离 |
| 认证层 | 已就绪 | `POST /login` 接受 `mainId`；不带时跨租户查账号，命中多个走 challenge → `POST /login/select-tenant` |
| 供给层 | **缺口** | `system_bootstrap` 为 `_id: "singleton"`；`main_id` 仅在 `setup.py::_next_main_id()` 一处生成；无开租户接口 |

当前实际语义：**一套部署 = 一个企业**。

---

## 2. 目标形态

### 2.1 两段式流程（决策 10、11）

```
阶段一：平台引导（一次性，系统级）
  /setup
    ├─ 步骤 1  部署检测（MongoDB 必绿；其余 5 项仅告警，可继续）
    └─ 步骤 2  创建平台超级管理员（main_id = __platform__）
          └─► 完成 → 去登录（此时还没有任何租户）

阶段二：租户供给（可重复，平台控制台）
  平台超管登录
    └─► 控制台空状态引导「还没有租户，立即创建」
          └─► /platform/tenants/new ──► TenantCreateForm ──► provision_tenant()
                                                              └─► 租户 + 租户内管理员
```

**关键点**：`provision_tenant()` 只有阶段二**一个调用方**，`TenantCreateForm` 也只有一份。

### 2.2 为什么这样切更好

1. **部署检测的门禁终于自洽**。创建平台超管只需 MongoDB 可写，所以"部署检测 → 创建超管"放在同一流程里，门禁可以合理地只卡 MongoDB。若部署检测卡在租户创建之前则逻辑不成立——Weaviate 挂了不该阻止新建一个企业。
2. **租户创建表单只剩一份**，不再有"首次引导也建租户"的第二条路径。
3. **首次启动极简**：阶段一只填 1 个账号，完全不触碰 LLM / 外部搜索 / 配额等外部依赖，首次启动成功率大幅提升。
4. **职责边界最干净**：系统引导（部署健康 + 平台超管）与租户供给（建企业）彻底分离。

### 2.3 初始化简化 = 租户创建表单的字段设计（决策 9）

现在 `/setup/initialize` 在建租户前会跑 `_deployment_services()`，要求 6 个服务全绿否则 503。若把这段带进 `provision_tenant()`，**平台超管每创建一个租户都要全平台服务全绿**——显然不成立。

部署检测必须从供给链路剥离（归入 §2.1 阶段一）。剥离后，"初始化简化"剩下的工作（LLM / 外部搜索 / 配额 / 初始员工改为可选）**本质上就是租户创建表单的字段设计**，与平台侧创建租户本是同一件事，分成两个 Phase 等于同一份表单做两遍。

| 部分 | 归属 |
| - | ---- |
| 企业名 + 管理员账号 + 密码（必填） | `TenantCreateForm.vue` |
| 员工账号 / LLM / 外部搜索 / 配额（折叠可选） | `TenantCreateForm.vue` |
| 部署检测 | 阶段一引导页（非阻塞）+ 平台侧系统健康页（§8） |
| singleton 一次性门禁 | 阶段一：是否已创建平台超管 |
| 完成页（租户 ID + 访问地址） | 租户创建成功后展示 |

---

## 3. 数据模型：新增 `tenants` 集合

### 3.1 Schema

```jsonc
{
  "_id": "uuid4-hex",
  "main_id": "acme-9f3c...",        // 唯一索引
  "name": "示例科技有限公司",
  "status": "active",               // active | disabled | archived | purged
  "edition": "community",
  "admin_username": "admin",        // 租户内管理员账号，供平台侧重置密码
  "member_limit": null,             // null = 不限
  "created_by": "platform-admin",   // 或 "setup-wizard" / "migration"
  "created_at": "...",
  "updated_at": "...",
  "archived_at": null,
  "archive_reason": "",
  "purged_at": null                 // 彻底清理后仅保留这条墓碑记录
}
```

### 3.2 与 `organizations` 的关系

`organizations` 保持不变，按 `{"main_id": ...}` 一条，承载租户内业务档案。

| 集合 | 层次 | 职责 |
| - | ---- | ---- |
| `tenants`（新增） | 平台层 | 生命周期：存在性、启停、归档、清理、创建来源 |
| `organizations`（既有） | 租户内 | 组织档案与业务属性 |

### 3.3 索引

```python
await db["tenants"].create_index([("main_id", 1)], unique=True, name="tenant_main_id_unique")
await db["tenants"].create_index([("status", 1), ("created_at", -1)], name="tenant_status_created")
```

### 3.4 ⚠️ 存量迁移（必做）

既有部署已通过 setup 向导创建租户，但**没有 `tenants` 记录**。启动时幂等回填，参照 `directory_bootstrap.py` 的遍历模式：

```python
tenant_ids = await db.admin_accounts.distinct(
    "main_id", {"main_id": {"$nin": [None, "", "default", "__platform__"]}}
)
for main_id in tenant_ids:
    await ensure_tenant_record(main_id, created_by="migration")
```

企业名取 `system_bootstrap.org_name` 或 `organizations.org_name`；`admin_username` 取 `system_bootstrap.admin_username`。

---

## 4. 核心改造：`provision_tenant()`

### 4.1 抽取边界

现状：`services/admin-api/app/api/routes/setup.py::setup_initialize()` 第 343–463 行内联。抽出为 `app/services/tenant_provisioning.py`：

```python
async def provision_tenant(
    *,
    org_name: str,
    admin_username: str,
    admin_password: str,
    admin_display_name: str = "系统管理员",
    employee: EmployeeSpec | None = None,         # 可选
    model: dict | None = None,                    # 可选（LLM）
    additional_models: list[dict] | None = None,  # 可选（embedding/rerank/vision/image）
    external_search: dict | None = None,          # 可选
    quota: QuotaSpec | None = None,               # 可选，缺省 = 不限额
    created_by: str,
) -> ProvisionResult:
```

### 4.2 内部步骤

1. `_next_main_id(org_name)`
2. **写 `tenants` 记录**（新增）
3. `ensure_group_exists(system_admin)`
4. `ensure_bootstrap_account()` 建租户内管理员
5. `ensure_root_department()`
6. 建初始员工（可选）
7. upsert `organizations`（含 `points_unlimited`，见 §6）
8. 写 `end_user_org_relations`
9. `PositionRoleRepository`：`ensure_full_access_role` → `assign_role` → `complete_migration`
10. 配置配额（可选，缺省 `unlimited = True`）
11. `create_setup_model()`（可选）
12. `configure_setup_knowledge_models()`（可选）
13. `save_setup_search()`（可选）

### 4.3 不含部署检测

`provision_tenant()` **不做任何服务就绪校验**（§8），仅依赖 MongoDB 可写。

### 4.4 与 `system_bootstrap` 的关系

`provision_tenant()` 不碰 `system_bootstrap`。该 singleton 仅表示阶段一是否完成，阶段二不依赖它。

---

## 5. 平台超管：`__platform__`

### 5.1 既有配置改名（决策 6）

`app/core/config.py` 中 6 项改名：

```
bootstrap_admin_enabled        → tenant_bootstrap_admin_enabled
bootstrap_admin_username       → tenant_bootstrap_admin_username
bootstrap_admin_password       → tenant_bootstrap_admin_password
bootstrap_admin_display_name   → tenant_bootstrap_admin_display_name
bootstrap_admin_role_name      → tenant_bootstrap_admin_role_name
bootstrap_admin_org_name       → tenant_bootstrap_admin_org_name
```

环境变量前缀为 `ASKAI_ADMIN_`，外部形态为 `ASKAI_ADMIN_TENANT_BOOTSTRAP_ADMIN_*`。

**影响面（已核对，仅 4 个文件）**：

| 文件 | 位置 |
| - | ---- |
| `services/admin-api/app/core/config.py` | 16–21 行 |
| `services/admin-api/app/services/admin_bootstrap.py` | 17、20、30–33 行 |
| `services/admin-api/.env.example` | 8–14 行 |
| `docker-compose.yml` | 246 行 |
| `deploy/production/docker-compose.portainer.yml.tpl` | 222 行 |

> `bootstrap_admin_role_name` 当前默认值是"平台超级管理员"，实为**租户内**管理员角色，改名同时改为"租户管理员"以消除误导。`docs/WORK_LOG.md` 的历史记录不动。

### 5.2 创建方式（决策 5、12）

| 途径 | 适用场景 | 触发 |
| - | ---- | ---- |
| **首次启动向导**（主） | 全新部署 | `/setup` 阶段一步骤 2 |
| **环境变量预置**（辅） | 无界面 / 自动化部署；**存量部署补建** | `platform_admin_password` 非空时启动时 ensure |

```python
platform_admin_username: str = "platform"
platform_admin_password: str = ""      # 为空则不自动创建
platform_admin_display_name: str = "平台管理员"
```

`/setup` 的表现（决策 12）：**已存在平台超管时降级为快捷入口**（可再次进入但不是唯一入口）；**不存在时作为唯一引导入口**（强制定向）。

**账号数量（决策 19）：仅一个**。不提供平台超管的多账号管理，`ensure_bootstrap_account()` 按用户名幂等 ensure，重复启动不会重复创建。若将来需要多个，再引入账号组机制。

### 5.3 ⚠️ 存量部署必须靠环境变量补建（关键）

已有部署的 `system_bootstrap.completed` 已是 `True`，改造后 `/setup` 不再是唯一入口，它们拿不到平台超管。

因此环境变量途径不是可选优化，而是**存量升级的必由之路**：

- 升级后首次启动前，必须配置 `ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD`
- 启动时 `bootstrap_platform_admin()` 自动补建 `__platform__` 账号
- 若未配置，应在启动日志与 `/api/setup/status` 中给出明确告警

### 5.4 启动 ensure

参照 `admin_bootstrap.py::bootstrap_admin_user()`：

```python
async def bootstrap_platform_admin() -> None:
    if not settings.platform_admin_password:
        return
    await ensure_group_exists("平台管理员", "platform_admin", "__platform__", ...)
    await ensure_bootstrap_account(
        main_id=PLATFORM_MAIN_ID,          # "__platform__"
        username=settings.platform_admin_username,
        password=settings.platform_admin_password,
        role_name="平台超级管理员",
        org_name="平台",
        group_code="platform_admin",
    )
```

在 `main.py` 启动钩子（现第 49 行 `bootstrap_admin_user()` 附近）追加调用。

### 5.5 `system_bootstrap` 语义变更

从"首个租户是否已创建"变为"**平台超管是否已创建**"。连带影响：

- `setup.py::_ensure_setup_open()`：条件改为 `admin_accounts` 中是否存在 `__platform__` 账号（或直接复用 `completed`）
- **`auth.py:228` 的兜底必须移除**：登录不带 `mainId` 时现会用 `setup_state.main_id` 作为默认租户，多租户下这是错误行为（会把人塞进首次创建的那个租户）。改为一律走跨租户搜索 + challenge 选租户（该机制已存在）。

### 5.6 鉴权依赖

```python
PLATFORM_MAIN_ID = "__platform__"

async def get_current_platform_admin(user=Depends(get_current_admin_user)) -> dict:
    if str(user.get("main_id")) != PLATFORM_MAIN_ID:
        raise HTTPException(403, "platform admin required")
    return user
```

**反向守卫**：业务路由须拒绝 `main_id == "__platform__"`，否则带该 main_id 调业务接口会因兜底逻辑落到错误租户。

### 5.7 数据权限边界（决策 7）

平台超管**只能**访问 `/api/platform/*`。租户列表只返回生命周期字段（`name / main_id / status / edition / created_at / admin_username / member_limit`），**不含成员数、用量、知识库数等业务指标**。业务数据由租户管理员在自己的控制台查看。

### 5.8 ⚠️ 必须处理的坑

`services/admin-api/app/services/directory_bootstrap.py:15` 遍历 `admin_accounts.distinct("main_id")`，会把 `__platform__` 当租户建岗位角色。现有过滤 `{"$nin": [None, "", "default"]}` **需加入 `"__platform__"`**。同类过滤见 `employee_tenant_identity.py:37,40`。

### 5.9 登录

`auth.py` 已支持 `mainId`，平台登录入口显式提交 `mainId: "__platform__"` 即可命中现有分支。前端登录页增加"平台管理员"入口。

---

## 6. 配额：默认不限额（含 Community edition）

### 6.1 问题

`quota_policy.py::assert_quota_available()`：

```python
if summary.get("status") != "active":
    raise QuotaExceededError(...)
if int(summary.get("remainingPoints") or 0) <= 0:
    raise QuotaExceededError(...)
```

而 `ensure_org_quota_policy()` / `ensure_default_user_policy()` 惰性默认为 `total_tokens = 0`、`quota_tokens = 0` —— **留空会让用户一登录就被拦截**。这就是必须引入 `unlimited` 而非"给个大数字"的原因。

### 6.2 Enterprise 分支

`org_quota_policies` 增加字段：

```python
"unlimited": bool   # 新建租户默认 True
```

`get_quota_summary()` 输出增加 `"unlimited"`；`unlimited=True` 时 `remainingPoints` 返回 `-1`（前端据 flag 渲染"不限额"，**不要拿 -1 做算术**）。

```python
if summary.get("status") != "active" and not summary.get("unlimited"):
    raise QuotaExceededError(...)
if not summary.get("unlimited") and int(summary.get("remainingPoints") or 0) <= 0:
    raise QuotaExceededError(...)
```

### 6.3 Community / personal 分支（决策 8）

该分支走 `get_quota_summary()` 的 `space_type != "enterprise"` 路径，读 `organizations.total_points / used_points`，与 `org_quota_policies` 无关，需单独处理：

- `organizations` 增加 `points_unlimited: bool`，新建租户默认 `True`
- `community_organization_fields()` 增加该字段
- personal 分支同样返回 `unlimited: true` + `remainingPoints: -1`
- `assert_quota_available()` 对 personal 分支也按 `unlimited` 短路

### 6.4 配套改动

- `configure_setup_quotas()` 的 `total_tokens > 0` / `default_user_tokens > 0` 强校验放宽：不传则写 `unlimited = True`
- `traffic_allocations.py` 的 `OrgQuotaPayload` / `DefaultPolicyPayload` 增加 `unlimited` 字段
- 前端配额展示与编辑支持"不限额"

---

## 7. 租户生命周期：归档、恢复、彻底清理

### 7.1 归档

`DELETE /api/platform/tenants/{main_id}`：
- `tenants.status = "archived"`，写 `archived_at` / `archive_reason`
- 同步将 `organizations`、`org_quota_policies` 置为 `disabled`
- **归档租户的 `admin_username` 禁止登录**（决策 13）：`auth.py` 在登录校验时查 `tenants.status`，非 `active` 一律 403

### 7.2 恢复

`POST /api/platform/tenants/{main_id}/restore`：`status → active`，清空 `archived_at`，恢复 `organizations` / `org_quota_policies` 的 `active`。

### 7.3 彻底清理（物理删，决策 15）

**前置约束**：

- **必须先归档再清理** —— 仅 `status == archived` 的租户允许 purge，杜绝误删活跃租户
- **无需二次审批**（决策 16）—— 平台超管权限本身即门禁；前端只需单人手动输入企业名称（或 `main_id`）确认。不引入第二人审批流。
- **不可恢复** —— UI 明确警示；执行前写入 `system_audit`

**清理范围（三层，缺一不可）**：

| 层 | 内容 | 说明 |
| - | ---- | ---- |
| MongoDB | 所有带 `main_id` 的集合 | ⚠️ 现有 `setup_cleanup.py::SETUP_SCOPED_COLLECTIONS` **只有 17 个**，而两个服务共有 **72 个集合常量**，远超该清单。必须重新盘点生成完整的 `TENANT_SCOPED_COLLECTIONS`（建议用脚本扫描 `db.list_collection_names()` 抽样含 `main_id` 的集合，人工确认后固化） |
| Weaviate | 向量数据 | chat-api 的知识检索按 `mainId` 过滤（`knowledge/retrieval/retrieval_client.py:45`），只删 Mongo 会留下向量残留在库中，必须一并清除 |
| 文件存储 | 磁盘文件 | `knowledge_local_storage_dir` / `admin_static_dir` 下按 `main_id` 前缀的目录（如 `admin-avatars/{main_id}`、知识库文档目录） |

**执行方式**：

- 建议做成异步任务并回报进度（大租户删除可能耗时较久），前端轮询状态
- 全部成功后 `tenants.status = "purged"`，仅保留墓碑记录（含 `purged_at`），便于审计追溯
- 任一步失败应中止并保留 `archived` 状态，记录失败原因

### 7.4 墓碑记录保留 1 个月（决策 17）

- purge 成功后 `tenants` 中仅剩墓碑记录（`status = "purged"` + `purged_at`）
- **保留 1 个月**，到期由定时清理任务物理删除该条记录
- 清理任务可复用 admin-api 既有的 `scheduled_tasks` 机制，或随 `bootstrap_directory()` 一类启动钩子做惰性清理
- 墓碑期间该 `main_id` 不可复用（创建租户时 `_next_main_id()` 本就随机生成，不会撞）

### 7.5 其他配套

- 各业务查询的租户枚举（现为 `distinct("main_id")`，不过滤状态）需改为先取 `tenants` 中 `status == "active"` 的 main_id 列表 —— 涉及 `directory_bootstrap.py:15` 与 `employee_tenant_identity.py:37,40`
- `setup_cleanup.py::cleanup_failed_setup()` **保留原职责**：仅用于 provision 失败回滚，与上述 purge 是两套逻辑；需收紧 main_id 格式校验，并改为按"本次实际写入的集合"回滚

### 7.6 授权 / 许可计数（决策 18）

**归档租户不计入授权配额**。凡按租户数计量的地方，计数条件统一为 `status == "active"`（`purged` 墓碑同样不计入）。

> 注意：当前代码中尚无按租户数授权的实现（`product_edition.py` 只做单租户的 `member_limit`）。因此本条是**前瞻约定**，需在将来引入租户数授权时落地；建议现在就在 `tenants` 查询处统一用 `count_documents({"status": "active"})` 的封装，避免届时遗漏。

### 7.7 重置密码（决策 14）

`POST /api/platform/tenants/{main_id}/admin/reset-password`：重置后**不强制**租户管理员首次登录改密。

---

## 8. 部署检测的归处

部署检测**只服务于阶段一**，与租户供给完全无关：

- **阶段一引导页**：作为步骤 1。门禁收紧为**仅 MongoDB 必绿**（创建超管只依赖它写 `admin_accounts`），其余 5 项（Redis / 存储 / Chat API / 文档处理 / Weaviate）降级为告警，允许带警告继续；`503` 硬拦截仅在 mongo 不可用时抛出。
- **平台侧系统健康页**：新增 `views/platform/SystemHealthPage.vue`，复用 `GET /api/setup/status` 的服务探针（该端点本就不需要 `_ensure_setup_open`），**纯展示、不阻塞任何写操作**。
- **`provision_tenant()` 内不做任何服务就绪校验**。

---

## 9. API 设计

前缀 `/api/platform`，全部挂 `get_current_platform_admin` 依赖。

```
POST   /api/platform/tenants                                  开租户
GET    /api/platform/tenants                                  列表（分页 / 搜索 / 状态筛选）
GET    /api/platform/tenants/{main_id}                        详情（仅生命周期字段）
PATCH  /api/platform/tenants/{main_id}                        改名 / 启停 / 成员上限
POST   /api/platform/tenants/{main_id}/admin/reset-password   重置租户内管理员密码（不强制改密）
DELETE /api/platform/tenants/{main_id}                        软归档
POST   /api/platform/tenants/{main_id}/restore                恢复
POST   /api/platform/tenants/{main_id}/purge                  彻底清理（仅 archived 可执行）
GET    /api/platform/tenants/{main_id}/purge-status           清理进度
GET    /api/platform/system/health                            服务健康（只读）
```

---

## 10. 隔离加固：`or "default"` 兜底

admin-api 81 处 + chat-api 33 处，集中在 `knowledge_documents.py`(27)、`skills.py`(17)、`tools.py`(11)、`analytics.py`(5)、`hooks.py`(4)。

- **短期（必做）**：`deps.py::get_current_admin_user` 入口强校验 —— `main_id` 为空、等于 `default`、或等于 `__platform__` 时按路由类型分别拒绝，兜底永不触发
- **长期**：逐模块把 `or "default"` 改为显式必填参数

---

## 11. 前端

**阶段一：平台引导（改造 `views/auth/SetupPage.vue`）**

- 步骤从 6 步**缩减为 3 步**：部署检测 → 创建平台超级管理员 → 完成
- 删除原步骤 2/3/4/5（组织与账号、对话模型、可选模型、联网搜索）
- 部署检测：仅 MongoDB 必绿，其余告警可继续
- 完成页：不再展示"租户 ID + 访问地址"（此时无租户），改为引导登录并创建第一个租户
- 已存在平台超管时降级为快捷入口（决策 12）

**阶段二：租户供给（平台控制台）**

- **`components/platform/TenantCreateForm.vue`（新，核心）**：企业名 + 管理员账号 + 密码必填；员工账号 / LLM / 外部搜索 / 配额折叠为可选。**仅此一处**
- **`views/platform/TenantsPage.vue`**：租户列表 / 新建 / 详情 / 归档 / 恢复 / **彻底清理** / 重置密码
- **空状态引导（必做）**：阶段一完成后平台是空的（决策 11），控制台首页需有"还没有租户，立即创建"的强引导

**公共**

- **`views/platform/SystemHealthPage.vue`**：服务健康只读展示
- `router/routes.ts` 增加 `/platform` 路由组（现有路由只有 `public` 标记，无角色体系，平台页按 `mainId === '__platform__'` 控制显隐）
- 登录页增加"平台管理员"入口，提交 `mainId: "__platform__"`
- 配额展示支持"不限额"

---

## 12. 实施阶段

| 阶段 | 内容 | 依赖 |
| - | ---- | ---- |
| **1** | 抽 `provision_tenant()`，setup 路由改为调用它。纯重构，行为不变 | 无 |
| **2** | `TenantCreateForm` 字段简化（LLM / 搜索 / 配额 / 员工改可选）+ 部署检测移出供给链路 | 1 |
| **3** | 新增 `tenants` 集合 + 索引 + 存量回填迁移 | 1 |
| **4** | 既有 `bootstrap_admin_*` → `tenant_bootstrap_admin_*` 改名（4 个文件） | 无 |
| **5** | **平台引导向导改造**：`SetupPage` 改为"部署检测 → 创建平台超管 → 完成"（6 步 → 3 步）；部署门禁收紧为仅 mongo 必绿；`system_bootstrap` 语义改为"平台超管已创建"；移除 `auth.py:228` 的 setup_state 兜底 | 4 |
| **6** | 平台超管：`__platform__` + 环境变量补建（存量升级必配）+ 鉴权依赖 + 反向守卫 + `directory_bootstrap` / `employee_tenant_identity` 过滤 | 3、5 |
| **7** | 配额不限额：enterprise（`org_quota_policies.unlimited`）+ community personal（`organizations.points_unlimited`）+ 前端 | 1 |
| **8** | 租户管理 API + 平台前端页（`TenantCreateForm`、列表、空状态引导） | 6 |
| **9** | 归档 + 恢复 + 归档租户禁止登录 + 租户枚举排除非 active | 8 |
| **10** | **彻底清理（purge）**：盘点 `TENANT_SCOPED_COLLECTIONS` + Weaviate 向量 + 文件存储，异步任务与进度 | 9 |
| **11** | `deps` 入口 main_id 强校验 | 6 |

**原"阶段 0 初始化简化"已并入阶段 2**，不再作为独立前置。

---

## 13. 残余待确认项

**无。** 决策 1–19 已全部确认，可以进入实施。

实施前建议再确认两点执行层面的事：

1. **首个落地阶段**：建议从阶段 1（`provision_tenant()` 抽取，纯重构）与阶段 4（`bootstrap_admin_*` 改名，4 个文件）并行开始，两者互不依赖且风险最低。
2. **存量升级的发布说明**：决策 5 的存量补建依赖 `ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD`，必须在发布说明中作为**升级必读项**明确写出，否则存量部署升级后将无法进入平台控制台。
