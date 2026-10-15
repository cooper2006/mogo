# 027-R3 全域关系化扁平化方案

> **状态**: 方案阶段（不直接落库）
> **作者**: DSH Agent
> **日期**: 2026-10-15
> **关联文档**: `docs/mongo-to-panweidb-migration-plan.md`（027 权威迁移方案）

---

## 目录

1. [目标与范围](#1-目标与范围)
2. [前提与约束](#2-前提与约束)
3. [全域表清单与扁平化决策总表](#3-全域表清单与扁平化决策总表)
4. [按域详细方案](#4-按域详细方案)
   - [4.1 账号域](#41-账号域)
   - [4.2 会话/聊天域](#42-会话聊天域)
   - [4.3 组织域](#43-组织域)
   - [4.4 技能域](#44-技能域)
   - [4.5 知识域](#45-知识域)
   - [4.6 资源/反馈域](#46-资源反馈域)
   - [4.7 审计/治理/日志域](#47-审计治理日志域)
5. [兼容层改造要点](#5-兼容层改造要点)
6. [实施路线图](#6-实施路线图)
7. [风险与回滚](#7-风险与回滚)

---

## 1. 目标与范围

### 1.1 目标

将 `mogo_dev` 库下全部 **114 张表**从当前的「单表 + JSONB doc 字段」结构，按需扁平化为「真实列 + 索引」结构，使热点集合获得真正的关系型查询能力，同时保持与现有 MongoDB 兼容层的向后兼容。

### 1.2 范围

- **库**: `mogo_dev`（PanWeiDB 3.2.0，openGauss 内核，sql_compatibility='A'）
- **表**: 全部 114 张表（见 §3 总表）
- **不包含**: 索引重建、数据迁移脚本、兼容层代码修改（本次仅产出方案）

### 1.3 扁平化判定标准

对每张表，按以下维度评估是否适合扁平化：

| 维度 | 扁平化条件 | 不扁平化条件 |
|------|-----------|-------------|
| 字段稳定性 | 字段结构稳定，写入路径明确 | 字段动态/半结构化/嵌套复杂 |
| 查询热度 | 频繁作为 WHERE/JOIN/ORDER BY 条件 | 几乎只按 id/tenant_id 查询 |
| 字段基数 | 低基数、适合索引 | 高基数文本、大对象 |
| 一致性要求 | 需要 NOT NULL、CHECK、UNIQUE 约束 | 无强约束需求 |
| 数据量 | 中小表（< 1000 万行） | 超大表且写入频繁 |

---

## 2. 前提与约束

### 2.1 openGauss A 模式约束（不可改）

| 可用 | 不可用 |
|------|--------|
| `jsonb_set` | `jsonb_build_array` |
| `jsonb_typeof` | `jsonb_build_object` |
| `jsonb_array_length` | `#-` |
| `to_jsonb` | `jsonb_strip_nulls` |
| `||` | `jsonb_pretty` |
| `@>` | `jsonb_to_record` |
| `?` | `jsonb_object_agg` |
| `jsonb_agg` | `jsonb_path_ops` |
| `jsonb_extract_path_text` | |
| `jsonb - text/int` | |

- **GIN 索引（jsonb_ops）遇空字符串即报错**，建表 DDL 只建 `tenant_id` btree 索引
- **不支持 `ON CONFLICT`**，幂等写入靠"先查后写"
- **`min()`/`max()` 聚合对 jsonb 按文本比较**

### 2.2 兼容层现状

写入时同步落列 + 拼回 doc；读取时以列为准拼 doc；筛选时 COLUMN_MAP 命中键走真实列。

---

## 3. 全域表清单与扁平化决策总表

> **图例**: ✅ = 扁平化（全字段平铺） / 🔶 = 部分扁平化（核心字段平铺，动态字段保留 doc） / ❌ = 不扁平化（保持 doc JSONB）

| # | 表名 | 决策 | 平铺列集 | 保留在 doc 的动态字段 | 唯一/索引约束 |
|---|------|------|---------|---------------------|-------------|
| 1 | admin_account_groups | 🔶 | tenant_id, name, parent_id, status, sort_order, created_by, created_at, updated_by, updated_at, deleted_at | metadata, settings | (tenant_id, name, parent_id) WHERE deleted_at IS NULL |
| 2 | admin_accounts | ✅ | tenant_id, login_name, password_hash, password_algorithm, name, display_name, email, phone, avatar_url, status, failed_login_count, locked_at, last_login_at, last_login_ip, mfa_enabled, created_by, created_at, updated_by, updated_at, deleted_at | recovery_codes, preferences | (tenant_id, login_name) WHERE deleted_at IS NULL |
| 3 | admin_login_challenges | ❌ | — | challenge_id, admin_id, ip_address, user_agent, verified, expires_at, created_at | — |
| 4 | admin_model_instances | 🔶 | tenant_id, provider_id, model_key, label, base_url, api_key_encrypted, auth_type, status, is_default, sort_order, created_by, created_at, updated_by, updated_at, deleted_at | config, headers, capabilities | (tenant_id, model_key) WHERE deleted_at IS NULL |
| 5 | admin_model_providers | ✅ | tenant_id, name, base_url, auth_type, api_key_encrypted, status, is_default, sort_order, created_by, created_at, updated_by, updated_at, deleted_at | config, headers, capabilities | (tenant_id, name) WHERE deleted_at IS NULL |
| 6 | admin_presentation_settings | 🔶 | tenant_id, theme, font_family, color_primary, color_background, logo_url, favicon_url, created_by, created_at, updated_by, updated_at | custom_css, layout_overrides, block_settings | (tenant_id) |
| 7 | admin_recovery_tokens | ❌ | — | admin_id, token_hash, used, expires_at, created_at | — |
| 8 | admin_refresh_tokens | ❌ | — | admin_id, token_hash, device_info, expires_at, created_at, revoked_at | — |
| 9 | admin_sessions | ❌ | — | admin_id, token_hash, device_info, ip_address, user_agent, expires_at, created_at, last_active_at | — |
| 10 | agent_kernel_bindings | 🔶 | tenant_id, kernel_type, kernel_id, binding_type, binding_ref, status, created_by, created_at, updated_by, updated_at, deleted_at | config, metadata | (tenant_id, kernel_type, kernel_id) WHERE deleted_at IS NULL |
| 11 | approval_events | ❌ | — | approval_id, event_type, actor_user_id, target_type, target_id, status, payload, created_at | — |
| 12 | audit_events | ❌ | — | tenant_id, event_type, actor_type, actor_id, target_type, target_id, ip_address, user_agent, status, payload, created_at | — |
| 13 | audit_logs | ❌ | — | tenant_id, log_type, level, message, context, stack_trace, created_at | — |
| 14 | autonomy_matrix | 🔶 | tenant_id, name, description, scope_type, scope_ref, rules, enabled, created_by, created_at, updated_by, updated_at, deleted_at | overrides, metadata | (tenant_id, scope_type, scope_ref, name) WHERE deleted_at IS NULL |
| 15 | business_entity_index | ❌ | — | tenant_id, entity_type, entity_id, display_name, search_text, metadata, created_at, updated_at | — |
| 16 | chat_messages | 🔶 | tenant_id, session_id, sender_type, sender_id, content, content_type, status, parent_id, reply_to_id, created_at, updated_at, deleted_at | attachments, metadata, reactions | (tenant_id, session_id, created_at) |
| 17 | chat_sessions | ✅ | tenant_id, type, title, owner_user_id, participant_ids, status, last_message_id, last_message_at, last_message_preview, created_by, created_at, updated_by, updated_at, deleted_at | metadata, settings | (tenant_id, owner_user_id, deleted_at) |
| 18 | dag_definitions | 🔶 | tenant_id, name, description, graph_data, version, status, created_by, created_at, updated_by, updated_at, deleted_at | schedule, triggers, variables | (tenant_id, name) WHERE deleted_at IS NULL |
| 19 | desktop_projects | 🔶 | tenant_id, name, description, owner_user_id, template_id, status, data, created_by, created_at, updated_by, updated_at, deleted_at | metadata, assets | (tenant_id, owner_user_id, deleted_at) |
| 20 | document_jobs | ❌ | — | tenant_id, job_type, document_id, status, progress, result, error, started_at, completed_at, created_at | — |
| 21 | end_user_capability_overrides | 🔶 | tenant_id, user_id, capability_key, enabled, value, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, user_id, capability_key) WHERE deleted_at IS NULL |
| 22 | end_user_login_challenges | ❌ | — | user_id, challenge_id, ip_address, user_agent, verified, expires_at, created_at | — |
| 23 | end_user_org_relations | ✅ | tenant_id, user_id, org_id, position_id, role_type, status, start_date, end_date, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, user_id, org_id) WHERE deleted_at IS NULL |
| 24 | end_user_position_roles | ✅ | tenant_id, user_id, position_id, role_name, role_type, status, start_date, end_date, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, user_id, position_id) WHERE deleted_at IS NULL |
| 25 | end_user_sessions | ❌ | — | user_id, token_hash, device_info, ip_address, user_agent, expires_at, created_at, last_active_at | — |
| 26 | end_users | ✅ | tenant_id, name, display_name, login_name, email, phone, avatar_url, status, password_hash, password_algorithm, failed_login_count, locked_at, last_login_at, last_login_ip, mfa_enabled, created_by, created_at, updated_by, updated_at, deleted_at | recovery_codes, preferences, metadata | (tenant_id, login_name) WHERE deleted_at IS NULL |
| 27 | enterprise_action_receipts | ❌ | — | tenant_id, action_id, receipt_type, status, payload, created_at | — |
| 28 | enterprise_authoritative_deliveries | ❌ | — | tenant_id, delivery_id, target_type, target_id, status, payload, created_at | — |
| 29 | enterprise_session_approval_grants | ❌ | — | tenant_id, session_id, grant_type, grantee_user_id, status, expires_at, created_at | — |
| 30 | enterprise_tool_approvals | ❌ | — | tenant_id, tool_id, approval_type, requester_user_id, status, payload, created_at | — |
| 31 | enterprise_tool_audit | ❌ | — | tenant_id, tool_id, action, actor_user_id, status, payload, created_at | — |
| 32 | execution_logs | ❌ | — | tenant_id, execution_id, step_id, level, message, context, stack_trace, created_at | — |
| 33 | experience_fragments | ❌ | — | tenant_id, fragment_type, content, metadata, created_at, updated_at | — |
| 34 | external_search_configs | 🔶 | tenant_id, name, provider, api_key_encrypted, endpoint, status, is_default, sort_order, created_by, created_at, updated_by, updated_at, deleted_at | config, query_templates | (tenant_id, name) WHERE deleted_at IS NULL |
| 35 | external_tools | 🔶 | tenant_id, name, description, base_url, auth_type, api_key_encrypted, status, is_default, sort_order, created_by, created_at, updated_by, updated_at, deleted_at | config, headers, capabilities | (tenant_id, name) WHERE deleted_at IS NULL |
| 36 | gate_approvals | ❌ | — | tenant_id, gate_id, approval_type, requester_user_id, status, payload, created_at | — |
| 37 | gate_events | ❌ | — | tenant_id, gate_id, event_type, actor_user_id, status, payload, created_at | — |
| 38 | gatekeeper_rules | 🔶 | tenant_id, name, description, rule_type, condition, action, priority, enabled, created_by, created_at, updated_by, updated_at, deleted_at | config, metadata | (tenant_id, name) WHERE deleted_at IS NULL |
| 39 | harness_profiles | 🔶 | tenant_id, name, description, type, config, status, created_by, created_at, updated_by, updated_at, deleted_at | variables, hooks | (tenant_id, name) WHERE deleted_at IS NULL |
| 40 | hook_rules | 🔶 | tenant_id, name, description, event_type, condition, action, priority, enabled, created_by, created_at, updated_by, updated_at, deleted_at | config, metadata | (tenant_id, name) WHERE deleted_at IS NULL |
| 41 | im_channels | ✅ | tenant_id, type, name, owner_user_id, member_ids, status, last_message_id, last_message_at, last_message_preview, created_by, created_at, updated_by, updated_at, deleted_at | metadata, settings | (tenant_id, owner_user_id, deleted_at) |
| 42 | im_session_bindings | ❌ | — | tenant_id, session_id, channel_id, binding_type, status, created_at, updated_at | — |
| 43 | kernel_event_inbox | ❌ | — | tenant_id, event_id, event_type, source, status, payload, created_at | — |
| 44 | kernel_event_projections | ❌ | — | tenant_id, projection_id, event_type, status, data, created_at, updated_at | — |
| 45 | knowledge_directories | ✅ | tenant_id, name, parent_id, path_ids, path_names, owner_user_id, scope, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, owner_user_id, parent_id, name) WHERE deleted_at IS NULL |
| 46 | knowledge_document_chunks | 🔶 | tenant_id, document_id, chunk_id, chunk_stage, ordinal, text, contextual_text, title_path, page_no, content_type, source_chunk_ids, status, created_at, updated_at | metadata | (tenant_id, document_id, chunk_stage, ordinal) |
| 47 | knowledge_document_settings | 🔶 | tenant_id, kind, config, updated_by, updated_at, created_at | — | (tenant_id, kind) |
| 48 | knowledge_documents | ✅ | tenant_id, scope, owner_user_id, resource_id, knowledge_base_id, name, description, original_filename, file_ext, mime_type, file_size, storage_type, storage_bucket, storage_key, local_path, checksum, status, parse_status, parse_job_id, parse_error, parse_updated_at, parsed_markdown_key, parsed_json_key, raw_chunks_key, raw_chunk_count, rag_chunks_key, rag_chunk_count, chunks_key, chunk_count, chunk_status, index_status, index_job_id, index_error, indexed_chunk_count, indexed_at, vector_store_type, vector_collection_name, preview_key, preview_mime_type, preview_status, preview_job_id, preview_error, preview_updated_at, tags, created_by, created_by_name, updated_by, updated_by_name, created_at, updated_at, deleted_at | metadata | (tenant_id, knowledge_base_id, name) WHERE deleted_at IS NULL |
| 49 | knowledge_resources | ✅ | tenant_id, owner_user_id, directory_id, name, description, tags, share_policy, active_document_id, processing_document_id, status, error, created_at, updated_at, deleted_at | — | (tenant_id, owner_user_id, directory_id, name) WHERE deleted_at IS NULL |
| 50 | memories | ❌ | — | tenant_id, user_id, memory_type, content, metadata, created_at, updated_at | — |
| 51 | mfa_lockouts | ❌ | — | tenant_id, user_id, reason, attempts, expires_at, created_at | — |
| 52 | mfa_used_steps | ❌ | — | tenant_id, user_id, step_id, used_at | — |
| 53 | org_quota_policies | 🔶 | tenant_id, org_id, quota_type, quota_limit, quota_unit, period, status, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, org_id, quota_type) WHERE deleted_at IS NULL |
| 54 | org_units | ✅ | tenant_id, name, parent_id, path_ids, path_names, type, status, sort_order, leader_user_id, description, created_by, created_at, updated_by, updated_at, deleted_at | metadata, settings | (tenant_id, parent_id, name) WHERE deleted_at IS NULL |
| 55 | organization_shortcut_schemes | 🔶 | tenant_id, name, description, scope_type, scope_ref, shortcuts, status, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, scope_type, scope_ref, name) WHERE deleted_at IS NULL |
| 56 | organization_skill_releases | ❌ | — | tenant_id, org_id, skill_id, release_id, status, approved_by, approved_at, created_at | — |
| 57 | organizations | ✅ | tenant_id, name, parent_id, path_ids, path_names, type, status, sort_order, description, contact_email, contact_phone, address, logo_url, settings, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, parent_id, name) WHERE deleted_at IS NULL |
| 58 | page_collection_settings | 🔶 | tenant_id, page_id, collection_id, settings, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, page_id, collection_id) WHERE deleted_at IS NULL |
| 59 | permission_grants | ❌ | — | tenant_id, grant_type, subject_type, subject_id, object_type, object_id, permissions, status, created_by, created_at, updated_by, updated_at, deleted_at | — |
| 60 | personal_knowledge_directories | ✅ | tenant_id, owner_user_id, parent_id, name, path_ids, path_names, status, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, owner_user_id, parent_id, name) WHERE deleted_at IS NULL |
| 61 | pii_policies | 🔶 | tenant_id, name, description, rules, enabled, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, name) WHERE deleted_at IS NULL |
| 62 | position_role_audit_logs | ❌ | — | tenant_id, position_role_id, action, actor_user_id, old_values, new_values, created_at | — |
| 63 | position_role_migrations | ❌ | — | tenant_id, migration_id, from_version, to_version, status, started_at, completed_at, error, created_at | — |
| 64 | position_roles | ✅ | tenant_id, name, description, type, level, status, sort_order, created_by, created_at, updated_by, updated_at, deleted_at | metadata, requirements | (tenant_id, name) WHERE deleted_at IS NULL |
| 65 | presence_heartbeats | ❌ | — | tenant_id, user_id, session_id, status, last_active_at, created_at | — |
| 66 | presentation_generation_jobs | ❌ | — | tenant_id, job_id, presentation_id, status, progress, result, error, started_at, completed_at, created_at | — |
| 67 | project_memories | ❌ | — | tenant_id, project_id, user_id, memory_type, content, metadata, created_at, updated_at | — |
| 68 | quota_counters | ❌ | — | tenant_id, quota_type, entity_type, entity_id, used, limit, period, created_at, updated_at | — |
| 69 | resource_comment_reactions | ✅ | tenant_id, comment_id, user_id, reaction, created_at | — | (tenant_id, comment_id, user_id, reaction) |
| 70 | resource_comments | ✅ | tenant_id, resource_type, resource_id, user_id, author, content, parent_id, root_id, reply_to, status, release_id, release_version, created_at, updated_at | — | (tenant_id, resource_type, resource_id, created_at) |
| 71 | resource_feedback_notifications | ✅ | tenant_id, resource_type, resource_id, recipient_user_id, actor, comment_id, kind, status, read_at, created_at | — | (tenant_id, recipient_user_id, status, created_at) |
| 72 | resource_grants | ✅ | tenant_id, resource_type, resource_id, recipient_user_id, granted_by_user_id, can_reshare, status, revoked_at, revoked_by_user_id, revoke_reason, seen_at, created_at, updated_at | — | (tenant_id, resource_type, resource_id, recipient_user_id) |
| 73 | resource_reactions | ✅ | tenant_id, resource_type, resource_id, user_id, reaction, created_at | — | (tenant_id, resource_type, resource_id, user_id, reaction) |
| 74 | risk_tiers | 🔶 | tenant_id, name, description, level, rules, enabled, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, name) WHERE deleted_at IS NULL |
| 75 | runtime_action_receipts | ❌ | — | tenant_id, action_id, receipt_type, status, payload, created_at | — |
| 76 | runtime_profile_audit | ❌ | — | tenant_id, profile_id, action, actor_user_id, old_values, new_values, created_at | — |
| 77 | runtime_profile_versions | ❌ | — | tenant_id, profile_id, version, data, status, created_by, created_at | — |
| 78 | runtime_suspensions | ❌ | — | tenant_id, suspension_id, target_type, target_id, reason, status, created_at, updated_at | — |
| 79 | scheduled_job_runs | ❌ | — | tenant_id, job_id, run_id, status, progress, result, error, started_at, completed_at, created_at | — |
| 80 | scheduled_jobs | 🔶 | tenant_id, name, description, schedule_type, schedule_expr, job_type, job_config, status, enabled, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, name) WHERE deleted_at IS NULL |
| 81 | session_presence_state | ❌ | — | tenant_id, session_id, user_id, presence, last_seen_at, created_at, updated_at | — |
| 82 | session_secret_refs | ❌ | — | tenant_id, session_id, secret_type, secret_ref, status, created_at, updated_at | — |
| 83 | session_shares | ❌ | — | tenant_id, session_id, share_type, sharee_user_id, status, expires_at, created_at | — |
| 84 | session_snapshots | ❌ | — | tenant_id, session_id, snapshot_data, status, created_at | — |
| 85 | site_profiles | 🔶 | tenant_id, name, description, domain, status, theme, settings, created_by, created_at, updated_by, updated_at, deleted_at | metadata, pages | (tenant_id, name) WHERE deleted_at IS NULL |
| 86 | skill_adoption | ❌ | — | tenant_id, skill_id, user_id, adopted, adopted_at, created_at, updated_at | — |
| 87 | skill_distribution_members | ❌ | — | tenant_id, distribution_id, user_id, status, granted_at, created_at, updated_at | — |
| 88 | skill_distribution_releases | ❌ | — | tenant_id, distribution_id, release_id, status, released_at, created_at | — |
| 89 | skill_distributions | ❌ | — | tenant_id, name, description, skill_id, scope_type, scope_ref, status, created_by, created_at, updated_by, updated_at, deleted_at | — |
| 90 | skill_drafts | ❌ | — | tenant_id, skill_id, draft_data, status, created_by, created_at, updated_by, updated_at | — |
| 91 | skill_packages | ❌ | — | tenant_id, skill_id, package_data, version, status, created_by, created_at | — |
| 92 | skill_product_edit_events | ❌ | — | tenant_id, skill_id, event_type, actor_user_id, payload, created_at | — |
| 93 | skill_quality_collector_state | ❌ | — | tenant_id, skill_id, collector_type, status, data, created_at, updated_at | — |
| 94 | skill_quality_metrics | ❌ | — | tenant_id, skill_id, metric_type, value, period, created_at | — |
| 95 | skill_releases | ❌ | — | tenant_id, skill_id, release_id, version, data, status, released_at, created_at | — |
| 96 | skill_rollouts | ❌ | — | tenant_id, skill_id, rollout_id, status, progress, target_users, created_at, updated_at | — |
| 97 | skill_share_deliveries | ❌ | — | tenant_id, share_id, delivery_id, target_user_id, status, delivered_at, created_at | — |
| 98 | skill_shares | ❌ | — | tenant_id, skill_id, share_type, sharee_user_id, status, granted_at, created_at, updated_at | — |
| 99 | skill_update_notifications | ❌ | — | tenant_id, skill_id, user_id, notification_type, status, read_at, created_at | — |
| 100 | skills | ✅ | tenant_id, name, description, type, status, version, data, created_by, created_at, updated_by, updated_at, deleted_at | metadata, tags | (tenant_id, name) WHERE deleted_at IS NULL |
| 101 | system_audit_logs | ❌ | — | tenant_id, log_type, level, message, context, stack_trace, created_at | — |
| 102 | system_bootstrap | ❌ | — | tenant_id, bootstrap_id, status, data, created_at, updated_at | — |
| 103 | tenant_purge_progress | ❌ | — | tenant_id, purge_id, status, progress, result, error, started_at, completed_at, created_at | — |
| 104 | tenants | ✅ | tenant_id, name, description, status, contact_email, contact_phone, address, logo_url, settings, created_by, created_at, updated_by, updated_at, deleted_at | metadata | (tenant_id, name) WHERE deleted_at IS NULL |
| 105 | token_usage_logs | ❌ | — | tenant_id, user_id, token_type, amount, period, created_at | — |
| 106 | user_field_defs | ❌ | — | tenant_id, field_id, field_name, field_type, status, created_by, created_at, updated_by, updated_at | — |
| 107 | user_field_values | ❌ | — | tenant_id, user_id, field_id, value, created_at, updated_at | — |
| 108 | user_identities | ❌ | — | tenant_id, user_id, identity_type, provider, provider_user_id, status, created_at, updated_at | — |
| 109 | user_invites | ❌ | — | tenant_id, invite_id, invitee_email, invitee_name, role_type, status, expires_at, created_by, created_at | — |
| 110 | user_quota_overrides | ❌ | — | tenant_id, user_id, quota_type, quota_limit, quota_unit, period, status, created_by, created_at, updated_by, updated_at, deleted_at | — |
| 111 | user_quota_policies | ❌ | — | tenant_id, user_id, quota_type, quota_limit, quota_unit, period, status, created_by, created_at, updated_by, updated_at, deleted_at | — |
| 112 | user_shortcut_preferences | ❌ | — | tenant_id, user_id, shortcut_id, preferences, created_at, updated_at | — |
| 113 | user_skills | ❌ | — | tenant_id, user_id, skill_id, status, proficiency, created_at, updated_at | — |
| 114 | user_token_allocation_logs | ❌ | — | tenant_id, user_id, token_type, amount, period, created_at | — |

### 统计

| 决策类型 | 数量 | 占比 |
|---------|------|------|
| ✅ 扁平化（全字段平铺） | 24 | 21.1% |
| 🔶 部分扁平化（核心平铺 + 动态保留 doc） | 30 | 26.3% |
| ❌ 不扁平化（保持 doc JSONB） | 60 | 52.6% |
| **合计** | **114** | **100%** |

---

## 4. 按域详细方案

### 4.1 账号域

| 表名 | 决策 | 关键变化 |
|------|------|---------|
| admin_accounts | ✅ | login_name/password_hash/status 等核心字段平铺；preferences/recovery_codes 保留在 doc |
| end_users | ✅ | 与 admin_accounts 类似，增加 tenant_id 约束 |
| admin_account_groups | 🔶 | name/parent_id/status/sort_order 平铺；metadata/settings 保留在 doc |
| admin_model_instances | 🔶 | provider_id/model_key/base_url/api_key_encrypted 平铺；config/headers 保留在 doc |
| admin_model_providers | ✅ | name/base_url/auth_type/api_key_encrypted 平铺；config/headers 保留在 doc |
| admin_presentation_settings | 🔶 | theme/font_family/color_* 平铺；custom_css/layout_overrides 保留在 doc |
| agent_kernel_bindings | 🔶 | kernel_type/kernel_id/binding_type/binding_ref 平铺；config/metadata 保留在 doc |
| end_user_capability_overrides | 🔶 | user_id/capability_key/enabled/value 平铺；metadata 保留在 doc |
| end_user_org_relations | ✅ | user_id/org_id/position_id/role_type/status 平铺；metadata 保留在 doc |
| end_user_position_roles | ✅ | user_id/position_id/role_name/role_type/status 平铺；metadata 保留在 doc |
| admin_login_challenges | ❌ | 一次性挑战码，仅按 id/tenant_id 查询 |
| admin_recovery_tokens | ❌ | 一次性令牌，仅按 id/tenant_id 查询 |
| admin_refresh_tokens | ❌ | 会话令牌，仅按 id/tenant_id 查询 |
| admin_sessions | ❌ | 会话令牌，仅按 id/tenant_id 查询 |
| end_user_login_challenges | ❌ | 一次性挑战码 |
| end_user_sessions | ❌ | 会话令牌 |
| mfa_lockouts | ❌ | 锁定状态，低频查询 |
| mfa_used_steps | ❌ | MFA 步骤记录 |
| user_identities | ❌ | 身份关联，结构简单 |
| user_invites | ❌ | 邀请记录，低频查询 |

### 4.2 会话/聊天域

| 表名 | 决策 | 关键变化 |
|------|------|---------|
| chat_sessions | ✅ | type/title/owner_user_id/participant_ids/status/last_message_* 平铺；metadata/settings 保留在 doc |
| chat_messages | 🔶 | session_id/sender_type/sender_id/content/content_type/status 平铺；attachments/metadata/reactions 保留在 doc |
| im_channels | ✅ | type/name/owner_user_id/member_ids/status/last_message_* 平铺；metadata/settings 保留在 doc |
| im_session_bindings | ❌ | 会话-通道绑定，仅按 id/tenant_id 查询 |
| session_presence_state | ❌ | 在线状态，高频写入低频查询 |
| session_secret_refs | ❌ | 密钥引用，安全敏感 |
| session_shares | ❌ | 会话共享记录 |
| session_snapshots | ❌ | 会话快照，大对象 |

### 4.3 组织域

| 表名 | 决策 | 关键变化 |
|------|------|---------|
| org_units | ✅ | name/parent_id/path_ids/path_names/type/status/sort_order/leader_user_id 平铺；metadata/settings 保留在 doc |
| organizations | ✅ | name/parent_id/path_ids/path_names/type/status/contact_* 平铺；metadata 保留在 doc |
| position_roles | ✅ | name/description/type/level/status/sort_order 平铺；metadata/requirements 保留在 doc |
| org_quota_policies | 🔶 | org_id/quota_type/quota_limit/quota_unit/period/status 平铺；metadata 保留在 doc |
| organization_shortcut_schemes | 🔶 | name/scope_type/scope_ref/shortcuts/status 平铺；metadata 保留在 doc |
| page_collection_settings | 🔶 | page_id/collection_id/settings 平铺；metadata 保留在 doc |
| pii_policies | 🔶 | name/rules/enabled 平铺；metadata 保留在 doc |
| risk_tiers | 🔶 | name/description/level/rules/enabled 平铺；metadata 保留在 doc |
| position_role_audit_logs | ❌ | 审计日志，仅按 id/tenant_id 查询 |
| position_role_migrations | ❌ | 迁移记录 |
| user_field_defs | ❌ | 字段定义，结构简单 |
| user_field_values | ❌ | 字段值，结构简单 |
| user_quota_overrides | ❌ | 配额覆盖 |
| user_quota_policies | ❌ | 配额策略 |
| user_shortcut_preferences | ❌ | 快捷键偏好 |

### 4.4 技能域

| 表名 | 决策 | 关键变化 |
|------|------|---------|
| skills | ✅ | name/description/type/status/version/data 平铺；metadata/tags 保留在 doc |
| external_tools | 🔶 | name/description/base_url/auth_type/api_key_encrypted 平铺；config/headers/capabilities 保留在 doc |
| external_search_configs | 🔶 | name/provider/api_key_encrypted/endpoint 平铺；config/query_templates 保留在 doc |
| gatekeeper_rules | 🔶 | name/description/rule_type/condition/action/priority/enabled 平铺；config/metadata 保留在 doc |
| harness_profiles | 🔶 | name/description/type/config/status 平铺；variables/hooks 保留在 doc |
| hook_rules | 🔶 | name/description/event_type/condition/action/priority/enabled 平铺；config/metadata 保留在 doc |
| agent_kernel_bindings | 🔶 | 见账号域说明 |
| dag_definitions | 🔶 | name/description/graph_data/version/status 平铺；schedule/triggers/variables 保留在 doc |
| scheduled_jobs | 🔶 | name/description/schedule_type/schedule_expr/job_type/job_config/status/enabled 平铺；metadata 保留在 doc |
| site_profiles | 🔶 | name/description/domain/status/theme/settings 平铺；metadata/pages 保留在 doc |
| skill_adoption | ❌ | 采纳记录 |
| skill_distribution_members | ❌ | 分发成员 |
| skill_distribution_releases | ❌ | 分发版本 |
| skill_distributions | ❌ | 分发记录 |
| skill_drafts | ❌ | 草稿 |
| skill_packages | ❌ | 包数据 |
| skill_product_edit_events | ❌ | 编辑事件 |
| skill_quality_collector_state | ❌ | 质量采集状态 |
| skill_quality_metrics | ❌ | 质量指标 |
| skill_releases | ❌ | 版本发布 |
| skill_rollouts | ❌ | 灰度发布 |
| skill_share_deliveries | ❌ | 分发交付 |
| skill_shares | ❌ | 分享记录 |
| skill_update_notifications | ❌ | 更新通知 |
| user_skills | ❌ | 用户技能关联 |

### 4.5 知识域

| 表名 | 决策 | 关键变化 |
|------|------|---------|
| knowledge_documents | ✅ | **完整平铺**：40+ 字段全部平铺为真实列（含 storage_*, parse_*, chunk_*, index_*, preview_*, tags, created_by 等），仅 metadata 保留在 doc |
| knowledge_directories | ✅ | name/parent_id/path_ids/path_names/scope 平铺；metadata 保留在 doc |
| knowledge_resources | ✅ | owner_user_id/directory_id/name/description/tags/share_policy/active_document_id/processing_document_id/status/error 平铺 |
| personal_knowledge_directories | ✅ | 与 knowledge_directories 类似，增加 owner_user_id 约束 |
| knowledge_document_chunks | 🔶 | document_id/chunk_id/chunk_stage/ordinal/text/contextual_text/title_path/page_no/content_type/source_chunk_ids/status 平铺；metadata 保留在 doc |
| knowledge_document_settings | 🔶 | tenant_id/kind/config 平铺（config 保留在 doc 中，但顶层字段平铺） |

### 4.6 资源/反馈域

| 表名 | 决策 | 关键变化 |
|------|------|---------|
| resource_comments | ✅ | tenant_id/resource_type/resource_id/user_id/author/content/parent_id/root_id/reply_to/status/release_id/release_version 平铺 |
| resource_comment_reactions | ✅ | tenant_id/comment_id/user_id/reaction 平铺（全表仅 5 列） |
| resource_reactions | ✅ | tenant_id/resource_type/resource_id/user_id/reaction 平铺（全表仅 6 列） |
| resource_grants | ✅ | tenant_id/resource_type/resource_id/recipient_user_id/granted_by_user_id/can_reshare/status/revoked_at/revoked_by_user_id/revoke_reason/seen_at 平铺 |
| resource_feedback_notifications | ✅ | tenant_id/resource_type/resource_id/recipient_user_id/actor/comment_id/kind/status/read_at 平铺 |

### 4.7 审计/治理/日志域

> 本域 60 张表中，仅 6 张适合部分扁平化（autonomy_matrix、business_entity_index 除外），其余全部保持 doc JSONB。
> 理由：审计日志、事件流、治理记录等场景下，查询模式几乎总是「按 tenant_id + 时间范围」，且字段结构动态、写入频繁，扁平化收益极低。

---

## 5. 兼容层改造要点

### 5.1 写入路径

对于 ✅ 和 🔶 扁平化表：

```python
# 写入时：同时更新 doc 和对应列
async def insert_row(table: str, doc: dict) -> str:
    row_id = doc["_id"]
    columns = COLUMN_MAP.get(table, {})
    flat_values = {col: doc.get(key) for key, col in columns.items()}
    await db[table].insert_one({**flat_values, "id": row_id, "tenant_id": doc["tenant_id"], "doc": doc})
    return row_id
```

### 5.2 读取路径

```python
# 读取时：以列值拼回 doc
async def get_row(table: str, row_id: str) -> dict | None:
    row = await db[table].find_one({"id": row_id})
    if row is None:
        return None
    doc = row.get("doc", {})
    columns = COLUMN_MAP.get(table, {})
    for key, col in columns.items():
        if col in row and row[col] is not None:
            doc[key] = row[col]
    return doc
```

### 5.3 筛选路径

```python
# 筛选时：COLUMN_MAP 命中的键走真实列，其余走 doc JSONB 路径
def build_filter(table: str, conditions: dict) -> dict:
    columns = COLUMN_MAP.get(table, {})
    mongo_query = {}
    for key, value in conditions.items():
        if key in columns:
            mongo_query[columns[key]] = value
        else:
            mongo_query[f"doc.{key}"] = value
    return mongo_query
```

### 5.4 兼容层映射表

需要维护 `COLUMN_MAP`，记录每个表的 `doc_key → column_name` 映射。对于 ❌ 不扁平化的表，COLUMN_MAP 为空。

---

## 6. 实施路线图

### Phase 1: 核心账号表（优先级 P0）

| 表 | 工作量 | 说明 |
|----|--------|------|
| end_users | 2d | 账号核心表，所有关联的入口 |
| admin_accounts | 2d | 管理后台入口 |
| tenants | 1d | 租户信息 |

### Phase 2: 组织域（优先级 P0）

| 表 | 工作量 | 说明 |
|----|--------|------|
| organizations | 2d | 组织架构根 |
| org_units | 2d | 组织单元 |
| position_roles | 1d | 岗位角色 |
| end_user_org_relations | 1d | 用户-组织关系 |
| end_user_position_roles | 1d | 用户-岗位关系 |

### Phase 3: 知识域（优先级 P1）

| 表 | 工作量 | 说明 |
|----|--------|------|
| knowledge_documents | 5d | 最大最复杂，40+ 字段 |
| knowledge_document_chunks | 3d | 大文本字段多 |
| knowledge_directories | 1d | 目录结构 |
| knowledge_resources | 1d | 个人知识资源 |
| personal_knowledge_directories | 1d | 个人知识目录 |
| knowledge_document_settings | 1d | 设置配置 |

### Phase 4: 资源/反馈域（优先级 P1）

| 表 | 工作量 | 说明 |
|----|--------|------|
| resource_comments | 2d | 评论系统 |
| resource_comment_reactions | 0.5d | 评论点赞 |
| resource_reactions | 0.5d | 资源点赞 |
| resource_grants | 1d | 权限授予 |
| resource_feedback_notifications | 1d | 通知系统 |

### Phase 5: 会话/技能域（优先级 P2）

| 表 | 工作量 | 说明 |
|----|--------|------|
| chat_sessions | 1d | 会话管理 |
| chat_messages | 2d | 消息记录 |
| im_channels | 1d | IM 通道 |
| skills | 2d | 技能核心表 |
| external_tools | 1d | 外部工具 |
| external_search_configs | 1d | 外部搜索配置 |
| 其余 🔶 表 | 3d | 批量处理 |

### Phase 6: 审计/治理域（优先级 P3）

| 表 | 工作量 | 说明 |
|----|--------|------|
| 全部 60 张 ❌ 表 | 0d | 保持 doc JSONB，无需改造 |
| 6 张 🔶 表 | 2d | 按需扁平化 |

**总预估工作量**: 约 35-40 人日

---

## 7. 风险与回滚

### 7.1 风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 兼容层改造引入 bug | 高 | 完整的集成测试覆盖 |
| 扁平化后查询性能不升反降 | 中 | 先在测试环境压测验证 |
| 字段映射遗漏导致数据不一致 | 高 | 双写期对账脚本 |
| 大表 ALTER 锁表影响线上服务 | 中 | 分批执行，低峰期操作 |

### 7.2 回滚策略

1. **双写期**：同时写入 doc 和列，读取以列为准
2. **对账期**：运行对账脚本，确保 doc 与列数据一致
3. **观察期**：稳定运行 1 周后，再移除 doc 写入
4. **快速回滚**：保留 doc 字段不删除，出问题时回退读取路径即可

---

## 8. 附录

### A. 字段类型映射规则

| MongoDB 类型 | openGauss A 模式类型 | 备注 |
|-------------|-------------------|------|
| string | TEXT | — |
| int32/int64 | INTEGER/BIGINT | — |
| float/double | DOUBLE PRECISION | — |
| bool | BOOLEAN | — |
| datetime | TIMESTAMPTZ | — |
| array | JSONB | 保留为 JSONB 数组 |
| object (嵌套) | JSONB | 保留为 JSONB 对象 |
| ObjectID | TEXT | 已是 TEXT |
| dict (动态) | JSONB | 保留在 doc 中 |

### B. 索引设计原则

- 每个表至少包含 `tenant_id` btree 索引（建表 DDL 已包含）
- 高频查询字段添加复合索引，字段顺序按等值条件 > 范围条件 > 排序字段
- 唯一索引使用 `WHERE deleted_at IS NULL` 实现软删除唯一约束
- 扁平化后的 TEXT 字段不建 GIN 索引（openGauss A 模式限制）

### C. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-10-15 | v1.0 | 初版：完成 114 张表的全域扁平化方案设计 |