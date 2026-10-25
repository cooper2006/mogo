# 026 T020/T021 数据库访问模式扫描报告

扫描根目录：`services`

- N+1 候选点：**60**
- 循环单条写入候选点：**39**

## N+1（FR-7，候选改为批量预取或 `$lookup` 聚合）

| 文件 | 行 | 方法 | 循环 | 建议 |
| --- | --- | --- | --- | --- |
| `services/admin-api/app/api/routes/dashboard.py` | 392 | `count_documents` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/api/routes/directory.py` | 280 | `find_one` | while | 批量预取 / `$lookup` |
| `services/admin-api/app/api/routes/directory.py` | 530 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/core/pg_compat.py` | 2027 | `find` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/governance/permission_grants.py` | 153 | `find` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/directory_bootstrap.py` | 18 | `find` | list-comp | 批量预取 / `$lookup` |
| `services/admin-api/app/services/directory_bootstrap.py` | 24 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/directory_bootstrap.py` | 27 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/employee_tenant_identity.py` | 42 | `find` | ? | 批量预取 / `$lookup` |
| `services/admin-api/app/services/employee_tenant_identity.py` | 48 | `find` | list-comp | 批量预取 / `$lookup` |
| `services/admin-api/app/services/employee_tenant_identity.py` | 55 | `find` | list-comp | 批量预取 / `$lookup` |
| `services/admin-api/app/services/organization_tools.py` | 54 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/organization_tools.py` | 61 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/tenant_provisioning.py` | 69 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/tenant_purge.py` | 484 | `find` | async-for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/tenant_registry.py` | 118 | `find` | ? | 批量预取 / `$lookup` |
| `services/admin-api/app/services/tenant_registry.py` | 130 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/tenant_registry.py` | 133 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/tenant_registry.py` | 137 | `find_one` | for | 批量预取 / `$lookup` |
| `services/admin-api/app/services/token_usage_analytics_helpers.py` | 48 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/auth.py` | 289 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/auth.py` | 454 | `find` | list-comp | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/personal_knowledge.py` | 106 | `find_one` | while | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/sessions.py` | 671 | `find` | async-for | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/sessions.py` | 702 | `find` | async-for | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/sessions.py` | 720 | `find_one` | async-for | 批量预取 / `$lookup` |
| `services/chat-api/app/api/endpoints/sessions.py` | 866 | `find` | async-for | 批量预取 / `$lookup` |
| `services/chat-api/app/core/pg_compat.py` | 2027 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/enterprise_capabilities/browser/engine/workflow_cache/parameters.py` | 102 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/enterprise_capabilities/content/writer_engine/pipeline.py` | 1068 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/enterprise_capabilities/evidence/foundation/user_request_fact_extractor.py` | 52 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/enterprise_capabilities/evidence/foundation/writer_packet/document_adapter.py` | 19 | `find` | list-comp | 批量预取 / `$lookup` |
| `services/chat-api/app/llm/configured_models.py` | 162 | `find` | async-for | 批量预取 / `$lookup` |
| `services/chat-api/app/llm/configured_models.py` | 343 | `find` | async-for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/form_filling/mapper.py` | 16 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/ontology_permission.py` | 199 | `find` | list-comp | 批量预取 / `$lookup` |
| `services/chat-api/app/services/page_collection_config.py` | 16 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/personal_knowledge/service.py` | 165 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/personal_knowledge/service.py` | 199 | `find` | while | 批量预取 / `$lookup` |
| `services/chat-api/app/services/portal/listings.py` | 277 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/portal/listings.py` | 282 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/presentation/pptx_compiler.py` | 81 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/presentation/pptx_compiler.py` | 89 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/presentation/pptx_compiler.py` | 93 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/presentation/svg_to_shape.py` | 412 | `find` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/resource_feedback/service.py` | 212 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/resource_feedback/service.py` | 213 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/resource_feedback/service.py` | 216 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/resource_feedback/service.py` | 219 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/search_provider_config.py` | 33 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/session_versioning/placeholder.py` | 87 | `find` | while | 批量预取 / `$lookup` |
| `services/chat-api/app/services/session_versioning/placeholder.py` | 90 | `find` | while | 批量预取 / `$lookup` |
| `services/chat-api/app/services/session_versioning/placeholder.py` | 110 | `find` | while | 批量预取 / `$lookup` |
| `services/chat-api/app/services/session_versioning/placeholder.py` | 113 | `find` | while | 批量预取 / `$lookup` |
| `services/chat-api/app/services/skill_sharing/distribution.py` | 243 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/skill_sharing/legacy_migration.py` | 48 | `find_one` | for | 批量预取 / `$lookup` |
| `services/chat-api/app/services/token_usage_service.py` | 176 | `find_one` | for | 批量预取 / `$lookup` |
| `services/document-parser/app/core/pg_compat.py` | 2020 | `find` | for | 批量预取 / `$lookup` |
| `services/document-parser/app/services/retrieval_access_policy.py` | 86 | `find` | ? | 批量预取 / `$lookup` |
| `services/document-parser/app/services/retrieval_access_policy.py` | 98 | `find` | ? | 批量预取 / `$lookup` |

## 循环单条写入（FR-12，候选改为 `bulk_write`）

| 文件 | 行 | 方法 | 循环 | 建议 |
| --- | --- | --- | --- | --- |
| `services/admin-api/app/api/routes/directory.py` | 149 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/api/routes/directory.py` | 338 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/api/routes/directory.py` | 1104 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/api/routes/knowledge_directories.py` | 60 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/api/routes/knowledge_directories.py` | 275 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/core/pg_compat.py` | 1702 | `insert_one` | for | `bulk_write` |
| `services/admin-api/app/core/pg_compat.py` | 1970 | `insert_one` | for | `bulk_write` |
| `services/admin-api/app/core/pg_compat.py` | 1976 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/core/pg_compat.py` | 1985 | `replace_one` | for | `bulk_write` |
| `services/admin-api/app/core/pg_compat.py` | 1994 | `delete_one` | for | `bulk_write` |
| `services/admin-api/app/position_roles/repository.py` | 154 | `insert_one` | for | `bulk_write` |
| `services/admin-api/app/repositories/model_repository.py` | 121 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/security/audit_events.py` | 383 | `insert_one` | for | `bulk_write` |
| `services/admin-api/app/security/audit_events.py` | 521 | `insert_one` | for | `bulk_write` |
| `services/admin-api/app/services/organization_tools.py` | 68 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/services/organization_tools.py` | 81 | `update_one` | for | `bulk_write` |
| `services/admin-api/app/services/skill_market/canary.py` | 546 | `replace_one` | for | `bulk_write` |
| `services/admin-api/app/services/skill_market/canary.py` | 584 | `replace_one` | for | `bulk_write` |
| `services/chat-api/app/context_engine/project_memory.py` | 119 | `update_one` | for | `bulk_write` |
| `services/chat-api/app/core/pg_compat.py` | 1702 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/core/pg_compat.py` | 1970 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/core/pg_compat.py` | 1976 | `update_one` | for | `bulk_write` |
| `services/chat-api/app/core/pg_compat.py` | 1985 | `replace_one` | for | `bulk_write` |
| `services/chat-api/app/core/pg_compat.py` | 1994 | `delete_one` | for | `bulk_write` |
| `services/chat-api/app/knowledge_graph/persisted_store.py` | 204 | `replace_one` | for | `bulk_write` |
| `services/chat-api/app/knowledge_graph/persisted_store.py` | 213 | `replace_one` | for | `bulk_write` |
| `services/chat-api/app/scheduled_tasks/migration.py` | 35 | `update_one` | async-for | `bulk_write` |
| `services/chat-api/app/security/audit_events.py` | 347 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/security/audit_events.py` | 449 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/services/personal_knowledge/service.py` | 176 | `update_one` | for | `bulk_write` |
| `services/chat-api/app/services/personal_knowledge/service.py` | 178 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/services/resource_feedback/service.py` | 129 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/services/skill_sharing/distribution.py` | 245 | `insert_one` | for | `bulk_write` |
| `services/chat-api/app/services/skill_sharing/legacy_migration.py` | 61 | `update_one` | for | `bulk_write` |
| `services/document-parser/app/core/pg_compat.py` | 1695 | `insert_one` | for | `bulk_write` |
| `services/document-parser/app/core/pg_compat.py` | 1963 | `insert_one` | for | `bulk_write` |
| `services/document-parser/app/core/pg_compat.py` | 1969 | `update_one` | for | `bulk_write` |
| `services/document-parser/app/core/pg_compat.py` | 1978 | `replace_one` | for | `bulk_write` |
| `services/document-parser/app/core/pg_compat.py` | 1987 | `delete_one` | for | `bulk_write` |

## 说明

- 本报告为静态 AST 扫描结果，**未执行代码**；候选点需人工确认后再改造。
- 已确认使用 `bulk_write` 的点（如 memory/lifecycle.py、dsh_runtime/events/repository.py）不重复列入。
- 改造完成后重跑本脚本，候选应减少至 0 或已登记为「确认为必要单查」。