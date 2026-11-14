/**
 * 039 可视化编排画布 —— 前端序列化 / 校验单测（tasks T028 / T029）。
 *
 * 覆盖点（与 spec FR-007 / FR-009 / FR-012、US2 / US3 对齐）：
 * * 画布 → 引擎文档 → 画布 往返，拓扑（节点/边/模式/条件）零丢失；
 * * 手写 YAML 形状（只给 depends_on、无 edges、无 layout）可在画布打开且信息不丢；
 * * 未知顶层键（data_contract / audit）原样透传；
 * * 环 / 自环阻断且错误文案与引擎 `topo.CycleError` 同格式；孤立节点只警示不阻断；
 * * 条件表达式按引擎受限文法校验（loader.compile_expr 同口径）。
 *
 * 运行：`npm run test:orchestration-canvas`（esbuild 打包后由 node 执行，仓库既有约定）。
 */
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import {
  autoLayout,
  canvasToEngineDocument,
  engineDocumentToCanvas,
  isSupportedConditionExpr,
  negateConditionExpr,
  type CanvasDocument,
  type CanvasEdge,
  type CanvasNode,
  type EngineDocument,
} from '../src/components/orchestration/canvasSchema'
import { findCycle, formatCyclePath, validateCanvas } from '../src/components/orchestration/canvasValidation'

// ------------------------------------------------------------------ helpers

function node(id: string, kind: CanvasNode['kind'], patch: Partial<CanvasNode['data']> = {}): CanvasNode {
  return { id, kind, position: { x: 0, y: 0 }, data: { label: id, ...patch } }
}

function edge(source: string, target: string): CanvasEdge {
  return { id: `e_${source}_${target}`, source, target }
}

function canvas(nodes: CanvasNode[], edges: CanvasEdge[], mode: CanvasDocument['orchestration']['mode'] = 'graph'): CanvasDocument {
  return {
    orchestration: { id: 'demo', version: '1', mode },
    nodes,
    edges,
    layout: Object.fromEntries(nodes.map((item, index) => [item.id, { x: index * 200, y: 0 }])),
  }
}

function codes(doc: CanvasDocument): string[] {
  return validateCanvas(doc).map((issue) => issue.code)
}

function engineNodeIds(doc: EngineDocument): string[] {
  return doc.nodes.map((item) => String(item.id))
}

// ------------------------------------------------------------------ T028-1 往返拓扑零丢失

{
  const source = canvas([node('a', 'start'), node('b', 'llm', { skill: 's1', timeout: 60 })], [edge('a', 'b')])
  const engine = canvasToEngineDocument(source)

  assert.equal(engine.orchestration.mode, 'graph')
  assert.deepEqual(engineNodeIds(engine), ['a', 'b'])
  assert.deepEqual(engine.nodes[1].depends_on, ['a'], 'depends_on 必须由入边派生')
  assert.deepEqual(engine.edges, [{ source: 'a', target: 'b' }])

  const back = engineDocumentToCanvas(engine)
  assert.deepEqual(back.nodes.map((item) => item.id), ['a', 'b'])
  assert.deepEqual(back.nodes.map((item) => item.kind), ['start', 'llm'], 'kind 必须经 x_canvas 还原')
  assert.deepEqual(back.edges.map((item) => [item.source, item.target]), [['a', 'b']])
  assert.equal(back.orchestration.mode, 'graph')
  assert.equal(back.nodes[1].data.skill, 's1')
  assert.equal(back.nodes[1].data.timeout, 60)
  console.log('  ok  T028-1 画布 → 引擎 → 画布 拓扑与节点属性零丢失')
}

// ------------------------------------------------------------------ T028-2 手写 YAML（competitor_deep_dive 形状）

{
  // 形状取自 services/chat-api/app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml：
  // 节点描述性字段写在节点顶层、只有 depends_on 没有 edges、没有 layout。
  const yamlDoc = {
    orchestration: { id: 'competitor_deep_dive', version: '1.0.0', mode: 'graph', max_concurrency: 4, timeout: 900 },
    nodes: [
      {
        id: 'market_intel',
        skill: 'market_intelligence_v1',
        description: '市场情报员',
        timeout: 600,
        tools: ['search_web', 'fetch_news'],
        output_key: 'market_intel_result',
        depends_on: [],
      },
      {
        id: 'financial_analysis',
        skill: 'financial_analysis_v1',
        tools: ['fetch_financials'],
        output_key: 'financial_analysis_result',
        depends_on: [],
        skip_condition: { expr: 'competitor_is_private == true', reason: 'private company has no public financials' },
      },
      {
        id: 'report_synthesis',
        skill: 'report_synthesis_v1',
        output_key: 'research_report',
        depends_on: ['market_intel', 'financial_analysis'],
        skip_condition: { expr: 'completed_children_count < 3', reason: 'insufficient upstream data' },
      },
    ],
    data_contract: { 'market_intel.output_key': 'market_intel_result' },
    audit: { enabled: true, emit_events: ['node_start'] },
  } as unknown as EngineDocument

  const opened = engineDocumentToCanvas(yamlDoc)

  assert.deepEqual(opened.nodes.map((item) => item.id), ['market_intel', 'financial_analysis', 'report_synthesis'])
  assert.deepEqual(
    opened.edges.map((item) => [item.source, item.target]),
    [
      ['market_intel', 'report_synthesis'],
      ['financial_analysis', 'report_synthesis'],
    ],
    '缺 edges 时必须按 depends_on 反推出边，否则画布打开后没有任何连线',
  )
  assert.equal(opened.orchestration.mode, 'graph')
  assert.equal(opened.orchestration.maxConcurrency, 4)
  assert.equal(opened.orchestration.timeout, 900)
  assert.equal(opened.nodes[0].data.skill, 'market_intelligence_v1', '节点顶层的 skill 必须还原')
  assert.deepEqual(opened.nodes[0].data.tools, ['search_web', 'fetch_news'])
  assert.equal(opened.nodes[0].data.outputKey, 'market_intel_result')
  assert.equal(opened.nodes[0].data.timeout, 600)
  assert.equal(opened.nodes[1].data.conditionExpr, 'competitor_is_private == true')
  assert.equal(opened.nodes[1].data.falseBranchReason, 'private company has no public financials')
  assert.equal(opened.nodes[2].data.conditionExpr, 'completed_children_count < 3')
  assert.equal(opened.nodes[2].data.falseBranchReason, 'insufficient upstream data')
  console.log('  ok  T028-2 手写 YAML 打开：节点 / 边 / 模式 / 条件全还原')
}

// ------------------------------------------------------------------ T028-3 未知顶层键透传（FR-009）

{
  const yamlDoc = {
    orchestration: { id: 'keep-raw', version: '1', mode: 'graph' },
    nodes: [{ id: 'a', skill: 's', depends_on: [] }],
    data_contract: { 'a.output_key': 'a_result' },
    audit: { enabled: true },
    failure_propagation: { on_all_children_failed: 'mark_parent_skipped' },
  } as unknown as EngineDocument

  const opened = engineDocumentToCanvas(yamlDoc)
  assert.deepEqual(opened.raw, {
    data_contract: { 'a.output_key': 'a_result' },
    audit: { enabled: true },
    failure_propagation: { on_all_children_failed: 'mark_parent_skipped' },
  })

  const saved = canvasToEngineDocument(opened)
  assert.deepEqual(saved.data_contract, { 'a.output_key': 'a_result' })
  assert.deepEqual(saved.audit, { enabled: true })
  assert.deepEqual(saved.failure_propagation, { on_all_children_failed: 'mark_parent_skipped' })
  console.log('  ok  T028-3 data_contract / audit 等未知顶层键往返不丢')
}

// ------------------------------------------------------------------ T028-4 layout 缺失 / 损坏降级（FR-012）

{
  const noLayout = engineDocumentToCanvas({
    orchestration: { id: 'nolayout', version: '1', mode: 'graph' },
    nodes: [{ id: 'a', depends_on: [] }, { id: 'b', depends_on: ['a'] }],
  } as EngineDocument)
  assert.ok(noLayout.nodes.every((item) => Number.isFinite(item.position.x) && Number.isFinite(item.position.y)))
  assert.notDeepEqual(noLayout.nodes[0].position, noLayout.nodes[1].position, '自动布局应把两层节点分开')

  const broken = engineDocumentToCanvas({
    orchestration: { id: 'broken', version: '1', mode: 'graph' },
    nodes: [{ id: 'a', depends_on: [] }],
    layout: { a: { x: 'oops', y: null } } as unknown as Record<string, { x: number; y: number }>,
  } as EngineDocument)
  assert.ok(Number.isFinite(broken.nodes[0].position.x), '坏 layout 必须降级到自动布局，不抛错')

  const layered = autoLayout(
    [node('a', 'start'), node('b', 'llm'), node('c', 'end')],
    [edge('a', 'b'), edge('b', 'c')],
  )
  assert.equal(layered.a.x, 40)
  assert.equal(layered.b.x, 280)
  assert.equal(layered.c.x, 520)
  console.log('  ok  T028-4 缺 layout 自动布局、坏 layout 降级不抛错')
}

// ------------------------------------------------------------------ T028-5 条件节点二分支：取反表达式必须仍可被引擎文法解析

{
  const source = canvas(
    [
      node('start', 'start'),
      node('check', 'condition', { conditionExpr: 'competitor_is_private == true', falseBranchReason: 'public company' }),
      node('yes', 'llm', { skill: 's_yes' }),
      node('no', 'llm', { skill: 's_no' }),
    ],
    [edge('start', 'check'), edge('check', 'yes'), edge('check', 'no')],
  )
  const engine = canvasToEngineDocument(source)
  const noNode = engine.nodes.find((item) => item.id === 'no')
  const skip = noNode?.skip_condition as { expr: string; reason: string }

  assert.equal(skip.expr, 'competitor_is_private != true', '取反必须用翻转运算符表达，不能生成 !(...)')
  assert.equal(skip.reason, 'public company')
  assert.ok(isSupportedConditionExpr(skip.expr), '生成的表达式必须能被 loader.compile_expr 解析')

  assert.equal(negateConditionExpr('completed_children_count < 3'), 'completed_children_count >= 3')
  assert.equal(negateConditionExpr('x >= 1'), 'x < 1')
  assert.equal(negateConditionExpr('x <= 1'), 'x > 1')
  assert.equal(negateConditionExpr('x != true'), 'x == true')
  console.log('  ok  T028-5 条件二分支的取反表达式可被引擎文法解析')
}

// ------------------------------------------------------------------ T029-1 环 / 自环阻断，文案与引擎同格式

{
  const cycle = canvas(
    [node('a', 'start'), node('b', 'llm'), node('c', 'end')],
    [edge('a', 'b'), edge('b', 'c'), edge('c', 'a')],
  )
  const issues = validateCanvas(cycle)
  const cycleIssue = issues.find((item) => item.code === 'cycle_detected')
  assert.ok(cycleIssue, '环必须阻断保存')
  assert.equal(cycleIssue.severity, 'error')
  assert.match(cycleIssue.message, /^cycle detected: /)
  assert.equal(cycleIssue.message, 'cycle detected: a -> b -> c -> a')
  assert.deepEqual(cycleIssue.nodeIds.sort(), ['a', 'b', 'c'], '环上节点必须全部高亮')
  assert.equal(cycleIssue.edgeIds.length, 3)

  // 与引擎 topo.CycleError 的构造方式一致（`f"cycle detected: {path}"`）。
  assert.equal(formatCyclePath(['a', 'b', 'c', 'a']), 'cycle detected: a -> b -> c -> a')
  assert.deepEqual(findCycle(cycle.nodes, cycle.edges), ['a', 'b', 'c', 'a'])

  const selfLoop = canvas([node('a', 'start')], [edge('a', 'a')])
  const selfIssues = validateCanvas(selfLoop)
  assert.ok(selfIssues.some((item) => item.code === 'self_loop' && item.severity === 'error'))
  console.log('  ok  T029-1 环 / 自环阻断，错误文案与 topo.CycleError 同格式')
}

// ------------------------------------------------------------------ T029-2 孤立节点只警示、空图与重复 ID 阻断

{
  const isolated = canvas([node('a', 'start'), node('b', 'llm')], [])
  const isolatedIssues = validateCanvas(isolated)
  const warn = isolatedIssues.find((item) => item.code === 'isolated_node')
  assert.ok(warn, '孤立节点必须有提示')
  assert.equal(warn.severity, 'warning', '孤立节点在引擎侧合法，画布只警示不阻断')
  assert.deepEqual(warn.nodeIds.sort(), ['a', 'b'])
  assert.equal(isolatedIssues.filter((item) => item.severity === 'error').length, 0)

  assert.deepEqual(codes(canvas([], [])), ['empty_graph'])
  assert.ok(codes(canvas([node('a', 'start'), node('a', 'llm')], [])).includes('duplicate_node_id'))
  assert.ok(codes(canvas([node('a', 'start')], [edge('a', 'ghost')])).includes('dangling_edge'))
  console.log('  ok  T029-2 孤立节点仅警示；空图 / 重复 ID / 悬空边阻断')
}

// ------------------------------------------------------------------ T029-3 条件表达式文法校验（loader.compile_expr 同口径）

{
  assert.ok(isSupportedConditionExpr('competitor_is_private == true'))
  assert.ok(isSupportedConditionExpr('completed_children_count < 3'))
  assert.ok(isSupportedConditionExpr('  state.revenue >= 1000.5  '))
  assert.equal(isSupportedConditionExpr('!(x == 1)'), false, '引擎文法不支持嵌套取反')
  assert.equal(isSupportedConditionExpr('competitor is private'), false, '自然语言不是合法条件')
  assert.equal(isSupportedConditionExpr('x'), false)

  const bad = canvas([node('c', 'condition', { conditionExpr: '!(x == 1)' })], [])
  const badIssues = validateCanvas(bad)
  const invalid = badIssues.find((item) => item.code === 'condition_invalid_expr')
  assert.ok(invalid, '非法条件必须阻断保存')
  assert.equal(invalid.severity, 'error')
  assert.deepEqual(invalid.nodeIds, ['c'])

  const missing = validateCanvas(canvas([node('c', 'condition')], []))
  assert.ok(missing.some((item) => item.code === 'condition_missing_expr' && item.severity === 'warning'))

  const good = validateCanvas(canvas([node('c', 'condition', { conditionExpr: 'x == 1' })], []))
  assert.equal(good.filter((item) => item.code === 'condition_invalid_expr').length, 0)
  console.log('  ok  T029-3 条件表达式按引擎文法校验，非法即阻断')
}

// ------------------------------------------------------------------ 补充：sequential 线性约束

{
  const fork = canvas([node('a', 'start'), node('b', 'llm'), node('c', 'llm')], [edge('a', 'b'), edge('a', 'c')], 'sequential')
  assert.ok(codes(fork).includes('sequential_not_linear'), 'sequential 模式下分叉必须阻断')

  const chain = canvas([node('a', 'start'), node('b', 'llm')], [edge('a', 'b')], 'sequential')
  assert.equal(validateCanvas(chain).filter((item) => item.severity === 'error').length, 0)
  console.log('  ok  补充：sequential 只接受线性链')
}

// ------------------------------------------------------------------ T028-6 044 协议声明必须落在节点顶层

{
  // 010 loader 只从 `raw["mode"]` 读协议；放进 payload 会被 `_PAYLOAD_KEYS` 过滤掉，
  // 画布写的 mode 因此静默失效（本用例锁死这个回归）。
  const source = canvas([node('rr', 'roundRobin', { skill: 's1' }), node('llm', 'llm', { skill: 's2', multiAgentMode: 'debate' })], [])
  const engine = canvasToEngineDocument(source)
  const rr = engine.nodes.find((item) => item.id === 'rr')
  const llm = engine.nodes.find((item) => item.id === 'llm')

  assert.equal(rr?.mode, 'round_robin', 'roundRobin 节点的 mode 必须在节点顶层')
  assert.equal(llm?.mode, 'debate', 'llm 节点显式选择的模式也要落到节点顶层')
  assert.equal((rr?.payload as Record<string, unknown> | undefined)?.mode, undefined, 'payload 里不应再有 mode')

  const back = engineDocumentToCanvas(engine)
  assert.equal(back.nodes[0].data.multiAgentMode, 'round_robin', '顶层 mode 必须能还原为画布模式')
  assert.equal(back.nodes[1].data.multiAgentMode, 'debate')
  console.log('  ok  T028-6 044 模式声明序列化到节点顶层并可往返')
}

// ------------------------------------------------------------------ T028-7 round_robin 候选实例只读保留

{
  const yamlDoc = {
    orchestration: { id: 'rr-demo', version: '1', mode: 'graph' },
    nodes: [
      {
        id: 'task',
        mode: 'round_robin',
        skill: 'writer',
        instances: [{ label: 'fast', model: 'light-1', temperature: 0.2 }, { label: 'deep', model: 'high-1' }],
        depends_on: [],
      },
    ],
  } as unknown as EngineDocument

  const opened = engineDocumentToCanvas(yamlDoc)
  assert.equal(opened.nodes[0].data.multiAgentMode, 'round_robin')
  assert.equal(opened.nodes[0].data.instances?.length, 2, 'instances 打开时不能丢')

  const saved = canvasToEngineDocument(opened)
  assert.equal(saved.nodes[0].mode, 'round_robin')
  assert.deepEqual(saved.nodes[0].payload?.instances, yamlDoc.nodes[0].instances, 'instances 保存时必须原样带出')
  console.log('  ok  T028-7 round_robin 的 instances 往返零丢失')
}

// ------------------------------------------------------------------ T028-8 debate 协议：pro / con 必填且必须指向真实节点

{
  const base = [node('debate', 'debate', { skill: 's' }), node('pro', 'llm', { skill: 'p' }), node('con', 'llm', { skill: 'c' })]
  const edges = [edge('pro', 'debate'), edge('con', 'debate')]

  const missing = validateCanvas(canvas(base, edges))
  const missingIssue = missing.find((item) => item.code === 'debate_missing_roles')
  assert.ok(missingIssue, 'debate 缺 pro/con 必须阻断（与 loader fail-closed 同口径）')
  assert.equal(missingIssue.severity, 'error')

  const okNodes = [node('debate', 'debate', { skill: 's', pro: 'pro', con: 'con' }), base[1], base[2]]
  const okIssues = validateCanvas(canvas(okNodes, edges))
  assert.equal(okIssues.filter((item) => item.code === 'debate_missing_roles').length, 0)
  assert.equal(okIssues.filter((item) => item.code === 'debate_dangling_role').length, 0)

  const danglingNodes = [node('debate', 'debate', { skill: 's', pro: 'pro', con: 'ghost' }), base[1], base[2]]
  assert.ok(codes(canvas(danglingNodes, edges)).includes('debate_dangling_role'), '引用不存在的节点必须阻断')

  const engine = canvasToEngineDocument(canvas(okNodes, edges))
  const debateNode = engine.nodes.find((item) => item.id === 'debate')
  assert.equal(debateNode?.mode, 'debate')
  assert.equal(debateNode?.payload?.pro, 'pro')
  assert.equal(debateNode?.payload?.con, 'con')
  console.log('  ok  T028-8 debate 的 pro / con 校验与序列化')
}

// ------------------------------------------------------------------ T029-4 instances 越权键阻断（044 R-1）

{
  const bad = canvas(
    [node('task', 'roundRobin', { skill: 's', instances: [{ model: 'm1' }, { retry: 3 } as unknown as { model: string }] })],
    [],
  )
  const issues = validateCanvas(bad)
  const invalid = issues.find((item) => item.code === 'round_robin_invalid_instances')
  assert.ok(invalid, '实例里出现 retry 等节点级语义键必须阻断')
  assert.equal(invalid.severity, 'error')

  const fine = canvas([node('task', 'roundRobin', { skill: 's', instances: [{ model: 'm1' }, { label: 'b', temperature: 0.3 }] })], [])
  assert.equal(validateCanvas(fine).filter((item) => item.code === 'round_robin_invalid_instances').length, 0)
  console.log('  ok  T029-4 instances 越权键阻断')
}

// ------------------------------------------------------------------ 与后端 fixture 同步（真实序列化产出）

{
  // 后端 `services/chat-api/tests/orchestration/fixtures/canvas_document.json` 由本序列化器
  // 生成，后端用真实 010 loader 装载并执行它（test_real_serializer_fixture_loads_and_runs）。
  // 这里做漂移守卫：改了序列化就必须同步刷新该 fixture，否则两边各测各的、彼此不再代表现实。
  // 该测试被 esbuild 打包到 node_modules/.tmp 执行，`import.meta.url` 指向产物而非源文件，
  // 因此从 cwd 向上找到仓库根再拼路径。
  let repoRoot = process.cwd()
  for (let i = 0; i < 6 && !existsSync(path.join(repoRoot, 'services', 'chat-api')); i += 1) {
    repoRoot = path.dirname(repoRoot)
  }
  const expected = JSON.parse(
    readFileSync(
      path.join(repoRoot, 'services/chat-api/tests/orchestration/fixtures/canvas_document.json'),
      'utf8',
    ),
  )
  const produced = canvasToEngineDocument({
    orchestration: { id: 'canvas-e2e', version: '1', mode: 'graph' },
    nodes: [
      node('research', 'llm', { label: '研究', skill: 'researcher', outputKey: 'research_result' }),
      node('write', 'llm', { label: '写作', skill: 'writer', outputKey: 'draft' }),
    ],
    edges: [edge('research', 'write')],
    layout: { research: { x: 0, y: 0 }, write: { x: 200, y: 0 } },
  })
  assert.deepEqual(
    // 过一遍 JSON：内存对象里 `undefined` 的键在落盘时会被丢掉，比较前先对齐口径。
    JSON.parse(JSON.stringify(produced)),
    expected,
    '序列化结果与后端 fixture 不一致：请重新生成 services/chat-api/tests/orchestration/fixtures/canvas_document.json',
  )
  console.log('  ok  fixture 与当前序列化结果一致（后端用它跑真实 loader）')
}

console.log('\norchestration-canvas: 全部断言通过')
