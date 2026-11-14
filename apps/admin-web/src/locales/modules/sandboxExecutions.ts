// ③ Sandbox 执行记录页面的译文。
// 注：查询 / 状态 / 耗时 / Agent 等为全局通用标签，已在 messages.ts 内联定义，
// 此处仅补充本页面专属、尚未存在的 key。
export const sandboxExecutionMessages = {
  'Sandbox 执行记录': { 'zh-CN': 'Sandbox 执行记录', 'en-US': 'Sandbox Execution Records' },
  '按 Agent ID 过滤': { 'zh-CN': '按 Agent ID 过滤', 'en-US': 'Filter by Agent ID' },
  '完成时间': { 'zh-CN': '完成时间', 'en-US': 'Finished At' },
  '退出码': { 'zh-CN': '退出码', 'en-US': 'Exit Code' },
  '镜像': { 'zh-CN': '镜像', 'en-US': 'Image' },
  '调用 ID': { 'zh-CN': '调用 ID', 'en-US': 'Call ID' },
  '暂无执行记录。': { 'zh-CN': '暂无执行记录。', 'en-US': 'No execution records yet.' },
  '数据库暂不可用，以下为降级空视图（非真实无记录）。': {
    'zh-CN': '数据库暂不可用，以下为降级空视图（非真实无记录）。',
    'en-US': 'Database unavailable; this is a degraded empty view (not a real empty result).',
  },
} as const;
