# 列名 vs doc key 匹配分析报告 (027-R3 回填映射)

平铺表数: 44; 有数据且存在缺失列的表: 20; 缺失列总数(仅统计有数据表): 107
空表(无 doc 数据, 回填 trivially 完成, 跳过): 22

说明: '缺失列' = 该列名(及 camelCase 形式)在 doc 中均找不到同名 key, 需确认语义别名(doc_key)才能正确回填。

## admin_account_groups  [缺失 2 列 / doc keys 8 个]
缺失列: parent_id, sort_order
doc 实际 keys: _id, code, created_at, description, name, status, tenant_id, updated_at

## admin_accounts  [缺失 8 列 / doc keys 16 个]
缺失列: login_name, password_algorithm, name, avatar_url, failed_login_count, locked_at, last_login_ip, mfa_enabled
doc 实际 keys: _id, created_at, display_name, email, group_code, is_protected, last_login_at, org_name, password_hash, password_salt, phone, role_name, status, tenant_id, updated_at, username

## admin_model_instances  [缺失 4 列 / doc keys 21 个]
缺失列: model_key, label, auth_type, sort_order
doc 实际 keys: _id, api_key_encrypted, api_key_masked, api_secret_encrypted, api_secret_masked, api_version, base_url, capabilities, created_at, display_name, health_status, is_default, last_error, max_context_tokens, model_name, org_id, priority, provider_id, status, tenant_id, updated_at

## admin_model_providers  [缺失 4 列 / doc keys 10 个]
缺失列: base_url, api_key_encrypted, is_default, sort_order
doc 实际 keys: _id, auth_type, code, created_at, default_base_url, name, priority, provider_type, status, updated_at

## agent_kernel_bindings  [缺失 4 列 / doc keys 29 个]
缺失列: kernel_type, kernel_id, binding_type, binding_ref
doc 实际 keys: _id, active_turn, base_commit, binding_id, conversation_id, created_at, current, detached_head, device_id, dsh_workspace_id, event_cursor, execution_location, execution_mode, git_branch, kernel, kernel_session_id, kernel_version, model_instance_id, preset_id, profile_version, replaces_binding_id, runtime_id, source_ref, source_workspace_id, status, tenant_id, updated_at, user_id, worktree

## autonomy_matrix  [缺失 6 列 / doc keys 5 个]
缺失列: name, description, scope_type, scope_ref, rules, enabled
doc 实际 keys: _id, cell, decision, level, risk

## chat_messages  [缺失 6 列 / doc keys 14 个]
缺失列: sender_type, sender_id, content_type, status, parent_id, reply_to_id
doc 实际 keys: _id, content, created_at, documents, evidence_bundles, execution_events, images, message_id, role, runtime_owner, seq, session_id, tenant_id, user_id

## chat_sessions  [缺失 5 列 / doc keys 11 个]
缺失列: type, owner_user_id, participant_ids, status, last_message_id
doc 实际 keys: _id, created_at, last_message_at, last_message_preview, message_count, next_message_seq, runtime_owner, tenant_id, title, updated_at, user_id

## end_user_org_relations  [缺失 5 列 / doc keys 7 个]
缺失列: position_id, role_type, status, start_date, end_date
doc 实际 keys: _id, created_at, is_primary, org_id, tenant_id, updated_at, user_id

## end_user_position_roles  [缺失 6 列 / doc keys 9 个]
缺失列: position_id, role_name, role_type, status, start_date, end_date
doc 实际 keys: _id, created_at, created_by, is_primary, role_id, tenant_id, updated_at, updated_by, user_id

## end_users  [缺失 8 列 / doc keys 17 个]
缺失列: display_name, phone, avatar_url, password_algorithm, failed_login_count, locked_at, last_login_ip, mfa_enabled
doc 实际 keys: _id, created_at, email, last_login_at, login_name, mobile, name, org_name, password_hash, password_salt, primary_org_id, source, source_user_id, space_type, status, tenant_id, updated_at

## external_search_configs  [缺失 5 列 / doc keys 13 个]
缺失列: name, api_key_encrypted, endpoint, status, sort_order
doc 实际 keys: _id, config, created_at, enabled, health_status, is_default, last_error, last_test_at, priority, provider, tenant_id, updated_at, updated_by

## gatekeeper_rules  [缺失 7 列 / doc keys 6 个]
缺失列: name, description, rule_type, condition, action, priority, enabled
doc 实际 keys: _id, audit_enabled, enabled_layers, kind, mode, tenant_overrides

## org_quota_policies  [缺失 4 列 / doc keys 10 个]
缺失列: org_id, quota_type, quota_limit, quota_unit
doc 实际 keys: _id, created_at, period, status, tenant_id, timezone, total_tokens, unlimited, updated_at, updated_by

## org_units  [缺失 4 列 / doc keys 12 个]
缺失列: type, sort_order, leader_user_id, description
doc 实际 keys: _id, code, created_at, name, parent_id, path_ids, path_names, source, source_dept_id, status, tenant_id, updated_at

## organizations  [缺失 13 列 / doc keys 14 个]
缺失列: name, parent_id, path_ids, path_names, type, status, sort_order, description, contact_email, contact_phone, address, logo_url, settings
doc 实际 keys: _id, billing_enabled, created_at, edition, is_own_model, org_name, owner_user_id, points_unlimited, tenant_id, tier, total_points, updated_at, used_points, user_limit

## pii_policies  [缺失 4 列 / doc keys 4 个]
缺失列: name, description, rules, enabled
doc 实际 keys: _id, pii_type, strategy, tenant_id

## position_roles  [缺失 3 列 / doc keys 14 个]
缺失列: type, level, sort_order
doc 实际 keys: _id, capabilities, created_at, description, name, protected, skill_access_mode, skill_ids, status, system_key, tenant_id, tool_access_mode, tool_ids, updated_at

## skills  [缺失 3 列 / doc keys 45 个]
缺失列: status, version, data
doc 实际 keys: _id, advanced, category, config, contract_json, created_at, description, enabled, execution_plane, formats, input_profile, is_active, model_invocable, name, notes, package_children, package_declared_tools, package_digest, package_files, package_id, package_kind, package_market_metadata, package_referenced_tools, package_slug, package_source, package_version, package_warnings, resources, role, scenario, skill_contract, skill_contract_version, skill_lint_warnings, skill_markdown, skill_object_path, skill_type, source_kind, sources, summary, tags, tenant_id, type, updated_at, user_invocable, visibility

## tenants  [缺失 6 列 / doc keys 10 个]
缺失列: description, contact_email, contact_phone, address, logo_url, settings
doc 实际 keys: _id, admin_username, created_at, created_by, edition, member_limit, name, status, tenant_id, updated_at
