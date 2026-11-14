-- 03b 修正回填: 仅高/中置信度映射列 (待用户确认后执行)

UPDATE mogo_dev.admin_accounts SET login_name = CAST(doc->>'username' AS TEXT) WHERE doc->>'username' IS NOT NULL;
UPDATE mogo_dev.admin_accounts SET name = CAST(doc->>'display_name' AS TEXT) WHERE doc->>'display_name' IS NOT NULL;
UPDATE mogo_dev.admin_model_instances SET model_key = CAST(doc->>'model_name' AS TEXT) WHERE doc->>'model_name' IS NOT NULL;
UPDATE mogo_dev.admin_model_instances SET label = CAST(doc->>'display_name' AS TEXT) WHERE doc->>'display_name' IS NOT NULL;
UPDATE mogo_dev.admin_model_instances SET sort_order = CAST(doc->>'priority' AS INTEGER) WHERE doc->>'priority' IS NOT NULL;
UPDATE mogo_dev.admin_model_providers SET base_url = CAST(doc->>'default_base_url' AS TEXT) WHERE doc->>'default_base_url' IS NOT NULL;
UPDATE mogo_dev.admin_model_providers SET sort_order = CAST(doc->>'priority' AS INTEGER) WHERE doc->>'priority' IS NOT NULL;
UPDATE mogo_dev.agent_kernel_bindings SET kernel_type = CAST(doc->>'kernel' AS TEXT) WHERE doc->>'kernel' IS NOT NULL;
UPDATE mogo_dev.agent_kernel_bindings SET kernel_id = CAST(doc->>'kernel_session_id' AS TEXT) WHERE doc->>'kernel_session_id' IS NOT NULL;
UPDATE mogo_dev.agent_kernel_bindings SET binding_ref = CAST(doc->>'source_ref' AS TEXT) WHERE doc->>'source_ref' IS NOT NULL;
UPDATE mogo_dev.chat_messages SET sender_type = CAST(doc->>'role' AS TEXT) WHERE doc->>'role' IS NOT NULL;
UPDATE mogo_dev.chat_messages SET sender_id = CAST(doc->>'user_id' AS TEXT) WHERE doc->>'user_id' IS NOT NULL;
UPDATE mogo_dev.chat_sessions SET owner_user_id = CAST(doc->>'user_id' AS TEXT) WHERE doc->>'user_id' IS NOT NULL;
UPDATE mogo_dev.end_user_position_roles SET position_id = CAST(doc->>'role_id' AS TEXT) WHERE doc->>'role_id' IS NOT NULL;
UPDATE mogo_dev.end_users SET display_name = CAST(doc->>'name' AS TEXT) WHERE doc->>'name' IS NOT NULL;
UPDATE mogo_dev.end_users SET phone = CAST(doc->>'mobile' AS TEXT) WHERE doc->>'mobile' IS NOT NULL;
UPDATE mogo_dev.external_search_configs SET name = CAST(doc->>'provider' AS TEXT) WHERE doc->>'provider' IS NOT NULL;
UPDATE mogo_dev.external_search_configs SET sort_order = CAST(doc->>'priority' AS INTEGER) WHERE doc->>'priority' IS NOT NULL;
UPDATE mogo_dev.org_quota_policies SET quota_limit = CAST(doc->>'total_tokens' AS BIGINT) WHERE doc->>'total_tokens' IS NOT NULL;
UPDATE mogo_dev.organizations SET name = CAST(doc->>'org_name' AS TEXT) WHERE doc->>'org_name' IS NOT NULL;
UPDATE mogo_dev.pii_policies SET name = CAST(doc->>'pii_type' AS TEXT) WHERE doc->>'pii_type' IS NOT NULL;
UPDATE mogo_dev.pii_policies SET rules = doc->'strategy' WHERE doc->'strategy' IS NOT NULL;
UPDATE mogo_dev.skills SET version = CAST(doc->>'package_version' AS TEXT) WHERE doc->>'package_version' IS NOT NULL;
UPDATE mogo_dev.skills SET data = doc->'config' WHERE doc->'config' IS NOT NULL;
