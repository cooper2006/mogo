# uuid4().hex 使用清单（058 T003）

> 生成方式：`python3 scripts/check_uuid_hex_usage.py --inventory`。
> 本清单由脚本按「代码调用」口径生成（用 `tokenize` 排除注释/docstring 中的字面文本），
> 范围限定 admin-api / chat-api / document-parser 三个服务（sandbox-manager 等独立服务不在 058 范围）。

## 分类口径

| 类别 | 数量 | 处置 |
|---|---|---|
| 实体主键 / 事件 ID（整体 32-hex 赋值） | 81 | 存量登记基线，逐步替换；**新增会被 CI 拦截** |
| 允许场景（令牌/短ID/追踪/临时文件名） | 52 | 有意保留，理由见下方说明 |
| 合计 | 133 | |

**为何允许场景不替换**：`generate_hex32_id()` = 12-hex 毫秒时间戳 + 20-hex 随机数。
- 切片短 ID（`[:10]` / `[:12]`）：前 12 位是时间戳，同毫秒内前缀相同，替换会引入碰撞；
- 令牌 / 密钥 / JWT `jti` / `resume_token` / boundary：时间有序会降熵，削弱安全性；
- `trace_id` / `request_id` / 临时文件名 / 带业务前缀的拼接：不是 `_id` 游标，无顺序需求。

## 本轮已替换（spec T006 清单）

以下文件的实体主键调用点已改为 `from app.core.ids import generate_hex32_id`：

- `services/chat-api/app/employees/repository.py`（employee_id / event_id）
- `services/admin-api/app/services/skill_lifecycle.py`（release `_id` ×2）
- `services/admin-api/app/position_roles/repository.py`（role `_id`）
- `services/admin-api/app/services/tenant_registry.py`（tenant `_id`，原 `from uuid import uuid4` 变体）
- `services/admin-api/app/services/eval_gate/gate.py`（event_id / `_id`）
- `services/admin-api/app/services/eval_gate/test_sets.py`（test set `_id`）
- `services/admin-api/app/api/routes/knowledge_documents.py`（document_id）
- `services/admin-api/app/services/capability_assets/registry.py`（audit `_id`）

> 注：`services/admin-api/app/services/eval_gate/gateway_auth.py` 的 `jti` 是 JWT 令牌标识，
> 按「逐文件核查」结论保留 `uuid4().hex`（非实体主键，且需保持不可预测性）。

## 存量实体主键明细（按文件）

- `services/admin-api/app/api/routes/auth.py` — 1 处
  - L761: `filename = f"{_safe_path_part(username, 'user')}-{uuid.uuid4().hex}.{ext}"`
- `services/admin-api/app/api/routes/connector_market.py` — 1 处
  - L197: `"_id": uuid.uuid4().hex,`
- `services/admin-api/app/api/routes/external_search.py` — 1 处
  - L136: `doc_id = str((existing or {}).get("_id") or uuid.uuid4().hex)`
- `services/admin-api/app/api/routes/knowledge_directories.py` — 1 处
  - L192: `directory_id = uuid.uuid4().hex`
- `services/admin-api/app/api/routes/memories.py` — 2 处
  - L299: `"_id": uuid.uuid4().hex,`
  - L328: `"_id": uuid.uuid4().hex,`
- `services/admin-api/app/api/routes/page_collection.py` — 1 处
  - L82: `doc_id = str((existing or {}).get("_id") or uuid.uuid4().hex)`
- `services/admin-api/app/api/routes/portal_admin.py` — 1 处
  - L188: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/api/routes/position_roles.py` — 1 处
  - L204: `override_id = uuid.uuid4().hex`
- `services/admin-api/app/api/routes/skills.py` — 1 处
  - L285: `"_id": uuid.uuid4().hex,`
- `services/admin-api/app/api/routes/tools.py` — 1 处
  - L251: `"_id": uuid.uuid4().hex,`
- `services/admin-api/app/employees/api_keys.py` — 1 处
  - L125: `key_id = uuid.uuid4().hex`
- `services/admin-api/app/employees/repository.py` — 2 处
  - L109: `"_id": uuid.uuid4().hex,`
  - L186: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/governance/config.py` — 1 处
  - L167: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/governance/layers/audit.py` — 1 处
  - L50: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/governance/permission_grants.py` — 1 处
  - L169: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/governance/risk.py` — 1 处
  - L164: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/middleware/trace_id.py` — 1 处
  - L26: `return uuid.uuid4().hex`
- `services/admin-api/app/position_roles/service.py` — 1 处
  - L64: `doc.update({"_id": uuid.uuid4().hex, "protected": False, "created_at": utcnow(), "updated_at": utcnow()})`
- `services/admin-api/app/security/audit_events.py` — 1 处
  - L106: `event_id: str = field(default_factory=lambda: f"{EVENT_ID_PREFIX}-{uuid.uuid4().hex}")`
- `services/admin-api/app/services/setup_external_search.py` — 1 处
  - L71: `"_id": uuid.uuid4().hex,`
- `services/admin-api/app/services/templates/model.py` — 2 处
  - L50: `return f"tpl_{uuid.uuid4().hex}"`
  - L54: `return f"clone_{uuid.uuid4().hex}"`
- `services/admin-api/app/services/templates/repository.py` — 1 处
  - L224: `"event_id": uuid.uuid4().hex,`
- `services/admin-api/app/services/templates/upgrade.py` — 1 处
  - L71: `upgrade_id=f"upg_{uuid.uuid4().hex}",`
- `services/admin-api/app/system_audit/repository.py` — 1 处
  - L27: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/api/endpoints/personal_knowledge.py` — 1 处
  - L89: `now, row_id = datetime.datetime.now(datetime.timezone.utc), uuid.uuid4().hex`
- `services/chat-api/app/api/endpoints/skills.py` — 2 处
  - L1593: `skill_id = uuid.uuid4().hex`
  - L1658: `skill_id = uuid.uuid4().hex`
- `services/chat-api/app/dsh_runtime/plugin_management/archive_store.py` — 1 处
  - L20: `archive_id = uuid.uuid4().hex`
- `services/chat-api/app/dsh_runtime/profile/plugin_runtime_recovery.py` — 1 处
  - L31: `probe_id = uuid4().hex`
- `services/chat-api/app/employees/api_keys.py` — 1 处
  - L120: `key_id = uuid.uuid4().hex`
- `services/chat-api/app/employees/boundary.py` — 1 处
  - L130: `"event_id": uuid.uuid4().hex,`
- `services/chat-api/app/enterprise_capabilities/browser/engine/desktop_agent_executor.py` — 1 处
  - L1600: `if run_id else f"assist_{uuid.uuid4().hex}"`
- `services/chat-api/app/enterprise_capabilities/browser/engine/workflow_cache/repository.py` — 2 处
  - L124: `workflow_id = str(existing.get("workflow_id") or uuid.uuid4().hex)`
  - L186: `workflow_id=uuid.uuid4().hex,`
- `services/chat-api/app/execution_isolation/call_audit.py` — 1 处
  - L58: `call_dir = workspace / "work" / "calls" / uuid4().hex`
- `services/chat-api/app/execution_isolation/script_backend.py` — 1 处
  - L49: `path = root / uuid4().hex`
- `services/chat-api/app/governance/approval_kernel.py` — 2 处
  - L225: `"event_id": uuid.uuid4().hex,`
  - L269: `ticket_id = uuid.uuid4().hex`
- `services/chat-api/app/governance/audit.py` — 1 处
  - L14: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/im_gateway/binding_store.py` — 1 处
  - L54: `binding.binding_id = uuid.uuid4().hex`
- `services/chat-api/app/infrastructure/execution_events/schema.py` — 1 处
  - L53: `"event_id": event_id or uuid.uuid4().hex,`
- `services/chat-api/app/memory/store.py` — 1 处
  - L148: `mem_id = str(memory_id or uuid.uuid4().hex)`
- `services/chat-api/app/middleware/trace_id.py` — 1 处
  - L24: `return uuid.uuid4().hex`
- `services/chat-api/app/orchestration/run_store.py` — 1 处
  - L79: `"run_id": uuid.uuid4().hex,`
- `services/chat-api/app/scheduled_tasks/repository.py` — 1 处
  - L172: `"run_id": uuid.uuid4().hex,`
- `services/chat-api/app/security/audit_events.py` — 1 处
  - L88: `event_id: str = field(default_factory=lambda: f"{EVENT_ID_PREFIX}-{uuid.uuid4().hex}")`
- `services/chat-api/app/services/external_tools.py` — 3 处
  - L287: `"_id": uuid.uuid4().hex,`
  - L727: `"uuid": uuid.uuid4().hex,`
  - L944: `"_id": str(node.get("id") or node.get("_id") or uuid.uuid4().hex),`
- `services/chat-api/app/services/feature_audit_bridge.py` — 1 处
  - L99: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/ontology_permission.py` — 1 处
  - L390: `"event_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/personal_knowledge/service.py` — 2 处
  - L39: `resource_id = uuid.uuid4().hex`
  - L178: `await db[GRANT_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, **values, "seen_at": None, "created_at": now})`
- `services/chat-api/app/services/portal/requests.py` — 1 处
  - L156: `"event_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/resource_feedback/service.py` — 6 处
  - L105: `"_id": uuid.uuid4().hex, **self._query(tenant_id, subject),`
  - L130: `"_id": uuid.uuid4().hex, **self._query(tenant_id, subject),`
  - L156: `await db[REACTION_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, "created_at": _utcnow()})`
  - L161: `"_id": uuid.uuid4().hex, **self._query(tenant_id, subject),`
  - L180: `await db[COMMENT_REACTION_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, "created_at": _utcnow()})`
  - L186: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/site_profiles.py` — 1 处
  - L159: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/skill_lifecycle/service.py` — 2 处
  - L129: `"_id": uuid.uuid4().hex,`
  - L188: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/skill_packages/archive_store.py` — 1 处
  - L29: `file_id = uuid.uuid4().hex`
- `services/chat-api/app/services/skill_packages/installer.py` — 2 处
  - L59: `package_id = uuid.uuid4().hex`
  - L125: `skill_id = uuid.uuid4().hex`
- `services/chat-api/app/services/skill_sharing/direct_service.py` — 2 处
  - L66: `share_id = uuid.uuid4().hex`
  - L256: `return f"{micros:016x}{uuid.uuid4().hex}"`
- `services/chat-api/app/services/skill_sharing/distribution.py` — 4 处
  - L42: `row = {"_id": uuid.uuid4().hex, **query, "created_at": _utcnow(), "updated_at": _utcnow()}`
  - L69: `"_id": str(release_id or uuid.uuid4().hex),`
  - L153: `await db[MEMBER_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, **values, "created_at": _utcnow()})`
  - L246: `"_id": uuid.uuid4().hex,`
- `services/chat-api/app/services/skill_sharing/service.py` — 1 处
  - L72: `share_id = uuid.uuid4().hex`
- `services/chat-api/app/services/skills.py` — 1 处
  - L1122: `"_id": payload.get("id") or uuid.uuid4().hex,`
- `services/document-parser/app/api/routes/document_indexing.py` — 1 处
  - L21: `job_id = f"index_{uuid.uuid4().hex}"`
- `services/document-parser/app/api/routes/document_parsing.py` — 1 处
  - L25: `job_id = f"parse_{uuid.uuid4().hex}"`
- `services/document-parser/app/api/routes/preview_conversion.py` — 1 处
  - L24: `job_id = f"preview_{uuid.uuid4().hex}"`
- `services/document-parser/app/middleware/trace_id.py` — 1 处
  - L26: `return uuid.uuid4().hex`

## 基线

存量用法登记在 `scripts/uuid_hex_baseline.json`；`--full` / `--staged` 只拦截基线之外的新增。
替换一批后执行 `python3 scripts/check_uuid_hex_usage.py --update-baseline` 重建。
