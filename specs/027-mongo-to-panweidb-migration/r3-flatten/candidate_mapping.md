# 候选 doc_key → column 映射表 (待确认)

生成依据: 各表 doc 实际 key (keys.txt) + 语义推断。置信度: 高/中/低; '-' = doc 无对应字段, 建议留空。


## admin_account_groups

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| parent_id | None | - | doc 无 parent 字段, 留空 |
| sort_order | None | - | doc 无, 留空 |

## admin_accounts

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| login_name | username | 高 | 登录名对应 username |
| password_algorithm | None | - | doc 仅有 password_hash/password_salt, 无算法字段, 留空 |
| name | display_name | 中 | display_name 为显示名; 也可能指 role_name, 待确认 |
| avatar_url | None | - | doc 无头像字段, 留空 |
| failed_login_count | None | - | doc 无, 留空 |
| locked_at | None | - | doc 无(有 is_protected), 留空 |
| last_login_ip | None | - | doc 无, 留空 |
| mfa_enabled | None | - | doc 无 mfa 字段(有 is_protected 但语义不同), 留空 |

## admin_model_instances

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| model_key | model_name | 中 | model_name 为模型标识 |
| label | display_name | 高 | display_name 即显示标签 |
| auth_type | None | - | doc 无 auth_type(有 api_key/secret), 留空 |
| sort_order | priority | 中 | priority 即优先级/排序 |

## admin_model_providers

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| base_url | default_base_url | 高 | default_base_url 即默认地址 |
| api_key_encrypted | None | - | doc 无 provider 级 api key, 留空 |
| is_default | None | - | doc 无 is_default, 留空 |
| sort_order | priority | 中 | priority 即排序 |

## agent_kernel_bindings

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| kernel_type | kernel | 中 | kernel 为内核类型 |
| kernel_id | kernel_session_id | 中 | kernel_session_id 为内核会话 |
| binding_type | None | - | doc 无明确绑定类型, 留空 |
| binding_ref | source_ref | 中 | source_ref 为源引用 |

## autonomy_matrix

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| name | None | - | doc 仅 cell/risk/level/decision, 结构完全不同, 留空 |
| description | None | - | 同上, 留空 |
| scope_type | None | - | 同上, 留空 |
| scope_ref | None | - | 同上, 留空 |
| rules | None | - | 同上, 留空 |
| enabled | None | - | 同上, 留空 |

## chat_messages

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| sender_type | role | 高 | role 即发送者角色 user/assistant |
| sender_id | user_id | 中 | user_id 为发送者(另有 runtime_owner) |
| content_type | None | - | doc 无 type(仅 content), 留空 |
| status | None | - | doc 无, 留空 |
| parent_id | None | - | doc 无父消息引用, 留空 |
| reply_to_id | None | - | doc 无, 留空 |

## chat_sessions

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| type | None | - | doc 无 type, 留空 |
| owner_user_id | user_id | 高 | user_id 即属主 |
| participant_ids | None | - | doc 无参与者列表, 留空 |
| status | None | - | doc 无, 留空 |
| last_message_id | None | - | doc 无消息ID列表, 留空 |

## end_user_org_relations

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| position_id | None | - | doc 仅 org_id/user_id/is_primary, 无 position, 留空 |
| role_type | None | - | doc 无, 留空 |
| status | None | - | doc 无(有 is_primary), 留空 |
| start_date | None | - | doc 无, 留空 |
| end_date | None | - | doc 无, 留空 |

## end_user_position_roles

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| position_id | role_id | 中 | role_id 即角色标识(可能对应 position) |
| role_name | None | - | doc 仅有 role_id, 无 name, 留空 |
| role_type | None | - | doc 无, 留空 |
| status | None | - | doc 无, 留空 |
| start_date | None | - | doc 无, 留空 |
| end_date | None | - | doc 无, 留空 |

## end_users

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| display_name | name | 高 | name 即用户显示名 |
| phone | mobile | 高 | mobile 即手机号 |
| avatar_url | None | - | doc 无, 留空 |
| password_algorithm | None | - | doc 无, 留空 |
| failed_login_count | None | - | doc 无, 留空 |
| locked_at | None | - | doc 无, 留空 |
| last_login_ip | None | - | doc 无, 留空 |
| mfa_enabled | None | - | doc 无, 留空 |

## external_search_configs

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| name | provider | 中 | provider 为供应商名; 也可能需新字段, 待确认 |
| api_key_encrypted | None | - | doc 中 key 在 config 内, 平铺列取不到, 留空 |
| endpoint | None | - | endpoint 在 config 内, 留空 |
| status | enabled | 低 | enabled 表示启用; 与 status 语义接近但不同, 待确认 |
| sort_order | priority | 中 | priority 即排序 |

## gatekeeper_rules

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| name | None | - | doc 仅 kind/mode 等, 结构不同, 留空 |
| description | None | - | 同上, 留空 |
| rule_type | None | - | 同上, 留空 |
| condition | None | - | 同上, 留空 |
| action | None | - | 同上, 留空 |
| priority | None | - | 同上, 留空 |
| enabled | None | - | 同上, 留空 |

## org_quota_policies

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| org_id | None | - | doc 仅 tenant_id, 无 org_id, 留空 |
| quota_type | None | - | doc 无, 留空 |
| quota_limit | total_tokens | 中 | total_tokens 即配额总量 |
| quota_unit | None | - | doc 无, 留空 |

## org_units

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| type | None | - | doc 无, 留空 |
| sort_order | None | - | doc 无, 留空 |
| leader_user_id | None | - | doc 无, 留空 |
| description | None | - | doc 无, 留空 |

## organizations

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| name | org_name | 高 | org_name 即组织名 |
| parent_id | None | - | doc 无, 留空 |
| path_ids | None | - | doc 无, 留空 |
| path_names | None | - | doc 无, 留空 |
| type | None | - | doc 无, 留空 |
| status | None | - | doc 无(有 edition/tier), 留空 |
| sort_order | None | - | doc 无, 留空 |
| description | None | - | doc 无, 留空 |
| contact_email | None | - | doc 无, 留空 |
| contact_phone | None | - | doc 无, 留空 |
| address | None | - | doc 无, 留空 |
| logo_url | None | - | doc 无, 留空 |
| settings | None | - | doc 无, 留空 |

## pii_policies

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| name | pii_type | 中 | pii_type 即策略类型名 |
| description | None | - | doc 无, 留空 |
| rules | strategy | 中 | strategy 即规则策略 |
| enabled | None | - | doc 无, 留空 |

## position_roles

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| type | None | - | doc 无, 留空 |
| level | None | - | doc 无, 留空 |
| sort_order | None | - | doc 无, 留空 |

## skills

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| status | is_active | 低 | is_active(bool) 近似 status; 类型 TEXT 列需 CAST, 待确认 |
| version | package_version | 高 | package_version 即版本号 |
| data | config | 中 | config(JSONB) 近似 data(JSONB) |

## tenants

| 列名 | 建议 doc_key | 置信度 | 理由 |
|------|-------------|--------|------|
| description | None | - | doc 无, 留空 |
| contact_email | None | - | doc 无, 留空 |
| contact_phone | None | - | doc 无, 留空 |
| address | None | - | doc 无, 留空 |
| logo_url | None | - | doc 无, 留空 |
| settings | None | - | doc 无, 留空 |
