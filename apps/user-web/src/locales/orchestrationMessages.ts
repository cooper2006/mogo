/**
 * 可视化编排画布 —— 终端用户侧文案（039 user-web）。
 *
 * 画布为投影、文档为权威：这里只描述画布操作文案；校验/环检测文案在
 * `canvasValidation.ts`（引擎侧同格式错误）。
 */
export const orchestrationMessages = {
  // 侧边栏 / 页面入口
  'orchestration.sidebar': { zh: '编排画布', en: 'Orchestration Canvas' },
  'orchestration.title': { zh: '可视化编排画布', en: 'Visual Orchestration Canvas' },
  'orchestration.subtitle': {
    zh: '以节点-连线方式编排 DAG 工作流，保存后可被编排引擎真实执行。文档为权威，画布为投影。',
    en: 'Compose DAG workflows with nodes and edges; the saved document is executed by the orchestration engine. The document is authoritative, the canvas is a projection.',
  },

  // 顶部动作
  'orchestration.back': { zh: '返回', en: 'Back' },
  'orchestration.refresh': { zh: '刷新', en: 'Refresh' },
  'orchestration.save': { zh: '保存草稿', en: 'Save Draft' },
  'orchestration.publish': { zh: '发布', en: 'Publish' },
  'orchestration.preview': { zh: '预览 / 试运行', en: 'Preview / Dry Run' },
  'orchestration.load_yaml': { zh: '打开现有编排', en: 'Open Existing' },
  'orchestration.saved': { zh: '已保存（版本 {version}）', en: 'Saved (version {version})' },
  'orchestration.published': { zh: '已发布（版本 {version}）', en: 'Published (version {version})' },

  // 节点类型
  'orchestration.node.start': { zh: '开始', en: 'Start' },
  'orchestration.node.llm': { zh: 'LLM 节点', en: 'LLM Node' },
  'orchestration.node.tool': { zh: '工具节点', en: 'Tool Node' },
  'orchestration.node.condition': { zh: '条件节点', en: 'Condition Node' },
  'orchestration.node.end': { zh: '结束', en: 'End' },
  'orchestration.node.parallel': { zh: '并行', en: 'Parallel' },
  'orchestration.node.aggregate': { zh: '聚合', en: 'Aggregate' },
  'orchestration.node.roundRobin': { zh: '轮询模式', en: 'Round Robin' },
  'orchestration.node.debate': { zh: '辩论模式', en: 'Debate' },

  // 模式
  'orchestration.mode.sequential': { zh: '串行（sequential）', en: 'Sequential' },
  'orchestration.mode.graph': { zh: '图（graph）', en: 'Graph' },
  'orchestration.mode.unsupported': {
    zh: 'supervisor / hybrid 模式暂不支持可视化，请在 YAML 中维护。',
    en: 'supervisor / hybrid modes are not yet supported in the canvas; maintain them in YAML.',
  },

  // 属性面板
  'orchestration.prop.title': { zh: '节点属性', en: 'Node Properties' },
  'orchestration.prop.id': { zh: '节点 ID', en: 'Node ID' },
  'orchestration.prop.label': { zh: '显示名称', en: 'Label' },
  'orchestration.prop.skill': { zh: '选择 Skill', en: 'Select Skill' },
  'orchestration.prop.tool': { zh: '工具', en: 'Tool' },
  'orchestration.prop.tools': { zh: '工具列表', en: 'Tools' },
  'orchestration.prop.timeout': { zh: '超时（秒）', en: 'Timeout (s)' },
  'orchestration.prop.output_key': { zh: '输出上下文键', en: 'Output Context Key' },
  'orchestration.prop.description': { zh: '描述', en: 'Description' },
  'orchestration.prop.condition_expr': { zh: '条件表达式', en: 'Condition Expression' },
  'orchestration.prop.false_reason': { zh: '条件不成立说明', en: 'False-branch Reason' },
  'orchestration.prop.multi_agent_mode': { zh: '多智能体模式', en: 'Multi-Agent Mode' },
  'orchestration.prop.round_robin': { zh: '轮询（round_robin）', en: 'Round Robin' },
  'orchestration.prop.debate': { zh: '辩论（debate）', en: 'Debate' },
  'orchestration.prop.unknown_payload': {
    zh: '该节点来自手工 YAML，含无法识别的属性；编辑时保留原值。',
    en: 'This node came from hand-written YAML and carries properties the canvas does not understand; they are preserved on save.',
  },

  // 校验
  'orchestration.validate.blocked': {
    zh: '存在 {count} 个错误，已阻止保存/发布。',
    en: '{count} error(s) block saving/publishing.',
  },
  'orchestration.validate.ok': { zh: '校验通过，可以保存。', en: 'Validation passed — ready to save.' },
  'orchestration.validate.cycle_highlight': { zh: '环已高亮', en: 'Cycle highlighted' },
  'orchestration.validate.publish_denied': {
    zh: '你没有发布权（需要权限码 orchestration:publish）。请先保存草稿。',
    en: 'You do not have publish permission (permission code orchestration:publish). Save as draft instead.',
  },

  // 空态 / 加载
  'orchestration.empty': { zh: '画布为空：从左侧拖入节点开始编排。', en: 'Empty canvas: drag nodes from the palette to start.' },
  'orchestration.load_failed': { zh: '编排加载失败', en: 'Failed to load orchestration' },
  'orchestration.delete_node': { zh: '删除节点', en: 'Delete Node' },
  'orchestration.delete_edge': { zh: '删除连线', en: 'Delete Edge' },
} as const