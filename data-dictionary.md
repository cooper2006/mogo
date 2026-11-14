# MOGO 数据字典

本文档枚举 MongoDB 核心集合、字段含义、取值范围与责任人。

## 集合清单

| 集合 | 用途 | 责任人 | 敏感级别 |
| --- | --- | --- | --- |
| `users` | 用户账户 | @cooper2006 | 高 |
| `organizations` | 组织/团队 | @cooper2006 | 中 |
| `site_profiles` | 站点配置 | @cooper2006 | 低 |
| `chat_sessions` | 聊天会话 | @cooper2006 | 中 |
| `chat_messages` | 聊天消息 | @cooper2006 | 中 |
| `project_memories` | 项目记忆 | @cooper2006 | 中 |
| `desktop_projects` | 桌面项目 | @cooper2006 | 中 |
| `knowledge_resources` | 知识资源 | @cooper2006 | 中 |
| `personal_knowledge_directories` | 个人知识目录 | @cooper2006 | 中 |
| `resource_grants` | 资源授权 | @cooper2006 | 低 |
| `resource_comments` | 资源评论 | @cooper2006 | 低 |
| `resource_comment_reactions` | 评论表情 | @cooper2006 | 低 |
| `resource_feedback_notifications` | 反馈通知 | @cooper2006 | 低 |
| `resource_reactions` | 资源表情 | @cooper2006 | 低 |
| `position_roles` | 岗位角色 | @cooper2006 | 低 |
| `position_role_audit_logs` | 角色审计日志 | @cooper2006 | 中 |
| `end_users` | 终端用户 | @cooper2006 | 高 |
| `end_user_sessions` | 终端用户会话 | @cooper2006 | 高 |
| `end_user_position_roles` | 终端用户角色 | @cooper2006 | 低 |
| `end_user_login_challenges` | 登录挑战 | @cooper2006 | 高 |
| `end_user_capability_overrides` | 能力覆盖 | @cooper2006 | 中 |
| `admin_accounts` | 管理员账户 | @cooper2006 | 高 |
| `agent_kernel_bindings` | 代理内核绑定 | @cooper2006 | 低 |
| `enterprise_tool_approvals` | 工具审批 | @cooper2006 | 中 |
| `enterprise_tool_audit` | 工具审计 | @cooper2006 | 中 |
| `external_tools` | 外部工具 | @cooper2006 | 中 |
| `execution_logs` | 执行日志 | @cooper2006 | 中 |
| `audit_logs` | 审计日志 | @cooper2006 | 高 |
| `scheduled_jobs` | 定时任务 | @cooper2006 | 低 |
| `token_usage_logs` | Token 用量日志 | @cooper2006 | 中 |

## 核心字段说明

### users 集合

| 字段 | 类型 | 含义 | 取值范围 | 敏感 |
| --- | --- | --- | --- | --- |
| `_id` | string | 用户 ID | 32 位 hex | 否 |
| `email` | string | 邮箱 | 唯一索引 | 是 |
| `password_hash` | string | 密码哈希 | bcrypt | 是 |
| `nickname` | string | 昵称 | 1-50 字符 | 否 |
| `avatar_url` | string | 头像 URL | URL | 否 |
| `role` | string | 角色 | admin/user | 否 |
| `tenant_id` | string | 租户 ID | 多租户隔离 | 否 |
| `created_at` | datetime | 创建时间 | UTC | 否 |
| `updated_at` | datetime | 更新时间 | UTC | 否 |
| `deleted_at` | datetime | 删除时间 | UTC/null | 否 |

### chat_sessions 集合

| 字段 | 类型 | 含义 | 取值范围 | 敏感 |
| --- | --- | --- | --- | --- |
| `_id` | string | 会话 ID | 32 位 hex | 否 |
| `user_id` | string | 用户 ID | 外键 | 否 |
| `title` | string | 会话标题 | 1-100 字符 | 否 |
| `model` | string | 模型名称 | gpt-4o 等 | 否 |
| `messages` | array | 消息列表 | 嵌套对象 | 中 |
| `created_at` | datetime | 创建时间 | UTC | 否 |
| `updated_at` | datetime | 更新时间 | UTC | 否 |

### token_usage_logs 集合

| 字段 | 类型 | 含义 | 取值范围 | 敏感 |
| --- | --- | --- | --- | --- |
| `_id` | string | 日志 ID | 32 位 hex | 否 |
| `user_id` | string | 用户 ID | 外键 | 否 |
| `request_id` | string | 请求 ID | 唯一 | 否 |
| `model` | string | 模型名称 | gpt-4o 等 | 否 |
| `prompt_tokens` | int | 输入 Token 数 | >=0 | 否 |
| `completion_tokens` | int | 输出 Token 数 | >=0 | 否 |
| `total_tokens` | int | 总 Token 数 | >=0 | 否 |
| `cost_usd` | float | 成本（美元） | >=0 | 否 |
| `created_at` | datetime | 创建时间 | UTC | 否 |

## 敏感字段分级

| 级别 | 字段 | 存储位置 | 加密方式 | 访问角色 |
| --- | --- | --- | --- | --- |
| 高 | `password_hash` | users.password_hash | bcrypt | 系统 |
| 高 | `email` | users.email | 明文（索引） | 系统/用户 |
| 高 | `session_token` | end_user_sessions.session_token | 加密 | 系统 |
| 中 | `chat_messages.content` | chat_messages | 明文 | 用户/系统 |
| 中 | `project_memories.content` | project_memories | 明文 | 用户/系统 |
| 低 | `nickname` | users.nickname | 明文 | 用户/系统 |

## 更多文档

- [隐私政策](privacy.md)
- [配置参考](configuration-reference.md)
- [安装指南](installation-guide.md)
