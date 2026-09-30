# 020-platform-multi-tenancy SDD 规范一致性审计报告

> 审计日期：2026-09-30 · 审计人：DSH Agent
> 审计范围：`specs/020-platform-multi-tenancy/`（spec.md 275 行 / contracts/tenants.md 219 行）与已实现代码（`services/admin-api`、`services/chat-api`、`apps/admin-web`）
> 方法：全量代码通读 + 集合名交叉核对（脚本化差集） + 两个只读子代理并行深挖（隔离认证 / 清理完整性） + 关键结论运行复现
> **本次审计未修改任何源码或规格文件**，仅新增本报告。

---

## 0. 结论速览

`020` 的**主干实现是正确的**：租户标识隔离、平台管理员守卫、登录选租户、生命周期状态机、墓碑回收、额度不限额口径均已落地并有测试覆盖。但在**彻底清理（User Story 6）**这一条上有系统性缺口，且该缺口使 **SC-005 实际不成立**。

| 维度 | 结论 |
|---|---|
| 租户隔离 / 认证（FR-015~019、024、025） | ⚠️ admin-api 正确；**chat-api 未接租户状态**，员工账号绕过归档（违反 FR-024） |
| 生命周期状态机（FR-020~027） | ✅ 正确，边界完备（**但 §3 的并发窗口除外**） |
| 彻底清理（FR-028~034、SC-005） | ❌ **存在 6 项 HIGH 缺陷**：清理面少 27 个集合、失败仍写墓碑、执行时不复检状态、进度不可靠、头像永不删、向量静默失败 |
| 额度不限额（FR-035~037、P3） | ✅ 正确 |
| 存量升级 / 平台引导（FR-038~040） | ✅ 正确 |
| 契约一致性 | ⚠️ 2 处文档与实现不符（创建响应字段大小写、清理审计缺失） |
| plan.md 自我承诺兑现 | ⚠️ R1/R2/R4/R6 已兑现；**R7（清理面盘点）未兑现**；R3 事实上安全但为隐式保证；R5 数字未降但风险已由 R6 关闭（§11） |
| tasks.md 勾选真实性 | ❌ **T045、T051 勾选与实现不符**（实现者自述的验收标准未达成，§11.2） |
| quickstart.md 验收清单 | ❌ **9 项中 3 项当前必然失败**：归档后登录被拒、清理残留为 0、全部生命周期有审计（§11.3） |

**最关键的一条**：`services/admin-api/app/services/tenant_purge.py:319-323` 无条件把租户刷成 `purged`，使 FR-033「部分失败 MUST 中止并保留已归档状态」在代码层面不可能成立；且 `:106-108` 已算出 `ok`、已把**任务**标记为 `failed`，却唯独没把它写回**租户行**。

**本报告的独立佐证线（互相印证，非重复计数）**：① spec/contracts 契约比对（§1~§7）；② plan.md 自我承诺核对（§11）；③ tasks.md 勾选证伪（§11.2）；④ quickstart 验收清单可执行性判定（§11.3）；⑤ 索引元数据法复核集合清单（§11.1）。其中 §1.1 的 `org_units`/`page_collection_settings` 由 ① 与 ⑤ **两种独立方法**同时命中。

---

## 1. 清理面严重不全（FR-031 / SC-005）—— 🔴 HIGH

**规格要求**：FR-031「彻底清理 MUST 删除该租户的数据库记录、向量数据与磁盘文件」；SC-005「彻底清理执行后，该租户的数据库记录、向量数据、磁盘文件残留均为 0」。

**实现机制**：`tenant_purge.py:33-65` 的 `TENANT_SCOPED_COLLECTIONS`（31 项，按 `main_id` 删）+ `:68-78` 的 `TENANT_GOVERNANCE_COLLECTIONS`（9 项，按 `tenant_id` 删）。

### 1.1 admin-api 侧漏项 5 个（脚本化差集确认）

把 `services/admin-api/app` 全部 `*COLLECTION = "..."` 常量与两张清理名单做差集，未被任一名单覆盖且**确认为租户分区**的集合：

| 集合名 | 定义处 | 证据（带 main_id） |
|---|---|---|
| `org_units` | `services/admin-api/app/repositories/directory_repository.py:9` | `:26` `create_index([("main_id", 1), ("code", 1)], unique=True, name="dept_main_code_unique")` |
| `user_quota_overrides` | `services/admin-api/app/core/quota_policy.py:15` | `:150` `aggregate([{"$match": {"main_id": main_id, "user_id": user_id, ...` |
| `admin_presentation_settings` | `services/admin-api/app/repositories/presentation_settings_repository.py:9` | `:17` `find_one({"main_id": main_id})` |
| `page_collection_settings` | `services/admin-api/app/api/routes/page_collection.py:17` | `:106` `create_index([("main_id", 1), ("provider", 1)], unique=True)` |
| `organization_shortcut_schemes` | `services/admin-api/app/shortcut_settings/service.py:11` | `:16` `find_one({"main_id": main_id, "scheme_key": "default"})` |

**`org_units` 是最典型的漏项**——它是一次改名未同步：

- `tenant_purge.py:39` 清的是**已废名** `"departments"`；
- `services/admin-api/app/services/setup_cleanup.py:12` 的注释自己就写着：
  `# "departments" was renamed to "org_units" (directory_repository.DEPARTMENT_COLLECTION);`
  并且 `:18` 的 `SETUP_SCOPED_COLLECTIONS` 里同时列了 `"org_units"`。
- 这个重命名知识只被 `setup_cleanup.py` 吸收，**`tenant_purge.py` 没跟**。
- 全仓 `grep '"departments"'` 后确认：`dashboard.py:537` 与 `analytics.py:137/434` 的命中都是**响应字段名**，不是集合名。即 `"departments"` 作为集合已无任何写入方，是纯 dead name。

**后果**：清理后 `org_units` 残留违反 SC-005；且 `dept_main_code_unique(main_id, code)` 唯一索引会**阻塞新建同名 code 的租户**。`page_collection_settings` 同理（`(main_id, provider)` 唯一索引）。

### 1.2 chat-api 侧漏项 22 个（🔴 最严重）

`026` 的清理由 admin-api 单向执行，但**租户数据大量存在 chat-api 使用的集合里**，而 admin-api 的清理名单完全没有覆盖它们。

从 `services/chat-api/app/main.py` 的索引引导提取「建了 `main_id`/`tenant_id` 索引」的集合，与清理名单做差集：

**已覆盖（4 个）**：`end_users`、`external_tools`、`skill_packages`、`token_usage_logs`

**未覆盖（22 个）**：

```
chat_messages                  chat_sessions                desktop_projects
end_user_sessions              execution_logs               knowledge_resources
personal_knowledge_directories project_memories             resource_comment_reactions
resource_comments              resource_feedback_notifications
resource_grants                resource_reactions           site_profiles
skill_distribution_members     skill_distribution_releases  skill_distributions
skill_releases                 skill_share_deliveries       skill_shares
skill_update_notifications     user_skills
```

**证据链（复核过，非误报）**：

- `services/chat-api/app/main.py:242` `await db.chat_messages.create_index([("main_id", 1), ("user_id", 1), ("session_id", 1), ("seq", 1)])`
- `services/chat-api/app/main.py:241` `await db.chat_sessions.create_index([("main_id", 1), ("user_id", 1), ("updated_at", -1)])`
- 写入侧确实落 `main_id`：`services/chat-api/app/api/endpoints/sessions.py:495-498`
  `await db.chat_messages.insert_one({"session_id": session_id, "user_id": str(user_id), "main_id": resolve_main_id(main_id), ...})`
- `services/chat-api/app/api/endpoints/personal_knowledge.py:67` `"main_id": principal.main_id, "owner_user_id": principal.user_id, "deleted_at": None`
- **admin-api 自己就在按 `main_id` 读这些集合**：`services/admin-api/app/api/routes/analytics.py:505`
  `session_doc = await db.chat_sessions.find_one({"_id": session_oid, "main_id": own_main_id}) if session_oid else None`
  ——即 admin-api 明知这些集合是租户分区的，却不在清理名单里。
- 复核：`grep -c 'chat_messages\|chat_sessions' services/admin-api/app/services/tenant_purge.py` → **0**。

**后果**：清理后该租户的**全部聊天历史、消息、终端用户会话、个人知识库、技能分享记录、定时任务、项目记忆**原样保留，SC-005「残留为 0」直接不成立。这些集合还带着唯一索引（如 `skill_shares` 的 `(main_id, token_hash)`、`desktop_projects` 的 `(main_id, user_id, workspace_id)`），重建同名租户时会撞索引。

### 1.3 需明确决策的 2 个

| 集合 | 位置 | 说明 |
|---|---|---|
| `system_audit_logs` | `services/admin-api/app/system_audit/constants.py:1` | 按 `main_id` 存（`middleware.py:52-56`），但记的是**平台管理员对租户的操作**（平台侧溯源）。不清可能是有意的，但需在决策记录里写明，或在 SC-005 口径里显式豁免 |
| `hook_rules` | `services/admin-api/app/services/hooks_store.py:16`、`services/chat-api/app/dsh_runtime/hooks/store.py:30` | 文档带 `tenant_id`（`store.py:44`），`HOOK_RULES_COLLECTION` 确实被持久化（`services/admin-api/app/services/hooks_store.py:95` `await self._db[HOOK_RULES_COLLECTION].insert_one(...)`，`services/admin-api/app/api/routes/hooks.py:67` 传 `tenant_id=tenant_id`）。但清理名单按 `tenant_id` 删的那张表里没有它 |

**已核实为全局表、不应清理**：`admin_model_providers`（索引只有 code/status）、`admin_sessions`、`admin_users`、`system_bootstrap`、`tenants`（租户注册表，单独处理为墓碑）。

### 1.4 磁盘文件：知识库正确，头像永不删除（FR-031 / SC-005）—— 🔴 HIGH

**知识库目录（✅ 安全）**：
`tenant_purge.py:252` `knowledge_root = Path(settings.knowledge_local_storage_dir) / main_id`，与写入侧 `services/admin-api/app/api/routes/knowledge_documents.py:724` 的 `storage_key = f"{storage_prefix}/{main_id}/{document_id}/{original_filename}"` 一致，子目录首段确为 `main_id`。

⚠️ 但 `tenant_purge.py:243-246` 自述 `OSS-backed storage is left in place`——若租户用 OSS 存储（`services/admin-api/app/services/knowledge_storage.py:78` `OSSStorageAdapter`），对象存储里的文档**不删**。需与 FR-031 口径对齐（补删，或在规格里显式豁免）。

**头像目录（❌ 永不删除）**：
`tenant_purge.py:264` `if entry.name.startswith(f"{main_id}-") and entry.is_dir():`，注释 `:261-263` 断言 `Avatar directories are named {main_id}-{short_uuid}` —— **这个假设是错的**。

唯一写入方是 `services/admin-api/app/api/routes/auth.py:394`：
`relative_dir = f"admin-avatars/{_safe_path_part(main_id, 'default')}"`
而 `services/admin-api/app/api/routes/auth.py:92-94`：
```python
def _safe_path_part(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return normalized[:80] or fallback
```
→ 真实头像目录名 = **净化后的 main_id，没有尾随短 uuid**。因此 `"acme-xxxx".startswith("acme-xxxx-")` 恒为 False，`:265` 的 `shutil.rmtree(entry)` **永不执行**。

⚠️ **修法警告**：不能简单改成 `startswith(main_id)`（无 dash）——main_id 形如 `slug-hex`（`services/admin-api/app/services/setup_cleanup.py:35` `_MAIN_ID_SHAPE = re.compile(r"^[a-z0-9]+-[0-9a-f]{24}$")`），前缀匹配会跨租户误删（`acme` 吃掉 `acme-other`）。必须复用 `_safe_path_part(main_id)` 推导等价目录名。

### 1.5 向量删除静默失败（FR-031 / FR-033 / SC-005）—— 🔴 HIGH

`tenant_purge.py:230-236`：
```python
except Exception as exc:
    logger.warning(
        "purge %s: vector delete failed for document %s: %s",
        main_id, document_id, exc,
    )
```
只 warning，**不 raise、不 `errors.append`**。且 `:210-212` 的 `if not settings.document_processing_service_token:` 直接 `return`（默认值见 `services/admin-api/app/core/config.py:45` `document_processing_service_token: str = ""`）。

**后果**：默认配置下向量阶段**完全不执行却标记 `done`**；即使执行失败，`errors` 仍为空 → `ok=True` → `status="done"`、`progress.vectors="done"`、`error=""`，而向量数据原样留在 Weaviate。**直接违反 SC-005 与 FR-031，且连 FR-033 的「记录失败原因」都没做到。**

---

## 2. 部分失败仍写墓碑（FR-033 被反转）—— 🔴 HIGH

**规格要求**：FR-033「彻底清理部分失败 MUST 中止并保留已归档状态，记录失败原因」；契约 `specs/020-platform-multi-tenancy/contracts/tenants.md:184` 同款表述；故事验收 6「清理过程中任一步失败，When 中止，Then 租户保持已归档状态并记录失败原因」。

**实际行为**：`tenant_purge.py:282-323`

三阶段各自 `try/except`（`:285-291`、`:294-300`、`:303-309`），**无一处 `return`/`raise`**：
```python
except Exception as exc:
    logger.exception("purge %s: mongo phase failed", main_id)
    errors.append(f"mongo: {exc}")
    _task_store.mark(key, "mongo", "failed")     # ← 不 return，继续下一阶段
```
文件 docstring `:14-16` 自述 `Each phase is best-effort: a failure is logged into the task and the remaining phases still run`。

决定性代码 `:319-323`：
```python
db = get_db()
await db[TENANT_COLLECTION].update_one(
    {"main_id": main_id, "status": {"$ne": "purged"}},
    {"$set": {"status": "purged", "purged_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
)
```
**与 `ok` 无关，无条件执行**。

**决定性代码配对（`ok` 被算了，但没用在租户行上）**：
```python
:106    ok = not errors
:107    error_text = "; ".join(errors)
:108    _task_store.finish(key, ok, error_text)      # ← 任务记录正确变成 "failed"
...
:319-323 await db[TENANT_COLLECTION].update_one(     # ← 租户行无条件变 "purged"
             {"main_id": main_id, "status": {"$ne": "purged"}},
             {"$set": {"status": "purged", ...}},
         )
```
即：**失败状态只停留在内存字典里，从未写回租户行**。作者注释 `:316-318` 明写这是有意为之（`# T050: ensure the tombstone is written even if the mongo phase failed`），但它与 T051 自述的验收标准（见 §11.2）直接冲突。

**后果链**：任一步失败 → 租户仍被标 `purged` → 30 天后被 `cleanup_expired_tombstones()` 删除（`app/main.py:71` 启动钩子确实调用）→ **失败原因永久丢失**，且 FR-033 的「保留已归档状态」不可能成立。

**附带**：`:180-183` 的 mongo 阶段内 update 是 `:320-323` 的真子集（后者条件 `status != "purged"` 在前者成功后为空操作），属冗余；两次修订的设计意图已自相矛盾（`:16` 说 `stays purged`，`:178-183` 说墓碑不能消失）。

---

## 3. 清理执行时不复检 archived（FR-028）—— 🔴 HIGH

`services/admin-api/app/api/routes/platform/tenants.py:222-223` **只在请求时**校验：
```python
if tenant_lifecycle._status(tenant) != "archived":
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only archived tenants can be purged")
```

`tenant_purge.py:277` 起的 `run_purge(main_id, task_id, actor)` 函数体内**从头到尾没有任何 status 读取**，`:285-286` 直接 `await _phase_mongo(main_id)`。

反向证据：`services/admin-api/app/services/tenant_lifecycle.py:137` 的 `restore_tenant` 确实会把行改回 `{"status": "active"}`，而它与 purge 之间**没有任何互斥锁或状态二次确认**。`POST /tenants/{id}/restore` 在 purge 后台任务排队/执行期间完全可调。

**后果**：并发 restore → 一个 **active** 租户的数据被删除，违反 FR-028。

---

## 4. 进度查询不可靠（FR-032）—— 🔴 HIGH

`tenant_purge.py:84-89`：
```python
class _PurgeTaskStore:
    self._tasks: dict[str, dict[str, Any]] = {}
    self._main_id_to_task: dict[str, str] = {}
```
`:137` `_task_store = _PurgeTaskStore()` —— **纯进程内字典，无 Mongo/Redis 持久化**。

- **重启即丢**：任务跑在 FastAPI `BackgroundTasks` 上（`services/admin-api/app/api/routes/platform/tenants.py:226-231`），进程重启会同时杀掉后台任务、清空 store。此后 `GET /tenants/{id}/purge-status` 只能走 `tenant_purge.py:147-160` 兜底：只有 `tenant.status == "purged"` 时才返回伪 `"done"` + 三阶段全 `done`（**这会掩盖 vectors/files 的真实失败**），否则返回 `{"status": "unknown", "progress": {}, "error": ""}`。真实中断状态与失败原因不可恢复，违反 FR-032 与 FR-033。
- **多 worker 确定性失效**：`services/admin-api/Dockerfile:40` 当前未设 `--workers`（`CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers"]`），单 worker 暂不触发；一旦加 `--workers N`，轮询落到另一进程会命中 `:124-125` `if not key: return None` → 报 `"unknown"`。
- `:98` 只保留最近一个任务句柄，重复发起 purge 会覆盖，旧任务进度不可再查。

---

## 5. 归档租户的员工仍可登录 chat-api（FR-024）—— 🔴 HIGH

**规格要求**：FR-024「归档后该租户所有账号 MUST 被禁止登录」。

**admin-api 侧（✅ 正确）**：三条登录路径全部校验——
- 显式 mainId：`services/admin-api/app/api/routes/auth.py:237` `await _assert_tenant_login_allowed(main_id)`
- 无 mainId 单租户：`:270` 同样调用
- 多租户：`:253` 用 `_tenant_blocked_for_login` 过滤候选
- select-tenant：`:308` 再次校验

**chat-api 侧（❌ 漏洞）**：`grep -rn '"tenants"' services/chat-api/app/` → **零命中**，chat-api 从不读租户状态表。登录闸门只有 `services/chat-api/app/api/endpoints/auth.py:98-100`：
```python
def _is_valid_tenant_main_id(main_id: str) -> bool:
    value = str(main_id or "").strip()
    return bool(value) and value != DEFAULT_MAIN_ID
```
候选租户加载 `services/chat-api/app/services/end_user_tenant_access.py:62`：
```python
organizations = await db.organizations.find({"main_id": {"$in": main_ids}}).to_list(...)
```
**没有 status 过滤**。

**后果**：`DELETE /api/platform/tenants/{main_id}` 归档后，该租户员工用原账号密码访问 chat-api `/auth/login` 仍能拿到会话令牌。`/auth/switch-tenant`（`services/chat-api/app/api/endpoints/auth.py:370-401`）同样无租户状态校验，且会话里 `available_tenants` 快照在归档后仍有效。

**同源变体**：`services/admin-api/app/api/routes/directory.py:830-939` 的 `accept_invite_link` **只挡 default 租户**（`:835-836`），**不校验租户是否 archived**——归档租户的邀请链接在 TTL 内（默认 72h）仍可完成注册。

**修复方向**：chat-api 的 `load_tenant_candidates` / `login` / `switch-tenant` 三处 + admin-api 的 `accept_invite_link` 都补 admin-api 同款检查（查 `tenants` 集合，`status != "active"` 即拒），可复刻 `services/admin-api/app/api/routes/auth.py:203-222`。

---

## 6. `PATCH` 未提及 `memberLimit` 会清空成员上限 —— 🔴 HIGH（已运行复现）

`services/admin-api/app/api/routes/platform/tenants.py:144`：
```python
member_limit=payload.get("memberLimit", payload.get("member_limit", "null")),
```
缺省值是**字面量字符串 `"null"`**。`services/admin-api/app/services/tenant_lifecycle.py:179-181`：
```python
if member_limit is not None:
    if member_limit == "null":
        fields["member_limit"] = None
```
→ 一个**只改名的 PATCH** 会顺手把 `member_limit` 抹成 `None`（= 不限）。

**已运行复现**（用 `tests/test_tenant_lifecycle.py` 的内存桩，临时脚本已清理）：
```
value passed to update_tenant as member_limit: 'null'
name       -> Acme Renamed
member_limit -> None
BUG CONFIRMED: a rename-only PATCH wiped member_limit (was 10).
```

**契约依据**：`specs/020-platform-multi-tenancy/contracts/tenants.md:135` 写「可改：`name`、`status`、`memberLimit`」——三者是**相互独立的可选字段**，省略其一不应影响其它。

**测试覆盖盲区**：`services/admin-api/tests/test_tenant_lifecycle.py:211-221` 只测了 `update_tenant(member_limit="null")` 直接调用（服务层语义），**没有任何测试覆盖 PATCH 路由的 payload 组装**——这正是缺陷没被发现的原因。前端 `apps/admin-web/src/views/platform/TenantsPage.vue:434-437` 的 `submitEdit` 总是显式传 `memberLimit`，所以在 UI 正常操作下不易暴露，但 API 层缺陷确实存在。

**修法**：改成 `payload.get("memberLimit", payload.get("member_limit", None))` 并把「显式清空」只交给字符串 `"null"`。

---

## 7. 契约与实现不一致（文档层）

| # | 契约位置 | 实际实现 | 判定 |
|---|---|---|---|
| C1 | `contracts/tenants.md:108` 创建响应写作 camelCase `{ "mainId": ..., "orgName": ..., "modelInstanceId": null, "additionalModelInstanceIds": [] }` | `services/admin-api/app/api/routes/platform/tenants.py:39` `response_model=ProvisionResult`，而 `services/admin-api/app/services/tenant_provisioning.py` 的 `ProvisionResult` 是**无 alias 的 snake_case** 数据类 | ❌ 契约错。前端 `apps/admin-web/src/api/platform.ts:61-62` 已按 snake_case 实现并注释说明。同文件的 archive 返回（`platform/tenants.py` 用 `{"mainId","status","archivedAt"}`）又是 camelCase，**同一资源两种风格** |
| C2 | `contracts/tenants.md:184`「失败时 `status = "failed"`，租户保持 `archived` 并保留 `error`」 | 见 §2，实际无条件置 `purged` | ❌ 契约与实现同时偏离（契约里的 `"failed"` 也不在 `status` enum `active\|disabled\|archived\|purged` 内） |
| C3 | SC-007「全部租户生命周期操作（创建/改名/启停/归档/恢复/清理/重置密码）均有审计记录可追溯」 | 归档/恢复/改名/启停走 `tenant_lifecycle._record_audit`（`:123/141/197`）、重置密码走 `platform/tenants.py:169`；但**创建**（`services/admin-api/app/services/tenant_provisioning.py` 中 `record_audit` 出现 0 次）与**彻底清理**（`tenant_purge.py:277` 的 `actor` 参数全文未使用）均不写业务审计 | ⚠️ 部分不满足。注：`SystemAuditMiddleware` 会为 `/api/platform` 的变更请求记 `system_audit_logs`（`main_id="__platform__"`），但那是**平台侧请求日志**，不等于「该租户的审计记录」 |

---

## 8. 已确认正确的项（附证明行，避免重复排查）

| 需求 | 证据 |
|---|---|
| FR-015 / FR-016 登录指定与多租户选择 | `services/admin-api/app/api/routes/auth.py` 三分支 + `select_tenant`；子代理用去依赖桩件实跑 5 场景（单租户已归档→403、双租户全归档→403、双活→challengeToken+candidates、显式指定归档→403）全部通过 |
| FR-017 无 mainId 不回退默认租户 | `services/admin-api/app/api/deps.py:30-32` main_id 只来自 token subject，空即 401。grep 命中的 4 处 `settings.bootstrap_main_id`（`auth.py:319/327/356/392`）**全是不可达死代码**（`deps.py:46` 返回的字典总是显式含 `main_id` 键，dict 默认值永不生效） |
| FR-019 拒绝平台标识访问业务接口 | `services/admin-api/app/api/deps.py:70-72` `is_reserved_main_id` → 403 "Tenant context is required"。子代理枚举了全部未带该依赖的路由，仅 4 类且有正当理由（公开登录端点、service-token 内部端点），**无遗漏业务路由** |
| FR-025 归档不计入授权数 | `services/admin-api/app/services/tenant_lifecycle.py:235` `count_documents({"status": "active"})`；`tests/test_tenant_lifecycle.py:170` 有断言 |
| FR-028 confirmName 严格相等 | `services/admin-api/app/api/routes/platform/tenants.py:219-221` 用 `!=` 完全一致校验 |
| FR-034 墓碑写入 + 一个月自动删除 | 成功路径写 `status=purged`+`purged_at`（`tenant_purge.py:180-183`）；`app/main.py:24` 导入、`:71` `await cleanup_expired_tombstones()` 确实在 `on_startup` 执行；`TOMBSTONE_RETENTION = timedelta(days=30)`（`:81`） |
| FR-037 额度查询返回明确不限额标识 | `services/admin-api/app/core/quota_policy.py` 返回 `unlimited: True` + `remainingPoints = -1`；`services/admin-api/app/api/routes/traffic_allocations.py` org/default/user 三处均下发 `unlimited` |
| FR-039 存量升级幂等 | `services/admin-api/app/services/tenant_registry.py:60-80` `find_one_and_update(upsert=True)`，`status`/`created_by`/`created_at` 在 `$setOnInsert` |
| FR-006/007/009/010 平台管理员唯一且幂等 | `services/admin-api/app/services/platform_bootstrap.py:75-76` `if await platform_admin_exists(): return`；11 个 `/api/platform` 路由全挂 `get_current_platform_admin` |
| FR-013 引导不建租户 | `services/admin-api/app/api/routes/setup.py:250-276` 只 `ensure_platform_admin` |

**两处"看起来像 bug 但实际安全"**（避免重复排查）：
1. `services/admin-api/app/services/admin_bootstrap.py:19` 的 `... or settings.bootstrap_main_id` 会落到 `"default"`，但它在 `if settings.tenant_bootstrap_admin_enabled:`（`:17`，默认 **False**）之内，生产走租户供给管线，不违反 FR-017。
2. `services/admin-api/app/api/routes/directory.py:834` `main_id = str(invite.get("main_id", "default"))` 是默认租户回退，但紧随的 `:835-836` 立即拦截，且 `:738-742` 另有第二重防护。

---

## 9. 修复优先级建议

| 优先级 | 项目 | 位置 | 修法要点 |
|---|---|---|---|
| P0 | 失败仍写墓碑（FR-033 反转） | `tenant_purge.py:319-323` | mongo 阶段失败即 `return`；兜底 update 必须仅 `if ok:` 执行 |
| P0 | 清理面不全 —— chat-api 22 个集合 | `tenant_purge.py:33-78` | 补齐 §1.2 清单；建议改为从索引元数据自动发现，避免再次漂移 |
| P0 | 清理面不全 —— admin-api 5 个集合 | `tenant_purge.py:39` 等 | 补 `org_units`（删 dead name `departments`）、`user_quota_overrides`、`admin_presentation_settings`、`page_collection_settings`、`organization_shortcut_schemes` |
| P0 | 归档租户员工仍可登录 | `services/chat-api/app/services/end_user_tenant_access.py:62`、`api/endpoints/auth.py` login/switch-tenant、`services/admin-api/app/api/routes/directory.py:830-939` | 四处补「查 `tenants`，非 active 即拒」 |
| P1 | `PATCH` 清空 memberLimit | `platform/tenants.py:144` | 缺省值由 `"null"` 改为 `None`；补 PATCH 路由层测试 |
| P1 | 向量删除静默成功 | `tenant_purge.py:210-212, 227-236` | 失败聚合进 `errors`；无 token 时不要标 `done` |
| P1 | 头像目录永不删除 | `tenant_purge.py:264` | 用 `_safe_path_part(main_id)` 推导目录名，**不要**改用裸前缀匹配 |
| P1 | 执行时不复检 archived | `tenant_purge.py:277` 起 | 开头加状态断言；路由与任务间加最小互斥 |
| P2 | 进度查询不可靠 | `tenant_purge.py:84-137` | task store 落 Mongo（可复用 `tenants` 行或独立集合） |
| P2 | 契约字段大小写 | `contracts/tenants.md:108` | 与 `contracts/tenants.md:184` 一并对齐实现（或给 `ProvisionResult` 加 alias） |
| P2 | 创建/清理缺业务审计 | `tenant_provisioning.py`、`tenant_purge.py:277` | 补 `_record_audit`，满足 SC-007 |
| P3 | 成员计数不过滤 status | `services/admin-api/app/api/routes/organizations.py:271`、`services/admin-api/app/core/product_edition.py:103` | 统一加 `status` 过滤 |

---

## 10. 审计方法学备注

- `services/admin-api/tests/test_login_tenant_status.py` 只测试了 `_assert_tenant_login_allowed` helper 层，**未覆盖 `login()` 的组装逻辑**——这正是多租户分支重构后缺陷未被发现的原因。建议补路由层集成测试。
- 同理，`services/admin-api/tests/test_tenant_lifecycle.py` 覆盖了服务层 `update_tenant(member_limit=...)` 的各种取值，但**没有任何 PATCH 路由的 payload 组装测试**（见 §6）。
- 当前**不存在任何 `tenant_purge` 的测试**：`grep -rln 'tenant_purge\|TENANT_SCOPED_COLLECTIONS' services/admin-api/tests/` → 无命中。清理是最高危操作却零测试覆盖，这解释了 §1~§4 的缺陷为何全部漏过。

---

## 11. plan.md 自我承诺的兑现核对

§1~§10 是「spec 契约 vs 实现」。本节补做「**plan.md 自己写的风险对策是否真的兑现**」——因为 plan.md:159-167 的「关键风险与对策」表逐条点名了要改的文件与要消除的写法，是比 contracts 更硬的自证标准。

| # | plan.md 承诺 | 位置 | 核对结果 |
|---|---|---|---|
| R1 | 「`directory_bootstrap.py` 排除 `__platform__`；按 `tenants.status=active` 枚举」 | plan.md:128、:164 | ✅ **已兑现**。`services/admin-api/app/services/directory_bootstrap.py:4` 导入 `PLATFORM_MAIN_ID`，枚举为 `db["tenants"].find({"status": "active", "main_id": {"$nin": [None, "", PLATFORM_MAIN_ID]}})` |
| R2 | 「`employee_tenant_identity.py` 同上（排除 `__platform__` + 只认 active）」 | plan.md:129、:164 | ✅ **已兑现**。`services/admin-api/app/services/employee_tenant_identity.py` `excluded = {"$nin": [None, "", "default", PLATFORM_MAIN_ID]}`，`active_main_ids` 取自 `tenants.find({"status": "active", "main_id": excluded})`，并带 `# T042: only active tenants are authoritative for identity repair; archived or purged tenants must not resurrect stale organization names.` |
| R3 | 「`provision_tenant()` 入口拒绝该（`__platform__`）标识」 | plan.md:164 | ✅ **事实安全，但为隐式保证**。`grep -n 'PLATFORM_MAIN_ID\|is_reserved\|RESERVED\|__platform__' services/admin-api/app/services/tenant_provisioning.py` → **无命中**（exit 1），即**没有显式守卫**。但 `_next_main_id`（`:60-67`）生成 `f"{_slug(org_name)[:12]}-{secrets.token_hex(12)}"`，`_slug`（`:55-57`）为 `re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")`，**结构上不可能产出 `__platform__` 或 `default`**；`provision_tenant` 也不接收调用方传入的 main_id。→ 不构成缺陷，但属**隐式不变量**：若将来有人给供给入口加「指定 main_id」参数，守卫就缺了。建议补一行显式断言 |
| R4 | 「抽 `provision_tenant()` 成为**唯一**供给入口」（plan.md:13、阶段 1） | plan.md:13、:147 | ✅ **已兑现**。`services/admin-api/app/api/routes/setup.py` 现存路由仅 `GET /status`、`GET /model-providers`、`POST /model/test`、`GET /search-providers`、`POST /search/test`、`POST /platform-admin`（`:186/212/219/230/236/250`）；`grep -n 'provision_tenant\|_next_main_id\|setup_initialize\|ensure_group_exists\|mark_setup_completed' setup.py` → **无命中**（exit 1）。plan.md:9、:43 描述的「内联在 setup.py 343–463 行」已不存在 |
| R5 | 「逐步消除 114 处 `or "default"` 兜底」 | plan.md:54、:166 | ⚠️ **语义已消化，字面量未消除**。实测：admin-api **81** + chat-api **33** = **114**，与 plan.md 记载**完全一致**，逐文件分布也与 plan.md:54 点名的一致（`knowledge_documents.py` 27 / `skills.py` 17 / `tools.py` 11 / `analytics.py` 5 / `hooks.py` 4）。**但风险已被 R6 从源头关闭**：`services/admin-api/app/api/deps.py:29-32` `main_id = str(subject.get("main_id") or "").strip()` + `if not username or not session_id or not main_id: raise HTTPException(401, "Invalid token subject")`，且 `:44-46` 返回字典**无条件**写 `"main_id": main_id`；token 签发方 `auth.py` 从账号行取 `main_id`。故 `current_user.get("main_id") or "default"` 的 `or` 分支**不可达**，与 FR-017 不冲突。plan.md 原话即为「**逐步**消除」，属已记录的延后项，**不计为缺陷**。补充观察：`knowledge_documents.py:200` 等 `str(doc.get("main_id") or "default")` 是**输出投影**（文档本体的 main_id 落空时才兜底），风险等级更低 |
| R6 | 「`deps` 入口强校验租户标识」（阶段 11 / FR-018） | plan.md:113、:157、:166 | ✅ **已兑现**。`grep -n 'bootstrap_main_id' services/admin-api/app/api/deps.py` 仅剩 `:15` 的**文档字符串**提及（「…has no `bootstrap_main_id` fallback any more (removing it is what closes the …)」），无代码引用 → plan.md:53 记载的 `deps.py:24 ... or settings.bootstrap_main_id` 已消除 |
| R7 | 「彻底清理残留（尤其向量）｜重新盘点集合清单（现有 17 个 vs 实际 72 个集合常量）」 | plan.md:165 | ❌ **未兑现，且这正是 §1 的根因**。独立证据：`services/admin-api/app/services/setup_cleanup.py:18` 的 `SETUP_SCOPED_COLLECTIONS` 恰为 **17** 项，其中含 `org_units`，且 `:12` 注释自证改名——而 `tenant_purge.py:39` 的 `TENANT_SCOPED_COLLECTIONS` 里放的是**废名 `departments`**，`org_units` 在两张 purge 名单中**都不存在**（脚本差集：`SETUP(17) not in purge: ['org_units', 'tenants']`，其中 `tenants` 由墓碑路径单独处理属正常）。plan.md 明确要求做的事没做 |

**另需修正的 plan.md 文本一处**：plan.md:52 与 :151 要求「移除 `auth.py:228`（后为 `:237`）的 `setup_state.main_id` 兜底」，该处**已消除**；但 plan.md 未提及的 `services/admin-api/app/api/routes/auth.py:319/327/356/392` 仍保留**四处 `str(current_user.get("main_id", settings.bootstrap_main_id))`**。经核**不可达**（`deps.py:46` 的字典总是含 `main_id` 键，dict 的 `get` 默认值永不生效），故不违反 FR-017——但这是与 plan.md「移除兜底」精神不符的**残留死代码**，建议随 §9 P3 清理。

**R5/R6 的合并结论（重要）**：`or "default"` 的**数字没降**，但**风险已由 R6 关闭**。这两条必须一起看，单独报「114 处兜底未消除」会是误报。

### 11.1 「清理名单是否真的枚举了全部租户分区集合」——用索引元数据独立复核

`services/admin-api/app/services/setup_cleanup.py:8-9` 的注释自述：

```
# Kept deliberately separate from the purge path (app/services/tenant_purge.py)
# which sweeps every main_id-partitioned collection.
```

这个断言**不成立**。改用**与 §1.1 不同的方法**（不是比对常量名，而是解析全部 `create_index([...])` 中含 `"main_id"` 的块）复核：admin-api 侧共 **21** 个集合声明了 `main_id` 索引，其中未进 purge 名单的 3 个：

| 集合 | 声明处 | 判定 |
|---|---|---|
| `org_units` | `services/admin-api/app/repositories/directory_repository.py:26` | ❌ **真漏项**（与 §1.1 一致，两种方法交叉印证）；purge 名单里躺着废名 `departments` |
| `page_collection_settings` | `services/admin-api/app/api/routes/page_collection.py:106` | ❌ **真漏项**（与 §1.1 一致） |
| `system_bootstrap` | `services/admin-api/app/repositories/setup_repository.py:24` `create_index([("main_id", 1)], unique=True, sparse=True, name="setup_main_id_unique")` | ✅ **假阳性，不清理是正确的**。它是 `_id: "singleton"` 单例（`:29` `find_one({"_id": "singleton"})`、`:40`/`:88` 写入），`main_id` 被钉死为保留标识（`:92` `"main_id": PLATFORM_MAIN_ID`，`:80-82` 注释「the `system_bootstrap` singleton no longer … ``main_id`` is pinned to the reserved」）。非租户分区数据 |

**方法学教训**：「某集合有 `main_id` 唯一索引」**不等于**「该集合按租户分区」。单例集合（`_id: "singleton"`）也会用 `main_id` 索引来约束「只允许一行」。审计此类清单时，**必须同时看 `_id` 语义**，否则会把单例表误报为漏项（本次 `system_bootstrap` 即为实例，已剔除）。

### 11.2 tasks.md 勾选项与实现的偏离（「勾了但没做到」）

`specs/020-platform-multi-tenancy/tasks.md` 的 T045–T052 全部标记 `[x]`。逐条对照实现后发现 **2 项勾选与代码实际行为不符**：

| 任务 | tasks.md 原文（`:122-129`） | 实际实现 | 判定 |
|---|---|---|---|
| **T045**（`:122`） | 「盘点并固化 `TENANT_SCOPED_COLLECTIONS`（**现有 17 个不足，需扫描实际含 `main_id` 的集合**）」 | 交付的是**硬编码 31 项列表**，且仍漏 chat-api 侧 22 个集合（§1.2）、admin-api 侧 `org_units` / `page_collection_settings`（§1.1、§11.1）。**任务书自己写明了「需扫描实际含 main_id 的集合」，这件事没有做** | ❌ 勾选不实 |
| **T051**（`:128`） | 「成功置 `status=purged` 留墓碑；**任一步失败中止并保持 `archived` 且记录原因**」 | `tenant_purge.py:319-323` 无条件置 `purged`（§2）。**且注释明写这是故意的**：`:316-318` `# T050: ensure the tombstone is written even if the mongo phase failed / # before the in-phase update. The row was set to purged inside _phase_mongo; / # if that failed we set it here as a fallback.` | ❌ 勾选不实（且与 T051 自身验收文本直接矛盾） |

**这项交叉验证的价值**：T045/T051 的验收标准是**实现者自己写的**，因此「未达成」不依赖我对 spec 的解读，而是代码与自身任务书冲突的直接证据。§2、§1.2 的结论由此从「审计员判读」升级为「内部矛盾」。

**T052（`:129`）✅ 属实**：`services/admin-api/app/main.py:24` 导入、`:71` `await cleanup_expired_tombstones()  # T052: reap tombstones older than 1 month`；实现于 `tenant_purge.py:326`。墓碑回收确实落地（但见 §2：因失败也写墓碑，它同时成了「失败原因永久丢失」的执行者）。

### 11.3 quickstart.md 验证清单的可通过性判定

`specs/020-platform-multi-tenancy/quickstart.md:120-126` 是一份**可勾选的验收清单**。逐条判定当前实现能否通过：

| 清单项 | 位置 | 判定 |
|---|---|---|
| 仅填 3 个字段即可创建租户，且向量库/文档处理不可用时仍能创建 | `:121` | ✅ 可过（`provision_tenant` 无连通性校验，docstring 自述 "without any connectivity check"） |
| 新租户成员可正常使用，不被额度拦截 | `:122` | ✅ 可过（`tenant_provisioning.py:172` `points_unlimited = (total_tokens is None) or (int(total_tokens or 0) == 0)`，FR-037 有 9 个测试） |
| 租户 A 无法读取租户 B 的任何数据 | `:123` | ✅ 可过（`deps.py` 守卫 + 测试覆盖） |
| 账号属于两个租户时，登录出现选择步骤 | `:124` | ✅ 可过 |
| 归档后该租户账号登录被拒；恢复后数据完整 | `:125` | ❌ **只得一半**。admin-api 侧可过（§8）；但 **chat-api 侧不可过**（§5：chat-api 从不读 `tenants`，员工仍能登录） |
| 未归档租户请求彻底清理被拒（409） | `:126` | ✅ 可过（`platform/tenants.py:222-223`） |
| **清理完成后数据库记录 / 向量 / 磁盘文件残留均为 0，仅剩墓碑** | `:126` | ❌ **不可过**。数据库侧漏 27 个集合（§1.1 5 个 + §1.2 22 个）→ 残留 ≠ 0；向量侧无 token 时静默跳过、失败仅 warning（§1.5）；磁盘侧头像目录 `startswith` 恒 False 永不删除（§1.4） |
| **全部生命周期操作均有审计记录** | `:126` | ❌ **不可过**。创建与彻底清理均无业务审计（§7 C3，对应 SC-007） |
| 既有部署升级后既有企业存在且数据完整 | `:126` | ✅ 可过 |

**即：quickstart 自带的 9 项验收清单里，当前有 3 项必然失败**（`归档后登录被拒`、`清理残留为 0`、`全部生命周期有审计`）——而这 3 项恰好分别对应 §5、§1、§7C3 三条 HIGH 结论，构成独立闭环验证。

### 11.4 checklists/requirements.md 的职责边界（**非**缺陷）

`specs/020-platform-multi-tenancy/checklists/requirements.md` 的 28 项 CHK 全部 `[x]`。**这不是勾选不实**——该文件 `:3` 明确声明「这是"需求的单元测试"，**不校验实现是否正确**」，`:8` 「`[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成」，`:46` 「实现正确性由测试与 `/speckit-analyze` 守护，不在本清单职责范围内」。本报告 §1~§11 属于**实现正确性**范畴，与该清单不构成冲突，不应据此指责其勾选。

**但有两项值得注意的连带影响**：
- **CHK022**（`:38`）「成功标准是否可度量（… SC-005 清理残留为 0）」——SC-005 作为**度量口径**是清晰的，判定为达标无误；但正因它可度量，本报告才得以证明它当前**不成立**（§1）。需求质量与实际达标是两件事。
- **CHK027**（`:44`）「每项成功标准（SC）是否对应可执行的验证动作（quickstart §7 验证清单）」——该映射成立，且**正是这个映射让 §11.3 的三项失败可被机械发现**。这条 CHK 的通过反而提高了审计的可执行性。

**方法学结论**：审计 SDD 特性时，必须区分三类勾选框—— ① `checklists/requirements.md`（需求质量，非实现）；② `tasks.md`（实现任务，**可被证伪**）；③ `quickstart.md` 验证清单（**可执行的验收**）。本次只有 ②③ 能证伪出问题（§11.2、§11.3），① 不应作为指责对象。忽略这一区分会产生系统性误报。
