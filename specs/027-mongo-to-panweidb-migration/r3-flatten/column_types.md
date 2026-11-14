# 列类型推断审查清单 (027-R3 扁平化)

生成依据: 文档 §3 平铺列集 + §8.A 类型映射 + 命名规则推断。
doc_key 默认等于列名 (兼容层 COLUMN_MAP 通常 1:1 同名)。


## 1. admin_account_groups  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| parent_id | TEXT | parent_id |  |
| status | TEXT | status |  |
| sort_order | INTEGER | sort_order |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 2. admin_accounts  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| login_name | TEXT | login_name |  |
| password_hash | TEXT | password_hash |  |
| password_algorithm | TEXT | password_algorithm |  |
| name | TEXT | name |  |
| display_name | TEXT | display_name |  |
| email | TEXT | email |  |
| phone | TEXT | phone |  |
| avatar_url | TEXT | avatar_url |  |
| status | TEXT | status |  |
| failed_login_count | INTEGER | failed_login_count |  |
| locked_at | TIMESTAMPTZ | locked_at |  |
| last_login_at | TIMESTAMPTZ | last_login_at |  |
| last_login_ip | TEXT | last_login_ip |  |
| mfa_enabled | BOOLEAN | mfa_enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 4. admin_model_instances  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| provider_id | TEXT | provider_id |  |
| model_key | TEXT | model_key |  |
| label | TEXT | label |  |
| base_url | TEXT | base_url |  |
| api_key_encrypted | TEXT | api_key_encrypted |  |
| auth_type | TEXT | auth_type |  |
| status | TEXT | status |  |
| is_default | BOOLEAN | is_default |  |
| sort_order | INTEGER | sort_order |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 5. admin_model_providers  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| base_url | TEXT | base_url |  |
| auth_type | TEXT | auth_type |  |
| api_key_encrypted | TEXT | api_key_encrypted |  |
| status | TEXT | status |  |
| is_default | BOOLEAN | is_default |  |
| sort_order | INTEGER | sort_order |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 6. admin_presentation_settings  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| theme | TEXT | theme |  |
| font_family | TEXT | font_family |  |
| color_primary | TEXT | color_primary |  |
| color_background | TEXT | color_background |  |
| logo_url | TEXT | logo_url |  |
| favicon_url | TEXT | favicon_url |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |

## 10. agent_kernel_bindings  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| kernel_type | TEXT | kernel_type |  |
| kernel_id | TEXT | kernel_id |  |
| binding_type | TEXT | binding_type |  |
| binding_ref | TEXT | binding_ref |  |
| status | TEXT | status |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 14. autonomy_matrix  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| scope_type | TEXT | scope_type |  |
| scope_ref | TEXT | scope_ref |  |
| rules | JSONB | rules | 是 |
| enabled | BOOLEAN | enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 16. chat_messages  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| session_id | TEXT | session_id |  |
| sender_type | TEXT | sender_type |  |
| sender_id | TEXT | sender_id |  |
| content | TEXT | content |  |
| content_type | TEXT | content_type |  |
| status | TEXT | status |  |
| parent_id | TEXT | parent_id |  |
| reply_to_id | TEXT | reply_to_id |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 17. chat_sessions  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| type | TEXT | type |  |
| title | TEXT | title |  |
| owner_user_id | TEXT | owner_user_id |  |
| participant_ids | JSONB | participant_ids | 是 |
| status | TEXT | status |  |
| last_message_id | TEXT | last_message_id |  |
| last_message_at | TIMESTAMPTZ | last_message_at |  |
| last_message_preview | TEXT | last_message_preview |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 18. dag_definitions  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| graph_data | JSONB | graph_data | 是 |
| version | TEXT | version |  |
| status | TEXT | status |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 19. desktop_projects  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| owner_user_id | TEXT | owner_user_id |  |
| template_id | TEXT | template_id |  |
| status | TEXT | status |  |
| data | JSONB | data | 是 |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 21. end_user_capability_overrides  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| user_id | TEXT | user_id |  |
| capability_key | TEXT | capability_key |  |
| enabled | BOOLEAN | enabled |  |
| value | TEXT | value |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 23. end_user_org_relations  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| user_id | TEXT | user_id |  |
| org_id | TEXT | org_id |  |
| position_id | TEXT | position_id |  |
| role_type | TEXT | role_type |  |
| status | TEXT | status |  |
| start_date | TIMESTAMPTZ | start_date |  |
| end_date | TIMESTAMPTZ | end_date |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 24. end_user_position_roles  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| user_id | TEXT | user_id |  |
| position_id | TEXT | position_id |  |
| role_name | TEXT | role_name |  |
| role_type | TEXT | role_type |  |
| status | TEXT | status |  |
| start_date | TIMESTAMPTZ | start_date |  |
| end_date | TIMESTAMPTZ | end_date |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 26. end_users  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| display_name | TEXT | display_name |  |
| login_name | TEXT | login_name |  |
| email | TEXT | email |  |
| phone | TEXT | phone |  |
| avatar_url | TEXT | avatar_url |  |
| status | TEXT | status |  |
| password_hash | TEXT | password_hash |  |
| password_algorithm | TEXT | password_algorithm |  |
| failed_login_count | INTEGER | failed_login_count |  |
| locked_at | TIMESTAMPTZ | locked_at |  |
| last_login_at | TIMESTAMPTZ | last_login_at |  |
| last_login_ip | TEXT | last_login_ip |  |
| mfa_enabled | BOOLEAN | mfa_enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 34. external_search_configs  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| provider | TEXT | provider |  |
| api_key_encrypted | TEXT | api_key_encrypted |  |
| endpoint | TEXT | endpoint |  |
| status | TEXT | status |  |
| is_default | BOOLEAN | is_default |  |
| sort_order | INTEGER | sort_order |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 35. external_tools  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| base_url | TEXT | base_url |  |
| auth_type | TEXT | auth_type |  |
| api_key_encrypted | TEXT | api_key_encrypted |  |
| status | TEXT | status |  |
| is_default | BOOLEAN | is_default |  |
| sort_order | INTEGER | sort_order |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 38. gatekeeper_rules  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| rule_type | TEXT | rule_type |  |
| condition | TEXT | condition |  |
| action | TEXT | action |  |
| priority | INTEGER | priority |  |
| enabled | BOOLEAN | enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 39. harness_profiles  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| type | TEXT | type |  |
| config | JSONB | config | 是 |
| status | TEXT | status |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 40. hook_rules  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| event_type | TEXT | event_type |  |
| condition | TEXT | condition |  |
| action | TEXT | action |  |
| priority | INTEGER | priority |  |
| enabled | BOOLEAN | enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 41. im_channels  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| type | TEXT | type |  |
| name | TEXT | name |  |
| owner_user_id | TEXT | owner_user_id |  |
| member_ids | JSONB | member_ids | 是 |
| status | TEXT | status |  |
| last_message_id | TEXT | last_message_id |  |
| last_message_at | TIMESTAMPTZ | last_message_at |  |
| last_message_preview | TEXT | last_message_preview |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 45. knowledge_directories  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| parent_id | TEXT | parent_id |  |
| path_ids | JSONB | path_ids | 是 |
| path_names | JSONB | path_names | 是 |
| owner_user_id | TEXT | owner_user_id |  |
| scope | TEXT | scope |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 46. knowledge_document_chunks  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| document_id | TEXT | document_id |  |
| chunk_id | TEXT | chunk_id |  |
| chunk_stage | TEXT | chunk_stage |  |
| ordinal | INTEGER | ordinal |  |
| text | TEXT | text |  |
| contextual_text | TEXT | contextual_text |  |
| title_path | TEXT | title_path |  |
| page_no | TEXT | page_no |  |
| content_type | TEXT | content_type |  |
| source_chunk_ids | JSONB | source_chunk_ids | 是 |
| status | TEXT | status |  |

## 47. knowledge_document_settings  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| kind | TEXT | kind |  |
| config | JSONB | config | 是 |
| updated_by | TEXT | updated_by |  |

## 48. knowledge_documents  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| scope | TEXT | scope |  |
| owner_user_id | TEXT | owner_user_id |  |
| resource_id | TEXT | resource_id |  |
| knowledge_base_id | TEXT | knowledge_base_id |  |
| name | TEXT | name |  |
| description | TEXT | description |  |
| original_filename | TEXT | original_filename |  |
| file_ext | TEXT | file_ext |  |
| mime_type | TEXT | mime_type |  |
| file_size | BIGINT | file_size |  |
| storage_type | TEXT | storage_type |  |
| storage_bucket | TEXT | storage_bucket |  |
| storage_key | TEXT | storage_key |  |
| local_path | TEXT | local_path |  |
| checksum | TEXT | checksum |  |
| status | TEXT | status |  |
| parse_status | TEXT | parse_status |  |
| parse_job_id | TEXT | parse_job_id |  |
| parse_error | TEXT | parse_error |  |
| parse_updated_at | TIMESTAMPTZ | parse_updated_at |  |
| parsed_markdown_key | TEXT | parsed_markdown_key |  |
| parsed_json_key | TEXT | parsed_json_key |  |
| raw_chunks_key | TEXT | raw_chunks_key |  |
| raw_chunk_count | INTEGER | raw_chunk_count |  |
| rag_chunks_key | TEXT | rag_chunks_key |  |
| rag_chunk_count | INTEGER | rag_chunk_count |  |
| chunks_key | TEXT | chunks_key |  |
| chunk_count | INTEGER | chunk_count |  |
| chunk_status | TEXT | chunk_status |  |
| index_status | TEXT | index_status |  |
| index_job_id | TEXT | index_job_id |  |
| index_error | TEXT | index_error |  |
| indexed_chunk_count | INTEGER | indexed_chunk_count |  |
| indexed_at | TIMESTAMPTZ | indexed_at |  |
| vector_store_type | TEXT | vector_store_type |  |
| vector_collection_name | TEXT | vector_collection_name |  |
| preview_key | TEXT | preview_key |  |
| preview_mime_type | TEXT | preview_mime_type |  |
| preview_status | TEXT | preview_status |  |
| preview_job_id | TEXT | preview_job_id |  |
| preview_error | TEXT | preview_error |  |
| preview_updated_at | TIMESTAMPTZ | preview_updated_at |  |
| tags | JSONB | tags | 是 |
| created_by | TEXT | created_by |  |
| created_by_name | TEXT | created_by_name |  |
| updated_by | TEXT | updated_by |  |
| updated_by_name | TEXT | updated_by_name |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 49. knowledge_resources  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| owner_user_id | TEXT | owner_user_id |  |
| directory_id | TEXT | directory_id |  |
| name | TEXT | name |  |
| description | TEXT | description |  |
| tags | JSONB | tags | 是 |
| share_policy | TEXT | share_policy |  |
| active_document_id | TEXT | active_document_id |  |
| processing_document_id | TEXT | processing_document_id |  |
| status | TEXT | status |  |
| error | TEXT | error |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 53. org_quota_policies  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| org_id | TEXT | org_id |  |
| quota_type | TEXT | quota_type |  |
| quota_limit | BIGINT | quota_limit |  |
| quota_unit | TEXT | quota_unit |  |
| period | TEXT | period |  |
| status | TEXT | status |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 54. org_units  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| parent_id | TEXT | parent_id |  |
| path_ids | JSONB | path_ids | 是 |
| path_names | JSONB | path_names | 是 |
| type | TEXT | type |  |
| status | TEXT | status |  |
| sort_order | INTEGER | sort_order |  |
| leader_user_id | TEXT | leader_user_id |  |
| description | TEXT | description |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 55. organization_shortcut_schemes  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| scope_type | TEXT | scope_type |  |
| scope_ref | TEXT | scope_ref |  |
| shortcuts | JSONB | shortcuts | 是 |
| status | TEXT | status |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 57. organizations  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| parent_id | TEXT | parent_id |  |
| path_ids | JSONB | path_ids | 是 |
| path_names | JSONB | path_names | 是 |
| type | TEXT | type |  |
| status | TEXT | status |  |
| sort_order | INTEGER | sort_order |  |
| description | TEXT | description |  |
| contact_email | TEXT | contact_email |  |
| contact_phone | TEXT | contact_phone |  |
| address | TEXT | address |  |
| logo_url | TEXT | logo_url |  |
| settings | JSONB | settings | 是 |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 58. page_collection_settings  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| page_id | TEXT | page_id |  |
| collection_id | TEXT | collection_id |  |
| settings | JSONB | settings | 是 |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 60. personal_knowledge_directories  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| owner_user_id | TEXT | owner_user_id |  |
| parent_id | TEXT | parent_id |  |
| name | TEXT | name |  |
| path_ids | JSONB | path_ids | 是 |
| path_names | JSONB | path_names | 是 |
| status | TEXT | status |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 61. pii_policies  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| rules | JSONB | rules | 是 |
| enabled | BOOLEAN | enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 64. position_roles  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| type | TEXT | type |  |
| level | TEXT | level |  |
| status | TEXT | status |  |
| sort_order | INTEGER | sort_order |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 69. resource_comment_reactions  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| comment_id | TEXT | comment_id |  |
| user_id | TEXT | user_id |  |
| reaction | TEXT | reaction |  |

## 70. resource_comments  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| resource_type | TEXT | resource_type |  |
| resource_id | TEXT | resource_id |  |
| user_id | TEXT | user_id |  |
| author | TEXT | author |  |
| content | TEXT | content |  |
| parent_id | TEXT | parent_id |  |
| root_id | TEXT | root_id |  |
| reply_to | TEXT | reply_to |  |
| status | TEXT | status |  |
| release_id | TEXT | release_id |  |
| release_version | TEXT | release_version |  |

## 71. resource_feedback_notifications  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| resource_type | TEXT | resource_type |  |
| resource_id | TEXT | resource_id |  |
| recipient_user_id | TEXT | recipient_user_id |  |
| actor | TEXT | actor |  |
| comment_id | TEXT | comment_id |  |
| kind | TEXT | kind |  |
| status | TEXT | status |  |
| read_at | TIMESTAMPTZ | read_at |  |

## 72. resource_grants  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| resource_type | TEXT | resource_type |  |
| resource_id | TEXT | resource_id |  |
| recipient_user_id | TEXT | recipient_user_id |  |
| granted_by_user_id | TEXT | granted_by_user_id |  |
| can_reshare | BOOLEAN | can_reshare |  |
| status | TEXT | status |  |
| revoked_at | TIMESTAMPTZ | revoked_at |  |
| revoked_by_user_id | TEXT | revoked_by_user_id |  |
| revoke_reason | TEXT | revoke_reason |  |
| seen_at | TIMESTAMPTZ | seen_at |  |

## 73. resource_reactions  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| resource_type | TEXT | resource_type |  |
| resource_id | TEXT | resource_id |  |
| user_id | TEXT | user_id |  |
| reaction | TEXT | reaction |  |

## 74. risk_tiers  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| level | TEXT | level |  |
| rules | JSONB | rules | 是 |
| enabled | BOOLEAN | enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 80. scheduled_jobs  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| schedule_type | TEXT | schedule_type |  |
| schedule_expr | TEXT | schedule_expr |  |
| job_type | TEXT | job_type |  |
| job_config | JSONB | job_config | 是 |
| status | TEXT | status |  |
| enabled | BOOLEAN | enabled |  |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 85. site_profiles  [🔶部分平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| domain | TEXT | domain |  |
| status | TEXT | status |  |
| theme | TEXT | theme |  |
| settings | JSONB | settings | 是 |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 100. skills  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| type | TEXT | type |  |
| status | TEXT | status |  |
| version | TEXT | version |  |
| data | JSONB | data | 是 |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |

## 104. tenants  [✅全平铺]

| 列名 | 推断类型 | doc_key | JSONB |
|------|---------|---------|-------|
| name | TEXT | name |  |
| description | TEXT | description |  |
| status | TEXT | status |  |
| contact_email | TEXT | contact_email |  |
| contact_phone | TEXT | contact_phone |  |
| address | TEXT | address |  |
| logo_url | TEXT | logo_url |  |
| settings | JSONB | settings | 是 |
| created_by | TEXT | created_by |  |
| updated_by | TEXT | updated_by |  |
| deleted_at | TIMESTAMPTZ | deleted_at |  |
