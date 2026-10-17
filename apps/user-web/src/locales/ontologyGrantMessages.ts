/**
 * 本体数据权限 —— 终端用户侧文案（030 user-web 迁移）。
 *
 * 本体定义与数据都在业务系统，MOGO 侧只做只读展示与数据范围授权；用户侧
 * 只回答「我被授予了哪些本体」，写入口在管理端。
 */
export const ontologyGrantMessages = {
  'ontology_grant.title': { zh: '我的本体授权', en: 'My Ontology Grants' },
  'ontology_grant.subtitle': {
    zh: '这里只做展示：你可以看到哪些本体，由管理员在管理端配置。本体定义与数据都在业务系统。',
    en: 'Read-only: which ontologies you can see is configured by an administrator. Ontology definitions and data live in the business systems.',
  },
  'ontology_grant.refresh': { zh: '刷新', en: 'Refresh' },
  'ontology_grant.load_failed': { zh: '本体授权加载失败', en: 'Failed to load ontology grants' },
  'ontology_grant.degraded': {
    zh: '本体授权暂时查询失败，本次结果为空。这不影响你使用其它功能，请稍后重试。',
    en: 'Ontology grants could not be loaded right now, so this view is empty. Your other features are unaffected — please retry later.',
  },
  'ontology_grant.empty': {
    zh: '当前没有本体授权。如果管理员开启了数据权限拦截，业务检索结果可能为空。',
    en: 'No ontology grants yet. If an administrator enabled enforcement, business search may return no results.',
  },
  'ontology_grant.disabled_hint': {
    zh: '有 {count} 条授权已被停用，不参与生效判定。',
    en: '{count} grant(s) are disabled and do not take effect.',
  },
  'ontology_grant.column_ontology': { zh: '本体标识', en: 'Ontology' },
  'ontology_grant.column_mode': { zh: '访问模式', en: 'Access mode' },
  'ontology_grant.column_source': { zh: '授权来源', en: 'Granted via' },
  'ontology_grant.column_visible': { zh: '是否可见', en: 'Visible' },
  'ontology_grant.column_priority': { zh: '优先级', en: 'Priority' },
  'ontology_grant.column_updated': { zh: '更新时间', en: 'Updated' },
  'ontology_grant.mode_read': { zh: '可读（read）', en: 'Read' },
  'ontology_grant.mode_write': { zh: '可写（write）', en: 'Write' },
  'ontology_grant.mode_none': { zh: '不可见（none）', en: 'Hidden' },
  'ontology_grant.source_tenant': { zh: '租户兜底授权', en: 'Tenant fallback' },
  'ontology_grant.source_user': { zh: '个人授权', en: 'Personal grant' },
  'ontology_grant.yes': { zh: '可见', en: 'Yes' },
  'ontology_grant.no': { zh: '不可见', en: 'No' },
  'ontology_grant.footnote': {
    zh: '同一本体可能同时存在租户兜底与个人授权：按优先级高者胜，同优先级取更严格的模式。如需调整授权，请联系管理员。',
    en: 'The same ontology may have both a tenant fallback and a personal grant: the higher priority wins, and ties resolve to the stricter mode. Contact an administrator to change grants.',
  },
  // 侧边栏入口
  'ontology_grant.sidebar': { zh: '本体授权', en: 'Ontology Grants' },
} as const
