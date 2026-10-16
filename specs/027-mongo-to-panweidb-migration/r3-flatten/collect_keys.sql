select 'admin_account_groups' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.admin_account_groups) s
union all
select 'admin_accounts' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.admin_accounts) s
union all
select 'admin_model_instances' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.admin_model_instances) s
union all
select 'admin_model_providers' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.admin_model_providers) s
union all
select 'admin_presentation_settings' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.admin_presentation_settings) s
union all
select 'agent_kernel_bindings' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.agent_kernel_bindings) s
union all
select 'autonomy_matrix' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.autonomy_matrix) s
union all
select 'chat_messages' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.chat_messages) s
union all
select 'chat_sessions' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.chat_sessions) s
union all
select 'dag_definitions' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.dag_definitions) s
union all
select 'desktop_projects' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.desktop_projects) s
union all
select 'end_user_capability_overrides' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.end_user_capability_overrides) s
union all
select 'end_user_org_relations' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.end_user_org_relations) s
union all
select 'end_user_position_roles' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.end_user_position_roles) s
union all
select 'end_users' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.end_users) s
union all
select 'external_search_configs' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.external_search_configs) s
union all
select 'external_tools' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.external_tools) s
union all
select 'gatekeeper_rules' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.gatekeeper_rules) s
union all
select 'harness_profiles' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.harness_profiles) s
union all
select 'hook_rules' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.hook_rules) s
union all
select 'im_channels' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.im_channels) s
union all
select 'knowledge_directories' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.knowledge_directories) s
union all
select 'knowledge_document_chunks' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.knowledge_document_chunks) s
union all
select 'knowledge_document_settings' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.knowledge_document_settings) s
union all
select 'knowledge_documents' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.knowledge_documents) s
union all
select 'knowledge_resources' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.knowledge_resources) s
union all
select 'org_quota_policies' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.org_quota_policies) s
union all
select 'org_units' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.org_units) s
union all
select 'organization_shortcut_schemes' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.organization_shortcut_schemes) s
union all
select 'organizations' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.organizations) s
union all
select 'page_collection_settings' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.page_collection_settings) s
union all
select 'personal_knowledge_directories' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.personal_knowledge_directories) s
union all
select 'pii_policies' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.pii_policies) s
union all
select 'position_roles' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.position_roles) s
union all
select 'resource_comment_reactions' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.resource_comment_reactions) s
union all
select 'resource_comments' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.resource_comments) s
union all
select 'resource_feedback_notifications' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.resource_feedback_notifications) s
union all
select 'resource_grants' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.resource_grants) s
union all
select 'resource_reactions' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.resource_reactions) s
union all
select 'risk_tiers' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.risk_tiers) s
union all
select 'scheduled_jobs' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.scheduled_jobs) s
union all
select 'site_profiles' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.site_profiles) s
union all
select 'skills' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.skills) s
union all
select 'tenants' as tbl, k from (select jsonb_object_keys(doc) as k from mogo_dev.tenants) s;
