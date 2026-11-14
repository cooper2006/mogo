-- 01 加列 (按文档 §3 平铺列集; openGauss A 模式)
-- openGauss 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS
-- → 用 DO 块查 information_schema.columns 判断, 可重复执行

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='name') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='status') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_account_groups' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.admin_account_groups ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='login_name') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN login_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='password_hash') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN password_hash TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='password_algorithm') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN password_algorithm TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='name') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='display_name') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN display_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='email') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN email TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='phone') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN phone TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='avatar_url') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN avatar_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='status') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='failed_login_count') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN failed_login_count INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='locked_at') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN locked_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='last_login_at') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN last_login_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='last_login_ip') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN last_login_ip TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='mfa_enabled') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN mfa_enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_accounts' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.admin_accounts ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='provider_id') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN provider_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='model_key') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN model_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='label') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN label TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='base_url') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN base_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='api_key_encrypted') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN api_key_encrypted TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='auth_type') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN auth_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='status') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='is_default') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN is_default BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_instances' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.admin_model_instances ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='name') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='base_url') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN base_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='auth_type') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN auth_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='api_key_encrypted') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN api_key_encrypted TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='status') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='is_default') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN is_default BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_model_providers' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.admin_model_providers ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='theme') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN theme TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='font_family') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN font_family TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='color_primary') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN color_primary TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='color_background') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN color_background TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='logo_url') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN logo_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='favicon_url') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN favicon_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='admin_presentation_settings' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.admin_presentation_settings ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='kernel_type') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN kernel_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='kernel_id') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN kernel_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='binding_type') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN binding_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='binding_ref') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN binding_ref TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='status') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='agent_kernel_bindings' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.agent_kernel_bindings ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='name') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='description') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='scope_type') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN scope_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='scope_ref') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN scope_ref TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='rules') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN rules JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='autonomy_matrix' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.autonomy_matrix ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='session_id') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN session_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='sender_type') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN sender_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='sender_id') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN sender_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='content') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN content TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='content_type') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN content_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='status') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='reply_to_id') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN reply_to_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_messages' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.chat_messages ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='type') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='title') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN title TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='participant_ids') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN participant_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='status') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='last_message_id') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN last_message_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='last_message_at') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN last_message_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='last_message_preview') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN last_message_preview TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='chat_sessions' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.chat_sessions ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='name') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='description') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='graph_data') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN graph_data JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='version') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN version TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='status') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='dag_definitions' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.dag_definitions ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='name') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='description') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='template_id') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN template_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='status') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='data') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN data JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='desktop_projects' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.desktop_projects ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='user_id') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='capability_key') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN capability_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='value') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN value TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_capability_overrides' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.end_user_capability_overrides ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='user_id') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='org_id') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN org_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='position_id') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN position_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='role_type') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN role_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='status') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='start_date') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN start_date TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='end_date') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN end_date TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_org_relations' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.end_user_org_relations ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='user_id') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='position_id') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN position_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='role_name') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN role_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='role_type') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN role_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='status') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='start_date') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN start_date TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='end_date') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN end_date TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_user_position_roles' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.end_user_position_roles ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='name') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='display_name') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN display_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='login_name') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN login_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='email') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN email TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='phone') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN phone TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='avatar_url') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN avatar_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='status') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='password_hash') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN password_hash TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='password_algorithm') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN password_algorithm TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='failed_login_count') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN failed_login_count INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='locked_at') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN locked_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='last_login_at') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN last_login_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='last_login_ip') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN last_login_ip TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='mfa_enabled') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN mfa_enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='end_users' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.end_users ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='name') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='provider') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN provider TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='api_key_encrypted') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN api_key_encrypted TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='endpoint') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN endpoint TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='status') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='is_default') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN is_default BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_search_configs' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.external_search_configs ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='name') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='description') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='base_url') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN base_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='auth_type') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN auth_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='api_key_encrypted') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN api_key_encrypted TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='status') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='is_default') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN is_default BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='external_tools' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.external_tools ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='name') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='description') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='rule_type') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN rule_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='condition') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN condition TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='action') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN action TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='priority') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN priority INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='gatekeeper_rules' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.gatekeeper_rules ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='name') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='description') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='type') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='config') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN config JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='status') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='harness_profiles' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.harness_profiles ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='name') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='description') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='event_type') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN event_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='condition') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN condition TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='action') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN action TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='priority') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN priority INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='hook_rules' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.hook_rules ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='type') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='name') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='member_ids') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN member_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='status') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='last_message_id') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN last_message_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='last_message_at') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN last_message_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='last_message_preview') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN last_message_preview TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='im_channels' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.im_channels ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='name') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='path_ids') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN path_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='path_names') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN path_names JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='scope') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN scope TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_directories' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.knowledge_directories ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='document_id') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN document_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='chunk_id') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN chunk_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='chunk_stage') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN chunk_stage TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='ordinal') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN ordinal INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='text') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN text TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='contextual_text') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN contextual_text TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='title_path') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN title_path TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='page_no') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN page_no TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='content_type') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN content_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='source_chunk_ids') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN source_chunk_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_chunks' AND column_name='status') THEN
    ALTER TABLE mogo_dev.knowledge_document_chunks ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_settings' AND column_name='kind') THEN
    ALTER TABLE mogo_dev.knowledge_document_settings ADD COLUMN kind TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_settings' AND column_name='config') THEN
    ALTER TABLE mogo_dev.knowledge_document_settings ADD COLUMN config JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_document_settings' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.knowledge_document_settings ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='scope') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN scope TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='resource_id') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN resource_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='knowledge_base_id') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN knowledge_base_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='name') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='description') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='original_filename') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN original_filename TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='file_ext') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN file_ext TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='mime_type') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN mime_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='file_size') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN file_size BIGINT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='storage_type') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN storage_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='storage_bucket') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN storage_bucket TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='storage_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN storage_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='local_path') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN local_path TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='checksum') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN checksum TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='status') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='parse_status') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN parse_status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='parse_job_id') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN parse_job_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='parse_error') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN parse_error TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='parse_updated_at') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN parse_updated_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='parsed_markdown_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN parsed_markdown_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='parsed_json_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN parsed_json_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='raw_chunks_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN raw_chunks_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='raw_chunk_count') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN raw_chunk_count INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='rag_chunks_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN rag_chunks_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='rag_chunk_count') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN rag_chunk_count INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='chunks_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN chunks_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='chunk_count') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN chunk_count INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='chunk_status') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN chunk_status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='index_status') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN index_status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='index_job_id') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN index_job_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='index_error') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN index_error TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='indexed_chunk_count') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN indexed_chunk_count INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='indexed_at') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN indexed_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='vector_store_type') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN vector_store_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='vector_collection_name') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN vector_collection_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='preview_key') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN preview_key TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='preview_mime_type') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN preview_mime_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='preview_status') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN preview_status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='preview_job_id') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN preview_job_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='preview_error') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN preview_error TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='preview_updated_at') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN preview_updated_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='tags') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN tags JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='created_by_name') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN created_by_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='updated_by_name') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN updated_by_name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_documents' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.knowledge_documents ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='directory_id') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN directory_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='name') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='description') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='tags') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN tags JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='share_policy') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN share_policy TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='active_document_id') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN active_document_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='processing_document_id') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN processing_document_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='status') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='error') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN error TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='knowledge_resources' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.knowledge_resources ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='org_id') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN org_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='quota_type') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN quota_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='quota_limit') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN quota_limit BIGINT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='quota_unit') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN quota_unit TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='period') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN period TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='status') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_quota_policies' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.org_quota_policies ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='name') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='path_ids') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN path_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='path_names') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN path_names JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='type') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='status') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='leader_user_id') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN leader_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='description') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='org_units' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.org_units ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='name') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='description') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='scope_type') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN scope_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='scope_ref') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN scope_ref TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='shortcuts') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN shortcuts JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='status') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organization_shortcut_schemes' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.organization_shortcut_schemes ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='name') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='path_ids') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN path_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='path_names') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN path_names JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='type') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='status') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='description') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='contact_email') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN contact_email TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='contact_phone') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN contact_phone TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='address') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN address TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='logo_url') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN logo_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='settings') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN settings JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='organizations' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.organizations ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='page_collection_settings' AND column_name='page_id') THEN
    ALTER TABLE mogo_dev.page_collection_settings ADD COLUMN page_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='page_collection_settings' AND column_name='collection_id') THEN
    ALTER TABLE mogo_dev.page_collection_settings ADD COLUMN collection_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='page_collection_settings' AND column_name='settings') THEN
    ALTER TABLE mogo_dev.page_collection_settings ADD COLUMN settings JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='page_collection_settings' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.page_collection_settings ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='page_collection_settings' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.page_collection_settings ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='page_collection_settings' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.page_collection_settings ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='owner_user_id') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN owner_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='name') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='path_ids') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN path_ids JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='path_names') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN path_names JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='status') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='personal_knowledge_directories' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.personal_knowledge_directories ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='name') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='description') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='rules') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN rules JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='pii_policies' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.pii_policies ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='name') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='description') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='type') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='level') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN level TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='status') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='sort_order') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN sort_order INTEGER;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='position_roles' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.position_roles ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comment_reactions' AND column_name='comment_id') THEN
    ALTER TABLE mogo_dev.resource_comment_reactions ADD COLUMN comment_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comment_reactions' AND column_name='user_id') THEN
    ALTER TABLE mogo_dev.resource_comment_reactions ADD COLUMN user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comment_reactions' AND column_name='reaction') THEN
    ALTER TABLE mogo_dev.resource_comment_reactions ADD COLUMN reaction TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='resource_type') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN resource_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='resource_id') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN resource_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='user_id') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='author') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN author TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='content') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN content TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='parent_id') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN parent_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='root_id') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN root_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='reply_to') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN reply_to TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='status') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='release_id') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN release_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_comments' AND column_name='release_version') THEN
    ALTER TABLE mogo_dev.resource_comments ADD COLUMN release_version TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='resource_type') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN resource_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='resource_id') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN resource_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='recipient_user_id') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN recipient_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='actor') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN actor TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='comment_id') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN comment_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='kind') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN kind TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='status') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_feedback_notifications' AND column_name='read_at') THEN
    ALTER TABLE mogo_dev.resource_feedback_notifications ADD COLUMN read_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='resource_type') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN resource_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='resource_id') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN resource_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='recipient_user_id') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN recipient_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='granted_by_user_id') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN granted_by_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='can_reshare') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN can_reshare BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='status') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='revoked_at') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN revoked_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='revoked_by_user_id') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN revoked_by_user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='revoke_reason') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN revoke_reason TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_grants' AND column_name='seen_at') THEN
    ALTER TABLE mogo_dev.resource_grants ADD COLUMN seen_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_reactions' AND column_name='resource_type') THEN
    ALTER TABLE mogo_dev.resource_reactions ADD COLUMN resource_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_reactions' AND column_name='resource_id') THEN
    ALTER TABLE mogo_dev.resource_reactions ADD COLUMN resource_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_reactions' AND column_name='user_id') THEN
    ALTER TABLE mogo_dev.resource_reactions ADD COLUMN user_id TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='resource_reactions' AND column_name='reaction') THEN
    ALTER TABLE mogo_dev.resource_reactions ADD COLUMN reaction TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='name') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='description') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='level') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN level TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='rules') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN rules JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='risk_tiers' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.risk_tiers ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='name') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='description') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='schedule_type') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN schedule_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='schedule_expr') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN schedule_expr TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='job_type') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN job_type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='job_config') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN job_config JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='status') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='enabled') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN enabled BOOLEAN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='scheduled_jobs' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.scheduled_jobs ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='name') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='description') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='domain') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN domain TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='status') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='theme') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN theme TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='settings') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN settings JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='site_profiles' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.site_profiles ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='name') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='description') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='type') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN type TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='status') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='version') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN version TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='data') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN data JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='skills' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.skills ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='name') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN name TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='description') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN description TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='status') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN status TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='contact_email') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN contact_email TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='contact_phone') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN contact_phone TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='address') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN address TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='logo_url') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN logo_url TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='settings') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN settings JSONB;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='created_by') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN created_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='updated_by') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN updated_by TEXT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='mogo_dev' AND table_name='tenants' AND column_name='deleted_at') THEN
    ALTER TABLE mogo_dev.tenants ADD COLUMN deleted_at TIMESTAMPTZ;
  END IF;
END $$;

