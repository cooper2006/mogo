import type { LabelMap } from '../messages';

/**
 * UI copy that was introduced without a catalogue entry.
 *
 * These namespaces (`inviteHistory.*`, `skillDeps.*`, `directoryScope.*`) were
 * added to the views directly, so the i18n helper silently fell back to
 * echoing the key — the UI showed raw identifiers such as `inviteHistory.copied`.
 */
export const adminUiMessages: Record<string, LabelMap> = {
  // ── 邀请记录 ──
  'inviteHistory.loadFailed': { 'zh-CN': '邀请记录加载失败', 'en-US': 'Failed to load the invite history' },
  'inviteHistory.rootDepartment': { 'zh-CN': '根部门', 'en-US': 'Root department' },
  'inviteHistory.role': { 'zh-CN': '角色', 'en-US': 'Role' },
  'inviteHistory.copied': { 'zh-CN': '已复制', 'en-US': 'Copied' },
  'inviteHistory.copyFailed': { 'zh-CN': '复制失败', 'en-US': 'Copy failed' },
  'inviteHistory.revoked': { 'zh-CN': '邀请已撤销', 'en-US': 'Invite revoked' },
  'inviteHistory.revokeFailed': { 'zh-CN': '撤销失败', 'en-US': 'Failed to revoke the invite' },
  'inviteHistory.title': { 'zh-CN': '邀请记录', 'en-US': 'Invite history' },
  'inviteHistory.allDepartments': { 'zh-CN': '全部部门', 'en-US': 'All departments' },
  'inviteHistory.allStatuses': { 'zh-CN': '全部状态', 'en-US': 'All statuses' },
  'inviteHistory.refresh': { 'zh-CN': '刷新', 'en-US': 'Refresh' },
  'inviteHistory.empty': { 'zh-CN': '暂无邀请记录', 'en-US': 'No invite records' },
  'inviteHistory.total': { 'zh-CN': '共 {count} 条邀请', 'en-US': '{count} invites in total' },
  'inviteHistory.createdAt': { 'zh-CN': '创建时间', 'en-US': 'Created at' },
  'inviteHistory.members': { 'zh-CN': '已加入成员', 'en-US': 'Members' },
  'inviteHistory.expires': { 'zh-CN': '过期时间', 'en-US': 'Expires' },
  'inviteHistory.viewMembers': { 'zh-CN': '查看成员', 'en-US': 'View members' },
  'inviteHistory.copy': { 'zh-CN': '复制链接', 'en-US': 'Copy link' },
  'inviteHistory.copyCode': { 'zh-CN': '复制邀请码', 'en-US': 'Copy invite code' },
  'inviteHistory.revoke': { 'zh-CN': '撤销', 'en-US': 'Revoke' },
  'inviteHistory.membersLoadFailed': { 'zh-CN': '成员列表加载失败', 'en-US': 'Failed to load the members' },
  'inviteHistory.back': { 'zh-CN': '返回', 'en-US': 'Back' },
  'inviteHistory.link': { 'zh-CN': '邀请链接', 'en-US': 'Invite link' },
  'inviteHistory.code': { 'zh-CN': '邀请码', 'en-US': 'Invite code' },
  'inviteHistory.unattributed': { 'zh-CN': '有 {count} 名成员未归属到部门', 'en-US': '{count} members are not attributed to a department' },
  'inviteHistory.registeredMembers': { 'zh-CN': '已注册成员', 'en-US': 'Registered members' },
  'inviteHistory.noMembers': { 'zh-CN': '暂无成员', 'en-US': 'No members' },
  'inviteHistory.name': { 'zh-CN': '姓名', 'en-US': 'Name' },
  'inviteHistory.loginName': { 'zh-CN': '登录名', 'en-US': 'Login name' },
  'inviteHistory.email': { 'zh-CN': '邮箱', 'en-US': 'Email' },
  'inviteHistory.joinedAt': { 'zh-CN': '加入时间', 'en-US': 'Joined at' },
  'inviteHistory.memberStatus': { 'zh-CN': '成员状态', 'en-US': 'Member status' },
  'inviteHistory.deletedUser': { 'zh-CN': '已删除用户', 'en-US': 'Deleted user' },
  'inviteHistory.activeUser': { 'zh-CN': '正常用户', 'en-US': 'Active user' },
  'inviteHistory.disabledUser': { 'zh-CN': '已停用用户', 'en-US': 'Disabled user' },
  'inviteHistory.attributed': { 'zh-CN': '{count} 名成员已归属到部门', 'en-US': '{count} members attributed to a department' },

  // ── 技能依赖准备记录 ──
  'skillDeps.records.open': { 'zh-CN': '查看准备记录', 'en-US': 'View preparation records' },
  'skillDeps.records.title': { 'zh-CN': '依赖准备记录', 'en-US': 'Dependency preparation records' },
  'skillDeps.records.refresh': { 'zh-CN': '刷新', 'en-US': 'Refresh' },
  'skillDeps.records.empty': { 'zh-CN': '暂无准备记录', 'en-US': 'No preparation records' },
  'skillDeps.records.startedAt': { 'zh-CN': '开始时间', 'en-US': 'Started at' },
  'skillDeps.records.finishedAt': { 'zh-CN': '完成时间', 'en-US': 'Finished at' },
  'skillDeps.records.status': { 'zh-CN': '状态', 'en-US': 'Status' },
  'skillDeps.records.id': { 'zh-CN': '记录 ID', 'en-US': 'Record ID' },
  'skillDeps.records.digest': { 'zh-CN': '镜像摘要', 'en-US': 'Image digest' },
  'skillDeps.records.baseImage': { 'zh-CN': '基础镜像', 'en-US': 'Base image' },
  'skillDeps.records.log': { 'zh-CN': '构建日志', 'en-US': 'Build log' },
  'skillDeps.records.download': { 'zh-CN': '下载日志', 'en-US': 'Download log' },
  'skillDeps.records.truncated': { 'zh-CN': '日志内容过长，仅显示部分内容', 'en-US': 'The log is too long; only part of it is shown' },
  'skillDeps.records.logPending': { 'zh-CN': '日志生成中……', 'en-US': 'The log is still being generated…' },
  'skillDeps.records.noLog': { 'zh-CN': '该记录没有可下载的日志', 'en-US': 'This record has no downloadable log' },
  'skillDeps.records.downloadFailed': { 'zh-CN': '日志下载失败', 'en-US': 'Failed to download the log' },
  'skillDeps.records.loadFailed': { 'zh-CN': '准备记录加载失败', 'en-US': 'Failed to load the preparation records' },

  // ── 通讯录可见范围 ──
  'directoryScope.scope': { 'zh-CN': '可见范围', 'en-US': 'Scope' },
  'directoryScope.all': { 'zh-CN': '全组织', 'en-US': 'Whole organization' },
  'directoryScope.title': { 'zh-CN': '选择可见范围', 'en-US': 'Select the visible scope' },
  'directoryScope.allHint': { 'zh-CN': '当前范围为整个组织，组织内所有成员均可见。', 'en-US': 'The scope is the whole organization, so every member can see it.' },
  'directoryScope.searchDepartment': { 'zh-CN': '搜索部门', 'en-US': 'Search departments' },
  'directoryScope.loadFailed': { 'zh-CN': '通讯录加载失败', 'en-US': 'Failed to load the directory' },
  'directoryScope.searchUser': { 'zh-CN': '搜索用户', 'en-US': 'Search users' },
  'directoryScope.noUsers': { 'zh-CN': '未找到用户', 'en-US': 'No users found' },
  'directoryScope.selected': { 'zh-CN': '已选择', 'en-US': 'Selected' },
  'directoryScope.selectDepartment': { 'zh-CN': '请选择部门', 'en-US': 'Select a department' },
  'directoryScope.cancel': { 'zh-CN': '取消', 'en-US': 'Cancel' },
  'directoryScope.apply': { 'zh-CN': '应用', 'en-US': 'Apply' },

  // ── 技能安装 ──
  'skills.install_limit': { 'zh-CN': '仅支持 ZIP 格式的技能安装包', 'en-US': 'Only ZIP skill packages are supported' },

  // ── 品牌名与技术术语（两种语言保持一致）──
  'DeepSeek': { 'zh-CN': 'DeepSeek', 'en-US': 'DeepSeek' },
  'Azure OpenAI': { 'zh-CN': 'Azure OpenAI', 'en-US': 'Azure OpenAI' },
  'SHA-256': { 'zh-CN': 'SHA-256', 'en-US': 'SHA-256' },
  'fail-closed': { 'zh-CN': 'fail-closed', 'en-US': 'fail-closed' },

  // ── 归属人 ──
  'owner': { 'zh-CN': '负责人', 'en-US': 'Owner' },
  'Owner': { 'zh-CN': '负责人', 'en-US': 'Owner' },

  // ── 无障碍与占位提示（原先硬编码在模板里，未走 i18n）──
  '跳转到主内容': { 'zh-CN': '跳转到主内容', 'en-US': 'Skip to main content' },
  '墨攻': { 'zh-CN': '墨攻', 'en-US': 'MOGO' },
  '如: 2024-10-21': { 'zh-CN': '如: 2024-10-21', 'en-US': 'e.g. 2024-10-21' },
  '032-eval-gate：本 Skill 尚无评测报告，发布将进入 fail-closed 评测门禁（无测试集 / 样本不足 / LLM 超时都会阻断）。': {
    'zh-CN': '032-eval-gate：本 Skill 尚无评测报告，发布将进入 fail-closed 评测门禁（无测试集 / 样本不足 / LLM 超时都会阻断）。',
    'en-US': '032-eval-gate: this Skill has no evaluation report yet, so publishing goes through the fail-closed evaluation gate (a missing test set, insufficient samples, or an LLM timeout will all block it).',
  },
};
