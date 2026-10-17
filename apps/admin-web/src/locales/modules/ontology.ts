import type { LabelMap } from '../messages';

/**
 * Ontology catalog & ontology data-permission labels (030).
 *
 * 「本体清单」只做展示，不提供本体 CRUD（本体定义与数据都在业务系统）。
 * 用户级「我的可见本体」自查已迁移到 user-web（终端用户侧），admin-web 只保留
 * 清单展示与按用户汇总授权两个视图。
 */
export const ontologyMessages: Record<string, LabelMap> = {
  '本体清单': { 'zh-CN': '本体清单', 'en-US': 'Ontology Catalog' },
  '用户本体授权': { 'zh-CN': '用户本体授权', 'en-US': 'User Ontology Grants' },
  '全量清单': { 'zh-CN': '全量清单', 'en-US': 'Full Catalog' },
  '用户': { 'zh-CN': '用户', 'en-US': 'User' },
  '已授予本体': { 'zh-CN': '已授予本体', 'en-US': 'Granted Ontologies' },
  '授权条数': { 'zh-CN': '授权条数', 'en-US': 'Grants' },
  '其中可见': { 'zh-CN': '其中可见', 'en-US': 'Visible' },
  '已停用': { 'zh-CN': '已停用', 'en-US': 'Disabled' },
  '仅继承租户兜底': { 'zh-CN': '仅继承租户兜底', 'en-US': 'Tenant fallback only' },
  '未知用户': { 'zh-CN': '未知用户', 'en-US': 'Unknown user' },
  '本体清单加载失败': { 'zh-CN': '本体清单加载失败', 'en-US': 'Failed to load the ontology catalog' },
  '同步失败': { 'zh-CN': '同步失败', 'en-US': 'Sync failed' },
  '已同步 {count} 个本体': { 'zh-CN': '已同步 {count} 个本体', 'en-US': 'Synced {count} ontologies' },
  '开启本体数据权限拦截': { 'zh-CN': '开启本体数据权限拦截', 'en-US': 'Enable Ontology Enforcement' },
  '关闭本体数据权限拦截': { 'zh-CN': '关闭本体数据权限拦截', 'en-US': 'Disable Ontology Enforcement' },
  '开启拦截': { 'zh-CN': '开启拦截', 'en-US': 'Enable' },
  '关闭拦截': { 'zh-CN': '关闭拦截', 'en-US': 'Disable' },
  '开启后未匹配到授权的主体将按 fail-closed 判定为不可见（deny）。请确认已完成授权配置。': {
    'zh-CN': '开启后未匹配到授权的主体将按 fail-closed 判定为不可见（deny）。请确认已完成授权配置。',
    'en-US': 'Once enabled, subjects without a matching grant are treated as invisible (deny, fail-closed). Confirm grants are configured first.',
  },
  '关闭后本体数据权限仅做配置与预演，不拦截任何查询。': {
    'zh-CN': '关闭后本体数据权限仅做配置与预演，不拦截任何查询。',
    'en-US': 'Once disabled, ontology data permission is configuration and rehearsal only; no query is blocked.',
  },
  '本体数据权限已开启：未匹配到授权的主体按 fail-closed 判定为不可见（deny）。': {
    'zh-CN': '本体数据权限已开启：未匹配到授权的主体按 fail-closed 判定为不可见（deny）。',
    'en-US': 'Enforcement is on: subjects without a matching grant are invisible (deny, fail-closed).',
  },
  '当前为预演模式（enforce=false）：授权只做配置与展示，不拦截任何查询。': {
    'zh-CN': '当前为预演模式（enforce=false）：授权只做配置与展示，不拦截任何查询。',
    'en-US': 'Rehearsal mode (enforce=false): grants are configuration and display only; nothing is blocked.',
  },
  '配置版本 rev={rev}': { 'zh-CN': '配置版本 rev={rev}', 'en-US': 'Config revision rev={rev}' },
  '清单聚合自 MOGO 侧业务实体索引的 ontology_id，并补上已授权但索引未出现的本体；本体 CRUD 不在 MOGO 侧。': {
    'zh-CN': '清单聚合自 MOGO 侧业务实体索引的 ontology_id，并补上已授权但索引未出现的本体；本体 CRUD 不在 MOGO 侧。',
    'en-US': 'The catalog aggregates ontology_id from the MOGO business-entity index and adds granted-but-unindexed ontologies; ontology CRUD is not part of MOGO.',
  },
  '按用户汇总 subject_type=user 的本体授权；租户兜底授权不归属任何用户。同一本体按优先级高者胜、同优先级取更严格模式。单个用户的授予与撤销在「用户管理」的用户行操作。': {
    'zh-CN': '按用户汇总 subject_type=user 的本体授权；租户兜底授权不归属任何用户。同一本体按优先级高者胜、同优先级取更严格模式。单个用户的授予与撤销在「用户管理」的用户行操作。',
    'en-US': 'Per-user summary of subject_type=user grants; tenant fallback grants belong to no user. For the same ontology the higher priority wins and ties take the stricter mode. Grant or revoke a single user from the user row in “Users”.',
  },
  '本体定义与数据都在业务系统，MOGO 侧只做只读展示与数据范围授权。': {
    'zh-CN': '本体定义与数据都在业务系统，MOGO 侧只做只读展示与数据范围授权。',
    'en-US': 'Ontology definitions and data live in the business systems; MOGO only provides read-only display and data-scope grants.',
  },
  '本体标识': { 'zh-CN': '本体标识', 'en-US': 'Ontology' },
  '类型标签': { 'zh-CN': '类型标签', 'en-US': 'Entity Types' },
  '索引实体数': { 'zh-CN': '索引实体数', 'en-US': 'Indexed Entities' },
  '已配置授权': { 'zh-CN': '已配置授权', 'en-US': 'Grants' },
  '未标注': { 'zh-CN': '未标注', 'en-US': 'Untagged' },
};
