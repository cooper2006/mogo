-- 由 scripts/pg/generate_ddl.py 生成，请勿手工编辑。
-- 表结构约定见 docs/mongo-to-panweidb-migration-plan.md。

CREATE SCHEMA IF NOT EXISTS "mogo_dev";

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_account_groups" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_account_groups_tenant_idx" ON "mogo_dev"."admin_account_groups" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_account_groups_doc_gin" ON "mogo_dev"."admin_account_groups" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_accounts" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_accounts_tenant_idx" ON "mogo_dev"."admin_accounts" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_accounts_doc_gin" ON "mogo_dev"."admin_accounts" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_login_challenges" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_login_challenges_tenant_idx" ON "mogo_dev"."admin_login_challenges" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_login_challenges_doc_gin" ON "mogo_dev"."admin_login_challenges" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_model_instances" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_model_instances_tenant_idx" ON "mogo_dev"."admin_model_instances" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_model_instances_doc_gin" ON "mogo_dev"."admin_model_instances" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_model_providers" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_model_providers_tenant_idx" ON "mogo_dev"."admin_model_providers" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_model_providers_doc_gin" ON "mogo_dev"."admin_model_providers" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_presentation_settings" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_presentation_settings_tenant_idx" ON "mogo_dev"."admin_presentation_settings" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_presentation_settings_doc_gin" ON "mogo_dev"."admin_presentation_settings" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_recovery_tokens" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_recovery_tokens_tenant_idx" ON "mogo_dev"."admin_recovery_tokens" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_recovery_tokens_doc_gin" ON "mogo_dev"."admin_recovery_tokens" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_refresh_tokens" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_refresh_tokens_tenant_idx" ON "mogo_dev"."admin_refresh_tokens" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_refresh_tokens_doc_gin" ON "mogo_dev"."admin_refresh_tokens" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."admin_sessions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "admin_sessions_tenant_idx" ON "mogo_dev"."admin_sessions" (tenant_id);
CREATE INDEX IF NOT EXISTS "admin_sessions_doc_gin" ON "mogo_dev"."admin_sessions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."agent_kernel_bindings" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "agent_kernel_bindings_tenant_idx" ON "mogo_dev"."agent_kernel_bindings" (tenant_id);
CREATE INDEX IF NOT EXISTS "agent_kernel_bindings_doc_gin" ON "mogo_dev"."agent_kernel_bindings" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."approval_events" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "approval_events_tenant_idx" ON "mogo_dev"."approval_events" (tenant_id);
CREATE INDEX IF NOT EXISTS "approval_events_doc_gin" ON "mogo_dev"."approval_events" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."audit_events" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "audit_events_tenant_idx" ON "mogo_dev"."audit_events" (tenant_id);
CREATE INDEX IF NOT EXISTS "audit_events_doc_gin" ON "mogo_dev"."audit_events" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."audit_logs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "audit_logs_tenant_idx" ON "mogo_dev"."audit_logs" (tenant_id);
CREATE INDEX IF NOT EXISTS "audit_logs_doc_gin" ON "mogo_dev"."audit_logs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."autonomy_matrix" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "autonomy_matrix_tenant_idx" ON "mogo_dev"."autonomy_matrix" (tenant_id);
CREATE INDEX IF NOT EXISTS "autonomy_matrix_doc_gin" ON "mogo_dev"."autonomy_matrix" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."business_entity_index" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "business_entity_index_tenant_idx" ON "mogo_dev"."business_entity_index" (tenant_id);
CREATE INDEX IF NOT EXISTS "business_entity_index_doc_gin" ON "mogo_dev"."business_entity_index" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."chat_messages" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "chat_messages_tenant_idx" ON "mogo_dev"."chat_messages" (tenant_id);
CREATE INDEX IF NOT EXISTS "chat_messages_doc_gin" ON "mogo_dev"."chat_messages" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."chat_sessions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "chat_sessions_tenant_idx" ON "mogo_dev"."chat_sessions" (tenant_id);
CREATE INDEX IF NOT EXISTS "chat_sessions_doc_gin" ON "mogo_dev"."chat_sessions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."dag_definitions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "dag_definitions_tenant_idx" ON "mogo_dev"."dag_definitions" (tenant_id);
CREATE INDEX IF NOT EXISTS "dag_definitions_doc_gin" ON "mogo_dev"."dag_definitions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."desktop_projects" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "desktop_projects_tenant_idx" ON "mogo_dev"."desktop_projects" (tenant_id);
CREATE INDEX IF NOT EXISTS "desktop_projects_doc_gin" ON "mogo_dev"."desktop_projects" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."end_user_capability_overrides" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "end_user_capability_overrides_tenant_idx" ON "mogo_dev"."end_user_capability_overrides" (tenant_id);
CREATE INDEX IF NOT EXISTS "end_user_capability_overrides_doc_gin" ON "mogo_dev"."end_user_capability_overrides" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."end_user_login_challenges" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "end_user_login_challenges_tenant_idx" ON "mogo_dev"."end_user_login_challenges" (tenant_id);
CREATE INDEX IF NOT EXISTS "end_user_login_challenges_doc_gin" ON "mogo_dev"."end_user_login_challenges" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."end_user_org_relations" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "end_user_org_relations_tenant_idx" ON "mogo_dev"."end_user_org_relations" (tenant_id);
CREATE INDEX IF NOT EXISTS "end_user_org_relations_doc_gin" ON "mogo_dev"."end_user_org_relations" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."end_user_position_roles" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "end_user_position_roles_tenant_idx" ON "mogo_dev"."end_user_position_roles" (tenant_id);
CREATE INDEX IF NOT EXISTS "end_user_position_roles_doc_gin" ON "mogo_dev"."end_user_position_roles" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."end_user_sessions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "end_user_sessions_tenant_idx" ON "mogo_dev"."end_user_sessions" (tenant_id);
CREATE INDEX IF NOT EXISTS "end_user_sessions_doc_gin" ON "mogo_dev"."end_user_sessions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."end_users" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "end_users_tenant_idx" ON "mogo_dev"."end_users" (tenant_id);
CREATE INDEX IF NOT EXISTS "end_users_doc_gin" ON "mogo_dev"."end_users" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."enterprise_action_receipts" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "enterprise_action_receipts_tenant_idx" ON "mogo_dev"."enterprise_action_receipts" (tenant_id);
CREATE INDEX IF NOT EXISTS "enterprise_action_receipts_doc_gin" ON "mogo_dev"."enterprise_action_receipts" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."enterprise_authoritative_deliveries" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "enterprise_authoritative_deliveries_tenant_idx" ON "mogo_dev"."enterprise_authoritative_deliveries" (tenant_id);
CREATE INDEX IF NOT EXISTS "enterprise_authoritative_deliveries_doc_gin" ON "mogo_dev"."enterprise_authoritative_deliveries" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."execution_logs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "execution_logs_tenant_idx" ON "mogo_dev"."execution_logs" (tenant_id);
CREATE INDEX IF NOT EXISTS "execution_logs_doc_gin" ON "mogo_dev"."execution_logs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."experience_fragments" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "experience_fragments_tenant_idx" ON "mogo_dev"."experience_fragments" (tenant_id);
CREATE INDEX IF NOT EXISTS "experience_fragments_doc_gin" ON "mogo_dev"."experience_fragments" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."external_search_configs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "external_search_configs_tenant_idx" ON "mogo_dev"."external_search_configs" (tenant_id);
CREATE INDEX IF NOT EXISTS "external_search_configs_doc_gin" ON "mogo_dev"."external_search_configs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."external_tools" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "external_tools_tenant_idx" ON "mogo_dev"."external_tools" (tenant_id);
CREATE INDEX IF NOT EXISTS "external_tools_doc_gin" ON "mogo_dev"."external_tools" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."gate_approvals" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "gate_approvals_tenant_idx" ON "mogo_dev"."gate_approvals" (tenant_id);
CREATE INDEX IF NOT EXISTS "gate_approvals_doc_gin" ON "mogo_dev"."gate_approvals" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."gate_events" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "gate_events_tenant_idx" ON "mogo_dev"."gate_events" (tenant_id);
CREATE INDEX IF NOT EXISTS "gate_events_doc_gin" ON "mogo_dev"."gate_events" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."gatekeeper_rules" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "gatekeeper_rules_tenant_idx" ON "mogo_dev"."gatekeeper_rules" (tenant_id);
CREATE INDEX IF NOT EXISTS "gatekeeper_rules_doc_gin" ON "mogo_dev"."gatekeeper_rules" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."harness_profiles" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "harness_profiles_tenant_idx" ON "mogo_dev"."harness_profiles" (tenant_id);
CREATE INDEX IF NOT EXISTS "harness_profiles_doc_gin" ON "mogo_dev"."harness_profiles" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."hook_rules" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "hook_rules_tenant_idx" ON "mogo_dev"."hook_rules" (tenant_id);
CREATE INDEX IF NOT EXISTS "hook_rules_doc_gin" ON "mogo_dev"."hook_rules" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."im_channels" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "im_channels_tenant_idx" ON "mogo_dev"."im_channels" (tenant_id);
CREATE INDEX IF NOT EXISTS "im_channels_doc_gin" ON "mogo_dev"."im_channels" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."im_session_bindings" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "im_session_bindings_tenant_idx" ON "mogo_dev"."im_session_bindings" (tenant_id);
CREATE INDEX IF NOT EXISTS "im_session_bindings_doc_gin" ON "mogo_dev"."im_session_bindings" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."kernel_event_projections" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "kernel_event_projections_tenant_idx" ON "mogo_dev"."kernel_event_projections" (tenant_id);
CREATE INDEX IF NOT EXISTS "kernel_event_projections_doc_gin" ON "mogo_dev"."kernel_event_projections" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."knowledge_directories" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "knowledge_directories_tenant_idx" ON "mogo_dev"."knowledge_directories" (tenant_id);
CREATE INDEX IF NOT EXISTS "knowledge_directories_doc_gin" ON "mogo_dev"."knowledge_directories" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."knowledge_document_chunks" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "knowledge_document_chunks_tenant_idx" ON "mogo_dev"."knowledge_document_chunks" (tenant_id);
CREATE INDEX IF NOT EXISTS "knowledge_document_chunks_doc_gin" ON "mogo_dev"."knowledge_document_chunks" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."knowledge_document_settings" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "knowledge_document_settings_tenant_idx" ON "mogo_dev"."knowledge_document_settings" (tenant_id);
CREATE INDEX IF NOT EXISTS "knowledge_document_settings_doc_gin" ON "mogo_dev"."knowledge_document_settings" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."knowledge_documents" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "knowledge_documents_tenant_idx" ON "mogo_dev"."knowledge_documents" (tenant_id);
CREATE INDEX IF NOT EXISTS "knowledge_documents_doc_gin" ON "mogo_dev"."knowledge_documents" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."knowledge_resources" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "knowledge_resources_tenant_idx" ON "mogo_dev"."knowledge_resources" (tenant_id);
CREATE INDEX IF NOT EXISTS "knowledge_resources_doc_gin" ON "mogo_dev"."knowledge_resources" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."memories" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "memories_tenant_idx" ON "mogo_dev"."memories" (tenant_id);
CREATE INDEX IF NOT EXISTS "memories_doc_gin" ON "mogo_dev"."memories" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."mfa_lockouts" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "mfa_lockouts_tenant_idx" ON "mogo_dev"."mfa_lockouts" (tenant_id);
CREATE INDEX IF NOT EXISTS "mfa_lockouts_doc_gin" ON "mogo_dev"."mfa_lockouts" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."mfa_used_steps" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "mfa_used_steps_tenant_idx" ON "mogo_dev"."mfa_used_steps" (tenant_id);
CREATE INDEX IF NOT EXISTS "mfa_used_steps_doc_gin" ON "mogo_dev"."mfa_used_steps" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."org_quota_policies" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "org_quota_policies_tenant_idx" ON "mogo_dev"."org_quota_policies" (tenant_id);
CREATE INDEX IF NOT EXISTS "org_quota_policies_doc_gin" ON "mogo_dev"."org_quota_policies" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."org_units" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "org_units_tenant_idx" ON "mogo_dev"."org_units" (tenant_id);
CREATE INDEX IF NOT EXISTS "org_units_doc_gin" ON "mogo_dev"."org_units" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."organization_shortcut_schemes" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "organization_shortcut_schemes_tenant_idx" ON "mogo_dev"."organization_shortcut_schemes" (tenant_id);
CREATE INDEX IF NOT EXISTS "organization_shortcut_schemes_doc_gin" ON "mogo_dev"."organization_shortcut_schemes" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."organization_skill_releases" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "organization_skill_releases_tenant_idx" ON "mogo_dev"."organization_skill_releases" (tenant_id);
CREATE INDEX IF NOT EXISTS "organization_skill_releases_doc_gin" ON "mogo_dev"."organization_skill_releases" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."organizations" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "organizations_tenant_idx" ON "mogo_dev"."organizations" (tenant_id);
CREATE INDEX IF NOT EXISTS "organizations_doc_gin" ON "mogo_dev"."organizations" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."page_collection_settings" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "page_collection_settings_tenant_idx" ON "mogo_dev"."page_collection_settings" (tenant_id);
CREATE INDEX IF NOT EXISTS "page_collection_settings_doc_gin" ON "mogo_dev"."page_collection_settings" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."permission_grants" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "permission_grants_tenant_idx" ON "mogo_dev"."permission_grants" (tenant_id);
CREATE INDEX IF NOT EXISTS "permission_grants_doc_gin" ON "mogo_dev"."permission_grants" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."personal_knowledge_directories" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "personal_knowledge_directories_tenant_idx" ON "mogo_dev"."personal_knowledge_directories" (tenant_id);
CREATE INDEX IF NOT EXISTS "personal_knowledge_directories_doc_gin" ON "mogo_dev"."personal_knowledge_directories" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."pii_policies" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "pii_policies_tenant_idx" ON "mogo_dev"."pii_policies" (tenant_id);
CREATE INDEX IF NOT EXISTS "pii_policies_doc_gin" ON "mogo_dev"."pii_policies" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."position_role_audit_logs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "position_role_audit_logs_tenant_idx" ON "mogo_dev"."position_role_audit_logs" (tenant_id);
CREATE INDEX IF NOT EXISTS "position_role_audit_logs_doc_gin" ON "mogo_dev"."position_role_audit_logs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."position_role_migrations" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "position_role_migrations_tenant_idx" ON "mogo_dev"."position_role_migrations" (tenant_id);
CREATE INDEX IF NOT EXISTS "position_role_migrations_doc_gin" ON "mogo_dev"."position_role_migrations" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."position_roles" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "position_roles_tenant_idx" ON "mogo_dev"."position_roles" (tenant_id);
CREATE INDEX IF NOT EXISTS "position_roles_doc_gin" ON "mogo_dev"."position_roles" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."presentation_generation_jobs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "presentation_generation_jobs_tenant_idx" ON "mogo_dev"."presentation_generation_jobs" (tenant_id);
CREATE INDEX IF NOT EXISTS "presentation_generation_jobs_doc_gin" ON "mogo_dev"."presentation_generation_jobs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."project_memories" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "project_memories_tenant_idx" ON "mogo_dev"."project_memories" (tenant_id);
CREATE INDEX IF NOT EXISTS "project_memories_doc_gin" ON "mogo_dev"."project_memories" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."quota_counters" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "quota_counters_tenant_idx" ON "mogo_dev"."quota_counters" (tenant_id);
CREATE INDEX IF NOT EXISTS "quota_counters_doc_gin" ON "mogo_dev"."quota_counters" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."resource_comment_reactions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "resource_comment_reactions_tenant_idx" ON "mogo_dev"."resource_comment_reactions" (tenant_id);
CREATE INDEX IF NOT EXISTS "resource_comment_reactions_doc_gin" ON "mogo_dev"."resource_comment_reactions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."resource_comments" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "resource_comments_tenant_idx" ON "mogo_dev"."resource_comments" (tenant_id);
CREATE INDEX IF NOT EXISTS "resource_comments_doc_gin" ON "mogo_dev"."resource_comments" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."resource_feedback_notifications" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "resource_feedback_notifications_tenant_idx" ON "mogo_dev"."resource_feedback_notifications" (tenant_id);
CREATE INDEX IF NOT EXISTS "resource_feedback_notifications_doc_gin" ON "mogo_dev"."resource_feedback_notifications" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."resource_grants" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "resource_grants_tenant_idx" ON "mogo_dev"."resource_grants" (tenant_id);
CREATE INDEX IF NOT EXISTS "resource_grants_doc_gin" ON "mogo_dev"."resource_grants" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."resource_reactions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "resource_reactions_tenant_idx" ON "mogo_dev"."resource_reactions" (tenant_id);
CREATE INDEX IF NOT EXISTS "resource_reactions_doc_gin" ON "mogo_dev"."resource_reactions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."risk_tiers" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "risk_tiers_tenant_idx" ON "mogo_dev"."risk_tiers" (tenant_id);
CREATE INDEX IF NOT EXISTS "risk_tiers_doc_gin" ON "mogo_dev"."risk_tiers" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."runtime_profile_audit" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "runtime_profile_audit_tenant_idx" ON "mogo_dev"."runtime_profile_audit" (tenant_id);
CREATE INDEX IF NOT EXISTS "runtime_profile_audit_doc_gin" ON "mogo_dev"."runtime_profile_audit" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."runtime_profile_versions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "runtime_profile_versions_tenant_idx" ON "mogo_dev"."runtime_profile_versions" (tenant_id);
CREATE INDEX IF NOT EXISTS "runtime_profile_versions_doc_gin" ON "mogo_dev"."runtime_profile_versions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."session_secret_refs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "session_secret_refs_tenant_idx" ON "mogo_dev"."session_secret_refs" (tenant_id);
CREATE INDEX IF NOT EXISTS "session_secret_refs_doc_gin" ON "mogo_dev"."session_secret_refs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."session_shares" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "session_shares_tenant_idx" ON "mogo_dev"."session_shares" (tenant_id);
CREATE INDEX IF NOT EXISTS "session_shares_doc_gin" ON "mogo_dev"."session_shares" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."session_snapshots" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "session_snapshots_tenant_idx" ON "mogo_dev"."session_snapshots" (tenant_id);
CREATE INDEX IF NOT EXISTS "session_snapshots_doc_gin" ON "mogo_dev"."session_snapshots" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."site_profiles" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "site_profiles_tenant_idx" ON "mogo_dev"."site_profiles" (tenant_id);
CREATE INDEX IF NOT EXISTS "site_profiles_doc_gin" ON "mogo_dev"."site_profiles" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_adoption" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_adoption_tenant_idx" ON "mogo_dev"."skill_adoption" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_adoption_doc_gin" ON "mogo_dev"."skill_adoption" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_distribution_members" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_distribution_members_tenant_idx" ON "mogo_dev"."skill_distribution_members" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_distribution_members_doc_gin" ON "mogo_dev"."skill_distribution_members" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_distribution_releases" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_distribution_releases_tenant_idx" ON "mogo_dev"."skill_distribution_releases" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_distribution_releases_doc_gin" ON "mogo_dev"."skill_distribution_releases" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_distributions" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_distributions_tenant_idx" ON "mogo_dev"."skill_distributions" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_distributions_doc_gin" ON "mogo_dev"."skill_distributions" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_drafts" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_drafts_tenant_idx" ON "mogo_dev"."skill_drafts" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_drafts_doc_gin" ON "mogo_dev"."skill_drafts" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_packages" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_packages_tenant_idx" ON "mogo_dev"."skill_packages" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_packages_doc_gin" ON "mogo_dev"."skill_packages" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_product_edit_events" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_product_edit_events_tenant_idx" ON "mogo_dev"."skill_product_edit_events" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_product_edit_events_doc_gin" ON "mogo_dev"."skill_product_edit_events" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_quality_collector_state" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_quality_collector_state_tenant_idx" ON "mogo_dev"."skill_quality_collector_state" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_quality_collector_state_doc_gin" ON "mogo_dev"."skill_quality_collector_state" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_quality_metrics" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_quality_metrics_tenant_idx" ON "mogo_dev"."skill_quality_metrics" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_quality_metrics_doc_gin" ON "mogo_dev"."skill_quality_metrics" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_releases" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_releases_tenant_idx" ON "mogo_dev"."skill_releases" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_releases_doc_gin" ON "mogo_dev"."skill_releases" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_rollouts" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_rollouts_tenant_idx" ON "mogo_dev"."skill_rollouts" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_rollouts_doc_gin" ON "mogo_dev"."skill_rollouts" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_share_deliveries" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_share_deliveries_tenant_idx" ON "mogo_dev"."skill_share_deliveries" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_share_deliveries_doc_gin" ON "mogo_dev"."skill_share_deliveries" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_shares" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_shares_tenant_idx" ON "mogo_dev"."skill_shares" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_shares_doc_gin" ON "mogo_dev"."skill_shares" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skill_update_notifications" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skill_update_notifications_tenant_idx" ON "mogo_dev"."skill_update_notifications" (tenant_id);
CREATE INDEX IF NOT EXISTS "skill_update_notifications_doc_gin" ON "mogo_dev"."skill_update_notifications" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."skills" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "skills_tenant_idx" ON "mogo_dev"."skills" (tenant_id);
CREATE INDEX IF NOT EXISTS "skills_doc_gin" ON "mogo_dev"."skills" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."system_audit_logs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "system_audit_logs_tenant_idx" ON "mogo_dev"."system_audit_logs" (tenant_id);
CREATE INDEX IF NOT EXISTS "system_audit_logs_doc_gin" ON "mogo_dev"."system_audit_logs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."system_bootstrap" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "system_bootstrap_tenant_idx" ON "mogo_dev"."system_bootstrap" (tenant_id);
CREATE INDEX IF NOT EXISTS "system_bootstrap_doc_gin" ON "mogo_dev"."system_bootstrap" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."tenant_purge_progress" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "tenant_purge_progress_tenant_idx" ON "mogo_dev"."tenant_purge_progress" (tenant_id);
CREATE INDEX IF NOT EXISTS "tenant_purge_progress_doc_gin" ON "mogo_dev"."tenant_purge_progress" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."tenants" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "tenants_tenant_idx" ON "mogo_dev"."tenants" (tenant_id);
CREATE INDEX IF NOT EXISTS "tenants_doc_gin" ON "mogo_dev"."tenants" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."token_usage_logs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "token_usage_logs_tenant_idx" ON "mogo_dev"."token_usage_logs" (tenant_id);
CREATE INDEX IF NOT EXISTS "token_usage_logs_doc_gin" ON "mogo_dev"."token_usage_logs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_field_defs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_field_defs_tenant_idx" ON "mogo_dev"."user_field_defs" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_field_defs_doc_gin" ON "mogo_dev"."user_field_defs" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_field_values" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_field_values_tenant_idx" ON "mogo_dev"."user_field_values" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_field_values_doc_gin" ON "mogo_dev"."user_field_values" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_identities" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_identities_tenant_idx" ON "mogo_dev"."user_identities" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_identities_doc_gin" ON "mogo_dev"."user_identities" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_invites" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_invites_tenant_idx" ON "mogo_dev"."user_invites" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_invites_doc_gin" ON "mogo_dev"."user_invites" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_quota_overrides" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_quota_overrides_tenant_idx" ON "mogo_dev"."user_quota_overrides" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_quota_overrides_doc_gin" ON "mogo_dev"."user_quota_overrides" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_quota_policies" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_quota_policies_tenant_idx" ON "mogo_dev"."user_quota_policies" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_quota_policies_doc_gin" ON "mogo_dev"."user_quota_policies" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_shortcut_preferences" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_shortcut_preferences_tenant_idx" ON "mogo_dev"."user_shortcut_preferences" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_shortcut_preferences_doc_gin" ON "mogo_dev"."user_shortcut_preferences" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_skills" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_skills_tenant_idx" ON "mogo_dev"."user_skills" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_skills_doc_gin" ON "mogo_dev"."user_skills" USING GIN (doc jsonb_ops);

CREATE TABLE IF NOT EXISTS "mogo_dev"."user_token_allocation_logs" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "user_token_allocation_logs_tenant_idx" ON "mogo_dev"."user_token_allocation_logs" (tenant_id);
CREATE INDEX IF NOT EXISTS "user_token_allocation_logs_doc_gin" ON "mogo_dev"."user_token_allocation_logs" USING GIN (doc jsonb_ops);
