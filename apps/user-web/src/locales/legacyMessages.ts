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

  // 模板硬编码中文（check_web_i18n_keys 加固后暴露的既存项）
  'SOP 模板': { zh: 'SOP 模板', en: 'SOP templates' },
  'mock 数据（001 端到端验收通过后切换真实数据源）': { zh: 'mock 数据（001 端到端验收通过后切换真实数据源）', en: 'Mock data (switch to the real data source after 001 E2E acceptance)' },
  '从广场复制模板到你名下，得到可编辑副本；原件只读，不受影响。': { zh: '从广场复制模板到你名下，得到可编辑副本；原件只读，不受影响。', en: 'Copy a template from the plaza to get an editable copy; the original stays read-only and unchanged.' },
  '例如：钉钉': { zh: '例如：钉钉', en: 'e.g. DingTalk' },
  '保存': { zh: '保存', en: 'Save' },
  '全部': { zh: '全部', en: 'All' },
  '再生成': { zh: '再生成', en: 'Regenerate' },
  '加载中…': { zh: '加载中…', en: 'Loading…' },
  '只有项目创建者可以管理成员，你可以查看当前成员。': { zh: '只有项目创建者可以管理成员，你可以查看当前成员。', en: 'Only the project creator can manage members; you can view the current list.' },
  '员工模板': { zh: '员工模板', en: 'Employee templates' },
  '复制到我的': { zh: '复制到我的', en: 'Copy to mine' },
  '定时任务正在运行': { zh: '定时任务正在运行', en: 'Scheduled task is running' },
  '定时任务自动发送': { zh: '定时任务自动发送', en: 'Scheduled task sends automatically' },
  '搜索姓名 / 账号 / 手机号': { zh: '搜索姓名 / 账号 / 手机号', en: 'Search name / account / phone' },
  '暂无模板': { zh: '暂无模板', en: 'No templates' },
  '暂无部门数据': { zh: '暂无部门数据', en: 'No department data' },
  '模板广场': { zh: '模板广场', en: 'Template plaza' },
  '竞品深度调研': { zh: '竞品深度调研', en: 'Competitor deep research' },
  '综合判断': { zh: '综合判断', en: 'Overall assessment' },
  '网络已断开，部分功能可能不可用': { zh: '网络已断开，部分功能可能不可用', en: 'Network is offline; some features may be unavailable' },
  '该部门下没有可选成员': { zh: '该部门下没有可选成员', en: 'No selectable members in this department' },
  '跳转到主内容': { zh: '跳转到主内容', en: 'Skip to main content' },
  '输入竞品名开始；报告将以四章分栏呈现，综合判断置顶。': { zh: '输入竞品名开始；报告将以四章分栏呈现，综合判断置顶。', en: 'Start by entering a competitor name; the report has four sections with the overall assessment on top.' },
  '输入竞品名，一次交互得到 analyst-grade 调研报告：市场情报 · 功能对比 · 财务估值 · 社媒舆情 + 综合判断': { zh: '输入竞品名，一次交互得到 analyst-grade 调研报告：市场情报 · 功能对比 · 财务估值 · 社媒舆情 + 综合判断', en: 'Enter a competitor name for an analyst-grade report in one interaction: market intelligence · feature comparison · valuation · social sentiment + overall assessment' },

  // 既有中文 t() key 补译（占位符/转义类）
  'project_id="default" 不可承载项目记忆，请改选具体项目。': { zh: 'project_id="default" 不可承载项目记忆，请改选具体项目。', en: 'project_id="default" cannot hold project memories; select a specific project.' },
  '有 {count} 条共享给你的记忆': { zh: '有 {count} 条共享给你的记忆', en: '{count} memories shared with you' },
  '有 {count} 条记忆接近衰减窗口': { zh: '有 {count} 条记忆接近衰减窗口', en: '{count} memories are nearing the decay window' },
  'project_id="default" 不可承载项目记忆': { zh: 'project_id="default" 不可承载项目记忆', en: 'project_id="default" cannot hold project memories' },
  '等待管理员审批，落 feature="017" memory.promoted 审计': { zh: '等待管理员审批，落 feature="017" memory.promoted 审计', en: 'Awaiting administrator approval; writes a feature="017" memory.promoted audit entry' },

  // 既有中文 t() key 补译
  '记忆详情': { zh: '记忆详情', en: 'Memory Details' },
  '范围': { zh: '范围', en: 'Scope' },
  '个人': { zh: '个人', en: 'Personal' },
  '项目': { zh: '项目', en: 'Project' },
  '部门': { zh: '部门', en: 'Department' },
  '实际范围': { zh: '实际范围', en: 'Actual Scope' },
  '解析来源': { zh: '解析来源', en: 'Resolved From' },
  '地址': { zh: '地址', en: 'Address' },
  '来源类型': { zh: '来源类型', en: 'Source Type' },
  '会话沉淀': { zh: '会话沉淀', en: 'Session Capture' },
  '手动': { zh: '手动', en: 'Manual' },
  '来源会话': { zh: '来源会话', en: 'Source Session' },
  '内容分层': { zh: '内容分层', en: 'Content Layers' },
  '摘要': { zh: '摘要', en: 'Summary' },
  '（暂无 L0 摘要）': { zh: '（暂无 L0 摘要）', en: '(No L0 summary)' },
  '概览': { zh: '概览', en: 'Overview' },
  '（暂无 L1 概览）': { zh: '（暂无 L1 概览）', en: '(No L1 overview)' },
  '原始全文': { zh: '原始全文', en: 'Full Text' },
  '（暂无 L2 全文）': { zh: '（暂无 L2 全文）', en: '(No L2 full text)' },
  '（暂无）': { zh: '（暂无）', en: '(None)' },
  '该项目成员由「成员」入口管理（049），此处仅只读展示。': { zh: '该项目成员由「成员」入口管理（049），此处仅只读展示。', en: 'Project members are managed in Members (049). Read-only here.' },
  '未选择记忆': { zh: '未选择记忆', en: 'No memory selected' },
  '我的记忆': { zh: '我的记忆', en: 'My Memories' },
  '共享给我': { zh: '共享给我', en: 'Shared with Me' },
  '「共享给我」= project / department 范围内他人创建的可见记忆；项目成员由「成员」入口管理（049），此处不编辑成员。': { zh: '「共享给我」= project / department 范围内他人创建的可见记忆；项目成员由「成员」入口管理（049），此处不编辑成员。', en: 'Shared with Me shows others\' visible memories in project / department scope. Manage members in Members (049); not editable here.' },
  '搜索记忆内容': { zh: '搜索记忆内容', en: 'Search memories' },
  '全部范围': { zh: '全部范围', en: 'All Scopes' },
  '全部状态': { zh: '全部状态', en: 'All Statuses' },
  '新建记忆': { zh: '新建记忆', en: 'Create Memory' },
  '已归档': { zh: '已归档', en: 'Archived' },
  '正常': { zh: '正常', en: 'Normal' },
  '（无摘要）': { zh: '（无摘要）', en: '(No summary)' },
  '详情': { zh: '详情', en: 'Details' },
  '编辑': { zh: '编辑', en: 'Edit' },
  '申请提升': { zh: '申请提升', en: 'Request Promotion' },
  '删除': { zh: '删除', en: 'Delete' },
  '加载中': { zh: '加载中', en: 'Loading...' },
  '暂无记忆': { zh: '暂无记忆', en: 'No memories yet' },
  '加载更多': { zh: '加载更多', en: 'Load More' },
  '编辑记忆': { zh: '编辑记忆', en: 'Edit Memory' },
  '内容': { zh: '内容', en: 'Content' },
  '记忆正文，服务端据此生成 L0/L1/L2 分层': { zh: '记忆正文，服务端据此生成 L0/L1/L2 分层', en: 'Memory body; the server generates L0/L1/L2 layers from it.' },
  '范围（由服务端解析最终归属）': { zh: '范围（由服务端解析最终归属）', en: 'Scope (resolved by server)' },
  '选择项目（default 不可承载项目记忆）': { zh: '选择项目（default 不可承载项目记忆）', en: 'Select a project (default can\'t hold project memories)' },
  '选择可见部门': { zh: '选择可见部门', en: 'Select a department' },
  '摘要（可选，服务端可回填）': { zh: '摘要（可选，服务端可回填）', en: 'Summary (optional, server can backfill)' },
  '留空由服务端生成': { zh: '留空由服务端生成', en: 'Leave blank to let the server generate' },
  '概览（可选）': { zh: '概览（可选）', en: 'Overview (optional)' },
  'project_owner_id 由服务端解析，客户端传值会被忽略；范围仅 personal / project / department。': { zh: 'project_owner_id 由服务端解析，客户端传值会被忽略；范围仅 personal / project / department。', en: 'project_owner_id is resolved by the server; client values are ignored. Scope is personal / project / department only.' },
  '个人 + 我创建的共享范围': { zh: '个人 + 我创建的共享范围', en: 'Personal + shared scopes I created' },
  'project / department 他人创建': { zh: 'project / department 他人创建', en: 'Created by others in project / department' },
  '本月沉淀': { zh: '本月沉淀', en: 'Captured this month' },
  '会话自动沉淀': { zh: '会话自动沉淀', en: 'Auto-captured from chats' },
  '即将衰减': { zh: '即将衰减', en: 'Decaying soon' },
  '近 23 天未命中（近似）': { zh: '近 23 天未命中（近似）', en: 'No hits in ~23 days (approx.)' },
  '共享记忆': { zh: '共享记忆', en: 'Shared Memories' },
  '加载失败': { zh: '加载失败', en: 'Failed to load' },
  '请填写记忆内容': { zh: '请填写记忆内容', en: 'Enter memory content' },
  '记忆已保存': { zh: '记忆已保存', en: 'Memory saved' },
  '范围由服务端解析并回显 actual_scope / resolved_from': { zh: '范围由服务端解析并回显 actual_scope / resolved_from', en: 'Scope is resolved by the server and shown as actual_scope / resolved_from' },
  '删除记忆': { zh: '删除记忆', en: 'Delete Memory' },
  '仅可删除自己的记忆，删除后不可恢复。确认删除？': { zh: '仅可删除自己的记忆，删除后不可恢复。确认删除？', en: 'You can only delete your own memories. This cannot be undone. Delete?' },
  '已删除': { zh: '已删除', en: 'Deleted' },
  '请先选择目标部门（提升为 department 级）': { zh: '请先选择目标部门（提升为 department 级）', en: 'Select a target department first (promote to department level)' },
  '提升申请已提交': { zh: '提升申请已提交', en: 'Promotion request submitted' },
  '提交失败': { zh: '提交失败', en: 'Submission failed' },
  '处理要求': { zh: '处理要求', en: 'Processing Requirements' },
  '已生成': { zh: '已生成', en: 'Generated' },
  '未生成': { zh: '未生成', en: 'Not generated' },
  '重新生成': { zh: '重新生成', en: 'Regenerate' },
  '生成代码': { zh: '生成代码', en: 'Generate Code' },
  '用自然语言描述要处理什么、输入是什么、输出什么。': { zh: '用自然语言描述要处理什么、输入是什么、输出什么。', en: 'Describe in plain language what to process, the input, and the output.' },
  '示例': { zh: '示例', en: 'Examples' },
  '上传文档：读取用户上传的 Word 或 PDF，删除说明文字和空段落，提取标题、表格和图片，按指定顺序重排，输出新的 Word 文件。': { zh: '上传文档：读取用户上传的 Word 或 PDF，删除说明文字和空段落，提取标题、表格和图片，按指定顺序重排，输出新的 Word 文件。', en: 'Upload documents: read user-uploaded Word or PDF files, remove descriptions and empty paragraphs, extract titles, tables and images, reorder as specified, and output a new Word file.' },
  '工具结果：读取上游工具返回的客户或订单数据，统一字段名和日期格式，去除重复记录，计算每类数量和金额汇总，输出 JSON 或 Excel。': { zh: '工具结果：读取上游工具返回的客户或订单数据，统一字段名和日期格式，去除重复记录，计算每类数量和金额汇总，输出 JSON 或 Excel。', en: 'Tool results: read customer or order data from upstream tools, unify field names and date formats, remove duplicates, compute counts and amount totals per category, and output JSON or Excel.' },
  '网页采集：读取爬取回来的多篇网页正文，去掉导航和广告文本，提取标题、发布时间、正文和链接，按来源分组输出结构化数据。': { zh: '网页采集：读取爬取回来的多篇网页正文，去掉导航和广告文本，提取标题、发布时间、正文和链接，按来源分组输出结构化数据。', en: 'Web scraping: read crawled article bodies, remove navigation and ad text, extract titles, publish times, body and links, and output structured data grouped by source.' },
  '高级': { zh: '高级', en: 'Advanced' },
  '节点要求': { zh: '节点要求', en: 'Node Requirements' },
  '查看使用说明与示例': { zh: '查看使用说明与示例', en: 'View usage guide and examples' },
  '使用场景': { zh: '使用场景', en: 'Use Cases' },
  '执行顺序预览': { zh: '执行顺序预览', en: 'Execution Order Preview' },
  '查看当前 Skill 的节点执行顺序': { zh: '查看当前 Skill 的节点执行顺序', en: 'View the node execution order of the current Skill' },
  '数据处理高级设置': { zh: '数据处理高级设置', en: 'Data Processing Advanced Settings' },
  '重新生成代码': { zh: '重新生成代码', en: 'Regenerate Code' },
  '生成处理代码': { zh: '生成处理代码', en: 'Generate Processing Code' },
  '节点规范': { zh: '节点规范', en: 'Node Specs' },
  '数据处理节点规范': { zh: '数据处理节点规范', en: 'Data Processing Node Specs' },
  '入口': { zh: '入口', en: 'Entry' },
  '标准输入': { zh: '标准输入', en: 'Standard Input' },
  '输出文件': { zh: '输出文件', en: 'Output Files' },
  '返回结果': { zh: '返回结果', en: 'Return Result' },
  '限制：禁止联网、子进程、eval/exec、固定本机路径；输出只支持 docx/pdf/xlsx/pptx/txt/md/json/csv。': { zh: '限制：禁止联网、子进程、eval/exec、固定本机路径；输出只支持 docx/pdf/xlsx/pptx/txt/md/json/csv。', en: 'Limits: no networking, subprocesses, eval/exec, or hardcoded local paths. Output supports only docx/pdf/xlsx/pptx/txt/md/json/csv.' },
  '代码尚未填写。可以手写代码，或点击生成处理代码。保存前需要通过检测。': { zh: '代码尚未填写。可以手写代码，或点击生成处理代码。保存前需要通过检测。', en: 'No code yet. Write it manually or click Generate Processing Code. It must pass validation before saving.' },
  '按 Tab 插入缩进，必须定义 run(inputs, context)': { zh: '按 Tab 插入缩进，必须定义 run(inputs, context)', en: 'Press Tab to indent. Define run(inputs, context).' },
  'Python 脚本需定义 run(inputs, context)，返回 { files, data, logs }': { zh: 'Python 脚本需定义 run(inputs, context)，返回 { files, data, logs }', en: 'Python scripts must define run(inputs, context) and return { files, data, logs }.' },
  '检测代码': { zh: '检测代码', en: 'Validate Code' },
  'AI 修复代码': { zh: 'AI 修复代码', en: 'AI Fix Code' },
  '检测通过': { zh: '检测通过', en: 'Validation Passed' },
  '检测未通过': { zh: '检测未通过', en: 'Validation Failed' },
  '代码已通过规则检测。': { zh: '代码已通过规则检测。', en: 'Code passed rule validation.' },
  '代码未通过检测，请查看下方问题或点击 AI 修复代码。': { zh: '代码未通过检测，请查看下方问题或点击 AI 修复代码。', en: 'Code failed validation. Check the issues below or click AI Fix Code.' },
  '错误': { zh: '错误', en: 'Error' },
  '警告': { zh: '警告', en: 'Warning' },
  '检测未通过，但检测服务没有返回具体错误明细。建议点击 AI 修复代码，或检查是否使用了不支持的输入/输出写法。': { zh: '检测未通过，但检测服务没有返回具体错误明细。建议点击 AI 修复代码，或检查是否使用了不支持的输入/输出写法。', en: 'Validation failed, but no details were returned. Try AI Fix Code, or check for unsupported input/output patterns.' },
  '重新生成会覆盖当前高级代码，是否继续？': { zh: '重新生成会覆盖当前高级代码，是否继续？', en: 'Regenerating will overwrite the current advanced code. Continue?' },
  '已生成代码并通过规则检测': { zh: '已生成代码并通过规则检测', en: 'Code generated and passed rule validation' },
  '已生成代码，请根据检测结果修复后保存': { zh: '已生成代码，请根据检测结果修复后保存', en: 'Code generated; fix any issues and save' },
  'AI 生成代码失败': { zh: 'AI 生成代码失败', en: 'AI failed to generate code' },
  '请先填写处理要求': { zh: '请先填写处理要求', en: 'Fill in the processing requirements first' },
  'AI 未返回可用代码': { zh: 'AI 未返回可用代码', en: 'AI returned no usable code' },
  '检测脚本代码失败': { zh: '检测脚本代码失败', en: 'Failed to validate script code' },
  '请先填写脚本代码': { zh: '请先填写脚本代码', en: 'Fill in the script code first' },
  '脚本代码检测通过': { zh: '脚本代码检测通过', en: 'Script code passed validation' },
  'AI 修复代码失败': { zh: 'AI 修复代码失败', en: 'AI failed to fix the code' },
  '已完成 AI 修复，请再次确认代码': { zh: '已完成 AI 修复，请再次确认代码', en: 'AI fix complete; review the code again' },
  '数据处理节点必须先填写处理要求': { zh: '数据处理节点必须先填写处理要求', en: 'Data processing nodes require processing requirements first' },
  '请先填写或生成脚本代码': { zh: '请先填写或生成脚本代码', en: 'Fill in or generate the script code first' },
  '脚本代码已变更或尚未检测通过，请先点击检测代码': { zh: '脚本代码已变更或尚未检测通过，请先点击检测代码', en: 'Script code changed or hasn\'t passed validation. Click Validate Code first.' },
  '已禁用': { zh: '已禁用', en: 'Disabled' },
  '启用': { zh: '启用', en: 'Enable' },
  '返回': { zh: '返回', en: 'Back' },
  '名称': { zh: '名称', en: 'Name' },
  '失败': { zh: '失败', en: 'Failed' },
  '关闭': { zh: '关闭', en: 'Close' },
} as const
