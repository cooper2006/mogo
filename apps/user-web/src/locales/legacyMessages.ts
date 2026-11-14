/**
 * Translations for keys that never received a catalogue entry.
 *
 * Two groups live here:
 *  - `legacy.*` — keys slugified from historical English copy, so the key
 *    itself carries the source wording while the entry carries the localised
 *    text.
 *  - namespaced keys (`session.*`, `invite.*`, `chat.*`, …) that were added
 *    to the views directly.
 *
 * The i18n helper falls back to echoing the key when no entry exists, which
 * leaked raw identifiers such as `legacy.username` into the UI.
 */
export const legacyMessages = {
  // ── 浏览器标签页 ──
  'legacy.new_tab': { zh: '新标签页', en: 'New tab' },
  'legacy.close_tab': { zh: '关闭标签页', en: 'Close tab' },
  'legacy.new_tab_7b451ec': { zh: '新建标签页', en: 'New tab' },
  'legacy.resize_chat_and_browser_panes': { zh: '调整对话与浏览器面板的大小', en: 'Resize the chat and browser panes' },

  // ── 任务指引 ──
  'legacy.task_guide': { zh: '任务指引', en: 'Task guide' },
  'legacy.setup_required': { zh: '需要先完成配置', en: 'Setup required' },
  'legacy.configure': { zh: '去配置', en: 'Configure' },

  // ── 消息操作 ──
  'legacy.message_actions': { zh: '消息操作', en: 'Message actions' },
  'legacy.copied': { zh: '已复制', en: 'Copied' },
  'legacy.copy_message': { zh: '复制消息', en: 'Copy message' },
  'legacy.copy': { zh: '复制', en: 'Copy' },
  'legacy.create_scheduled_task': { zh: '创建定时任务', en: 'Create a scheduled task' },

  // ── 能力前置配置引导 ──
  'legacy.set_up_internal_knowledge_first': { zh: '请先配置内部知识库', en: 'Set up internal knowledge first' },
  'legacy.set_up_a_knowledge_base_or_upload_internal_material': { zh: '创建知识库或上传内部资料后即可使用', en: 'Set up a knowledge base or upload internal material' },
  'legacy.set_up_a_connected_system_first': { zh: '请先接入一个外部系统', en: 'Set up a connected system first' },
  'legacy.set_up_an_http_tool_or_mcp_service_first': { zh: '配置 HTTP 工具或 MCP 服务后即可使用', en: 'Set up an HTTP tool or MCP service first' },
  'legacy.setup_required_d047e4f': { zh: '需要先完成配置', en: 'Setup required' },
  'legacy.complete_setup_before_using_this_capability': { zh: '完成上述配置后才能使用该能力', en: 'Complete the setup before using this capability' },

  // ── 会话运行状态 ──
  'session.run.other_running': { zh: '{name} 正在运行', en: '{name} is running' },
  'session.run.finished_refresh': { zh: '运行已结束，刷新查看', en: 'The run has finished. Refresh to see it' },
  'session.run.refreshing': { zh: '刷新中……', en: 'Refreshing…' },
  'session.run.refresh': { zh: '刷新', en: 'Refresh' },
  'session.run.another_member': { zh: '其他成员', en: 'Another member' },
  'session.run.refresh_failed': { zh: '刷新失败', en: 'Failed to refresh' },

  // ── 会话快照 ──
  'session.snapshot.createFailed': { zh: '快照创建失败', en: 'Failed to create the snapshot' },
  'session.snapshot.revokeFailed': { zh: '快照撤销失败', en: 'Failed to revoke the snapshot' },
  'session.snapshot.title': { zh: '会话快照', en: 'Session snapshot' },
  'session.snapshot.hint': { zh: '创建一份会话快照，生成可分享的只读副本。', en: 'Create a session snapshot to generate a shareable read-only copy.' },
  'session.snapshot.create': { zh: '创建快照', en: 'Create snapshot' },
  'session.snapshot.user': { zh: '用户', en: 'User' },
  'session.snapshot.assistant': { zh: '助手', en: 'Assistant' },
  'session.snapshot.readOnly': { zh: '只读快照', en: 'Read-only snapshot' },
  'session.snapshot.unavailable': { zh: '快照不可用', en: 'The snapshot is unavailable' },

  // ── 邀请注册 ──
  'invite.invalid': { zh: '邀请码无效', en: 'The invite code is invalid' },
  'invite.required': { zh: '请填写邀请码、登录名和姓名', en: 'Please fill in the invite code, login name, and name' },
  'invite.password_rule': { zh: '密码至少 10 位，且两次输入需一致', en: 'The password must be at least 10 characters and both entries must match' },
  'invite.join_org': { zh: '你将加入组织「{org}」', en: 'You will join the organization "{org}"' },
  'invite.code': { zh: '邀请码', en: 'Invite code' },
  'invite.verify': { zh: '校验', en: 'Verify' },
  'invite.username': { zh: '登录名', en: 'Username' },
  'invite.name': { zh: '姓名', en: 'Name' },
  'invite.email': { zh: '邮箱', en: 'Email' },
  'invite.password': { zh: '密码', en: 'Password' },
  'invite.confirm_password': { zh: '确认密码', en: 'Confirm password' },
  'invite.submitting': { zh: '提交中……', en: 'Submitting…' },
  'invite.register': { zh: '注册并加入', en: 'Register and join' },

  // ── 文档编辑与重新生成 ──
  'chat.docx_edit_source_failed': { zh: 'DOCX 编辑源加载失败', en: 'Failed to load the DOCX edit source' },
  'chat.docx_edit_source_empty': { zh: 'DOCX 内容为空，无法编辑', en: 'The DOCX has no content to edit' },
  'chat.presentation_edit_unavailable': { zh: '当前演示文稿暂不支持编辑', en: 'Editing is not available for this presentation' },
  'chat.presentation_edit_load_failed': { zh: '演示文稿加载失败', en: 'Failed to load the presentation' },
  'chat.regenerate_source_warning': { zh: '原始内容已变更，重新生成的结果可能与原文不一致', en: 'The source content changed, so the regenerated result may differ from the original' },
  'chat.regenerate_success': { zh: '重新生成成功', en: 'Regenerated successfully' },
  'chat.regenerate_failed': { zh: '重新生成失败', en: 'Failed to regenerate' },

  // ── 代码权限 ──
  'code.history_restoring': { zh: '正在恢复历史版本……', en: 'Restoring history…' },
  'code.permission.invalidConfig': { zh: '代码权限配置无效', en: 'The code permission config is invalid' },
  'code.permission.heading': { zh: '代码权限', en: 'Code permissions' },
  'code.permission.editConfig': { zh: '编辑配置', en: 'Edit config' },
  'code.permission.applyNextTurn': { zh: '将在下一轮对话中生效', en: 'Takes effect from the next turn' },
  'code.permission.networkLimit': { zh: '网络访问受限', en: 'Network access is restricted' },

  // ── 插件快捷键 ──
  'plugins.shortcuts': { zh: '快捷键', en: 'Shortcuts' },
  'plugins.moreShortcuts': { zh: '还有 {count} 个快捷键', en: '{count} more shortcuts' },
  'plugins.uiOriginRequired': { zh: '插件界面必须与当前站点同源', en: 'The plugin UI must share the origin with this site' },

  // ── 侧边栏 ──
  'app.sidebar.project_folder_unavailable': { zh: '项目文件夹不可用，仅保留会话历史', en: 'The project folder is unavailable; only the session history is kept' },
  'app.sidebar.project_history_only': { zh: '仅历史', en: 'History only' },

  // ── 证据来源 ──
  'evidence.external_knowledge': { zh: '外部知识', en: 'External knowledge' },
  'evidence.open_external_document': { zh: '打开外部文档', en: 'Open the external document' },

  // ── 工作流预设 ──
  'workflow.preset.review_check.label': { zh: '复核检查', en: 'Review check' },
  'workflow.preset.review_check.placeholder': { zh: '例如：复核上游生成的结论，逐条给出判断与依据', en: 'Example: review the conclusions produced upstream, giving a verdict and evidence for each' },

  // ── 执行视图 ──
  'execution.v3.connection_lost': { zh: '连接已断开', en: 'The connection was lost' },
  'execution.v3.tool_attempt_details': { zh: '工具调用详情', en: 'Tool attempt details' },

  // ── 接口错误 ──
  'api.auth.register_failed': { zh: '注册失败', en: 'Registration failed' },

  // ── 记忆溯源 ──
  'Provenance': { zh: '来源信息', en: 'Provenance' },

  // ── 产物 ──
  'artifact.download_to_edit': { zh: '下载后编辑', en: 'Download to edit' },

  // ── 无障碍与占位提示（原先硬编码在模板里，未走 i18n）──
  '墨攻': { zh: '墨攻', en: 'MOGO' },
  '选择我的 Tool / MCP': { zh: '选择我的 Tool / MCP', en: 'Select my Tool / MCP' },
} as const
