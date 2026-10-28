/**
 * 可视化编排画布 —— 唯一转换层（特性 039 决策 4）。
 *
 * 定位：画布 JSON ↔ 010 引擎权威文档（YAML/JSON）的双向互转。**不引入第三种定义格式**。
 * * 权威 = 010 引擎文档（`orchestration` 头 + `nodes`(带 `depends_on`) + `edges`），
 *   保存到 `dag_definitions.document` 后可由 `load_orchestration_document` 原样装载、
 *   被 010 引擎真实执行（FR-002 / FR-004）。
 * * 投影 = `layout`（`{nodeId: {x,y}}`），可丢失（FR-012）。
 * * 画布专属信息（节点 kind、标签、044 多智能体模式等）收在节点 `payload.x_canvas` 下，
 *   引擎对未知 payload 键是透传的，因此往返拓扑零丢失、未知字段只读保留（FR-007/FR-009）。
 *
 * 引擎节点 `type` 取 010 既有集合的子集：
 * `start / llm / tool / condition / end / parallel / aggregate`。
 * 044 的多智能体模式节点（round_robin / debate）在画布上是独立 kind，
 * 序列化后落在 `payload.mode`（引擎侧尚未实现执行逻辑，本特性只做画布 UI + 序列化）。
 */

export type CanvasNodeKind =
  | 'start'
  | 'llm'
  | 'tool'
  | 'condition'
  | 'end'
  | 'parallel'
  | 'aggregate'
  | 'roundRobin'
  | 'debate';

/** 首期画布明示支持的模式（FR-006：supervisor/hybrid 暂不支持，UI 明示）。 */
export type SupportedMode = 'sequential' | 'graph';

/** 044 多智能体模式（画布节点，引擎逻辑不在本特性实现范围）。 */
export type MultiAgentMode = 'round_robin' | 'debate';

/**
 * round_robin 的候选实例声明（044 `instances:`）。
 *
 * 画布首期不提供实例编辑 UI，但必须**原样往返**：手写 YAML 的 instances 在画布打开后
 * 不能丢，否则保存一次就把多候选配置抹成单候选（FR-009 未知字段只读保留）。
 */
export interface CanvasInstance {
  label?: string;
  model?: string;
  temperature?: number;
  prompt?: string;
}

/** 画布节点上的位置（投影元数据）。 */
export interface CanvasPosition {
  x: number;
  y: number;
}

/** 画布节点的业务数据（除 id/kind/position 外的可编辑属性）。 */
export interface CanvasNodeData {
  label: string;
  /** LLM / roundRobin / debate 节点选中的 skill id（复用 api/skills.ts）。 */
  skill?: string;
  /** tool / llm 节点可选的工具 id 列表（复用 api/tools.ts）。 */
  tools?: string[];
  /** 工具节点的主工具 id（属性面板单选）。 */
  tool?: string;
  /** 条件节点的表达式（自然语言面，如 `competitor_is_private == true`）。 */
  conditionExpr?: string;
  /** 条件不成立分支的说明（对应引擎 skip_condition.reason）。 */
  falseBranchReason?: string;
  /** 044 多智能体模式（roundRobin / debate 节点，或 llm 节点显式声明）。 */
  multiAgentMode?: MultiAgentMode;
  /** round_robin 候选实例（首期只做往返保留，无编辑 UI）。 */
  instances?: CanvasInstance[];
  /** debate：正方 / 反方 / 裁决节点 id（引用本编排内的节点）。 */
  pro?: string;
  con?: string;
  arbiter?: string;
  /** 节点级超时（秒）。 */
  timeout?: number;
  description?: string;
  /** 输出到后续节点的上下文键。 */
  outputKey?: string;
}

/** 画布节点（投影侧表示）。 */
export interface CanvasNode {
  id: string;
  kind: CanvasNodeKind;
  position: CanvasPosition;
  data: CanvasNodeData;
}

/** 画布连线（source -> target）。 */
export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
}

/** 画布文档：完整可往返的投影表示。 */
export interface CanvasDocument {
  orchestration: {
    id: string;
    version: string;
    mode: SupportedMode;
    maxConcurrency?: number;
    timeout?: number;
    retry?: { maxAttempts: number; backoff: 'linear' | 'exponential'; baseSeconds: number };
  };
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  /** 投影元数据（可丢失）。 */
  layout: Record<string, CanvasPosition>;
  /**
   * 画布不认识的顶层键（如 `data_contract` / `audit` / `failure_propagation`）原样保留，
   * 保存时透传回引擎文档（FR-009：未知字段只读保留，不透写丢失）。
   */
  raw?: Record<string, unknown>;
}

/** 010 引擎权威文档节点。 */
export interface EngineNode {
  id: string;
  type: string;
  depends_on?: string[];
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

/** 010 引擎权威文档（可被 load_orchestration_document 装载）。 */
export interface EngineDocument {
  orchestration: {
    id: string;
    version: string;
    mode: string;
    max_concurrency?: number;
    timeout?: number;
    retry?: Record<string, unknown>;
  };
  nodes: EngineNode[];
  edges?: Array<{ source: string; target: string }>;
  layout?: Record<string, CanvasPosition>;
  data_contract?: unknown;
  audit?: unknown;
}

/** 画布节点 kind → 引擎节点 type（010 既有集合的子集）。 */
export function engineTypeForKind(kind: CanvasNodeKind): string {
  switch (kind) {
    case 'roundRobin':
    case 'debate':
      return 'llm';
    default:
      return kind;
  }
}

/** 引擎节点 type → 画布 kind（未知 type 归为 llm）。 */
export function kindForEngineType(type: string): CanvasNodeKind {
  if (type === 'start' || type === 'tool' || type === 'condition' || type === 'end' || type === 'parallel' || type === 'aggregate') {
    return type;
  }
  return 'llm';
}

/** 画布节点默认标签（中英双语文案 key 回退中文由 i18n 处理；这里给默认中文）。 */
export function defaultLabel(kind: CanvasNodeKind): string {
  const labels: Record<CanvasNodeKind, string> = {
    start: '开始',
    llm: 'LLM 节点',
    tool: '工具节点',
    condition: '条件节点',
    end: '结束',
    parallel: '并行',
    aggregate: '聚合',
    roundRobin: '轮询模式',
    debate: '辩论模式',
  };
  return labels[kind];
}

/** 生成不重复的画布节点 id。 */
export function generateNodeId(kind: CanvasNodeKind, existing: Set<string>): string {
  const prefix = kind.toLowerCase().replace(/[^a-z0-9]/g, '');
  let candidate = `${prefix}_1`;
  let index = 1;
  while (existing.has(candidate)) {
    index += 1;
    candidate = `${prefix}_${index}`;
  }
  return candidate;
}

/** 新建画布节点。 */
export function createCanvasNode(kind: CanvasNodeKind, id: string, position: CanvasPosition): CanvasNode {
  const data: CanvasNodeData = { label: defaultLabel(kind) };
  if (kind === 'roundRobin') data.multiAgentMode = 'round_robin';
  if (kind === 'debate') data.multiAgentMode = 'debate';
  return { id, kind, position, data };
}

/** 画布节点声明了哪个多智能体模式（kind 优先，其次 llm 节点上的显式选择）。 */
export function declaredMultiAgentMode(node: CanvasNode): MultiAgentMode | undefined {
  if (node.kind === 'roundRobin') return 'round_robin';
  if (node.kind === 'debate') return 'debate';
  return node.data.multiAgentMode;
}

/**
 * 044 协议参数（instances / pro / con / arbiter）。
 *
 * `mode` 本身不在这里——它必须落在**节点顶层**（loader 只从 `raw["mode"]` 读），
 * 放进 payload 会被 `_PAYLOAD_KEYS` 过滤掉，画布声明因此静默失效。
 */
function protocolPayload(node: CanvasNode): Record<string, unknown> {
  const mode = declaredMultiAgentMode(node);
  const payload: Record<string, unknown> = {};
  if (mode === 'round_robin' && node.data.instances?.length) payload['instances'] = node.data.instances;
  if (mode !== 'debate') return payload;
  if (node.data.pro) payload['pro'] = node.data.pro;
  if (node.data.con) payload['con'] = node.data.con;
  if (node.data.arbiter) payload['arbiter'] = node.data.arbiter;
  return payload;
}

/** 序列化单个画布节点的业务属性到引擎 payload（不含 x_canvas 回程信息）。 */
function enginePayload(node: CanvasNode): Record<string, unknown> {
  const { data } = node;
  const payload: Record<string, unknown> = {};
  if (data.skill) payload['skill'] = data.skill;
  if (data.tool) payload['tool'] = data.tool;
  if (data.tools && data.tools.length) payload['tools'] = data.tools;
  if (data.timeout !== undefined) payload['timeout'] = data.timeout;
  if (data.description) payload['description'] = data.description;
  if (data.outputKey) payload['output_key'] = data.outputKey;
  if (node.kind === 'condition' && data.conditionExpr) {
    // 自然语言面：引擎侧装载时会用 not 包装成 condition（loader 行为，不在此透出极性）。
    payload['condition_expr'] = data.conditionExpr;
  }
  return { ...payload, ...protocolPayload(node) };
}

/** 引擎条件文法（与 010 `loader._EXPR_PATTERN` 同口径：`<var> <op> <literal>`）。 */
export const CONDITION_EXPR_PATTERN = /^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$/;

/** 条件表达式能否被引擎 loader 解析（`compile_expr` 只接受受限文法）。 */
export function isSupportedConditionExpr(expr: string): boolean {
  return CONDITION_EXPR_PATTERN.test(String(expr || ''));
}

const NEGATED_OPERATOR: Record<string, string> = {
  '==': '!=',
  '!=': '==',
  '>=': '<',
  '<=': '>',
  '>': '<=',
  '<': '>=',
};

/**
 * 取反条件表达式。
 *
 * 引擎文法不支持 `!(...)` 这类嵌套，因此取反只能靠**翻转比较运算符**表达
 * （`x == true` → `x != true`）。文法外表达式保留 `!(...)` 原样，交由校验与后端
 * loader 明确报错，不静默生成非法文档。
 */
export function negateConditionExpr(expr: string): string {
  const matched = CONDITION_EXPR_PATTERN.exec(String(expr || ''));
  if (!matched) return `!(${expr})`;
  return `${matched[1]} ${NEGATED_OPERATOR[matched[2]]} ${matched[3]}`;
}

/**
 * 画布 → 引擎权威文档。
 *
 * 规则（FR-002 / FR-003 / FR-007）：
 * * 每个节点保留画布 kind/标签等专属信息到 `payload.x_canvas`，保证往返零丢失；
 * * `depends_on` = 所有入边 source（010 引擎 edges 可派生，但显式给出更稳）；
 * * 条件节点：第一个出边是"成立分支"，其余出边目标节点补 `skip_condition`（expr 取反 + 说明）。
 */
export function canvasToEngineDocument(canvas: CanvasDocument): EngineDocument {
  const engineNodes: EngineNode[] = canvas.nodes.map((node) => {
    const incoming = canvas.edges.filter((edge) => edge.target === node.id).map((edge) => edge.source);
    const engineNode: EngineNode = {
      id: node.id,
      type: engineTypeForKind(node.kind),
      depends_on: incoming.length ? incoming : undefined,
      payload: {
        ...enginePayload(node),
        x_canvas: { kind: node.kind, label: node.data.label, multiAgentMode: declaredMultiAgentMode(node) },
      },
    };
    // 044：协议声明必须落在**节点顶层**——010 loader 只从 `raw["mode"]` 读，
    // 放进 payload 会被 `_PAYLOAD_KEYS` 过滤掉（画布声明因此静默失效）。
    const mode = declaredMultiAgentMode(node);
    if (mode) engineNode['mode'] = mode;
    if (node.data.conditionExpr) engineNode['skip_condition'] = { expr: node.data.conditionExpr, reason: node.data.falseBranchReason };
    return engineNode;
  });

  const edges = canvas.edges.map((edge) => ({ source: edge.source, target: edge.target }));

  const document = {
    // FR-009：画布不认识的顶层键（data_contract / audit / failure_propagation…）原样透传，
    // 放在最前面使下面的契约字段永远覆盖它们。
    ...(canvas.raw || {}),
    orchestration: {
      id: canvas.orchestration.id,
      version: canvas.orchestration.version || '1',
      mode: canvas.orchestration.mode,
    },
    nodes: engineNodes,
    edges,
  } as EngineDocument;
  if (canvas.orchestration.maxConcurrency !== undefined) document.orchestration['max_concurrency'] = canvas.orchestration.maxConcurrency;
  if (canvas.orchestration.timeout !== undefined) document.orchestration['timeout'] = canvas.orchestration.timeout;
  if (canvas.orchestration.retry) document.orchestration['retry'] = canvas.orchestration.retry;
  if (Object.keys(canvas.layout || {}).length) document['layout'] = canvas.layout;

  // 条件节点的"取反分支"：给非首条出边的目标补 skip_condition（与 010 loader 的 not 包装同语义）。
  for (const node of canvas.nodes) {
    if (node.kind !== 'condition' || !node.data.conditionExpr) continue;
    const outgoing = canvas.edges.filter((edge) => edge.source === node.id);
    for (const edge of outgoing.slice(1)) {
      const target = engineNodes.find((item) => item.id === edge.target);
      if (!target) continue;
      target['skip_condition'] = {
        // 引擎文法不接受 `!(...)`，取反用翻转运算符表达（语义等价，可被 compile_expr 解析）。
        expr: negateConditionExpr(node.data.conditionExpr),
        reason: node.data.falseBranchReason || 'condition not satisfied',
      };
    }
  }

  return document;
}

type EngineHeader = EngineDocument['orchestration'];

/** 从 payload 中安全取字符串字段（非字符串或缺失返回 undefined）。 */
function stringField(payload: Record<string, unknown>, key: string): string | undefined {
  return typeof payload[key] === 'string' ? (payload[key] as string) : undefined;
}

/** 从 payload 中安全取数字字段（非数字或缺失返回 undefined）。 */
function numberField(payload: Record<string, unknown>, key: string): number | undefined {
  return typeof payload[key] === 'number' ? (payload[key] as number) : undefined;
}

/** 取默认多智能体模式（仅 roundRobin / debate 节点有值）。 */
function multiAgentModeFor(kind: CanvasNodeKind): MultiAgentMode | undefined {
  if (kind === 'roundRobin') return 'round_robin';
  if (kind === 'debate') return 'debate';
  return undefined;
}

/** 引擎节点顶层 `mode`（044 协议声明）→ 画布多智能体模式。 */
function declaredModeFromEngine(node: EngineNode): MultiAgentMode | undefined {
  const mode = node['mode'];
  return mode === 'round_robin' || mode === 'debate' ? mode : undefined;
}

/**
 * 引擎节点 → 画布节点业务数据。
 *
 * 手写 YAML 把描述性字段写在节点顶层（loader 才把它们收进 payload），
 * 因此这里 payload 优先、节点顶层兜底，保证"手工 YAML 打开不丢信息"（US2）。
 */
function nodeDataFrom(
  payload: Record<string, unknown>,
  node: EngineNode,
  kind: CanvasNodeKind,
  canvas: (Partial<CanvasNodeData> & { kind?: CanvasNodeKind }) | undefined,
): CanvasNodeData {
  const pickString = (key: string) => stringField(payload, key) ?? stringField(node, key);
  const pickNumber = (key: string) => numberField(payload, key) ?? numberField(node, key);
  const rawTools = Array.isArray(payload['tools']) ? payload['tools'] : node['tools'];
  const rawInstances = Array.isArray(payload['instances']) ? payload['instances'] : node['instances'];
  const skip = node.skip_condition as { expr?: string; reason?: string } | undefined;
  return {
    label: canvas?.label ?? String(node.id),
    skill: pickString('skill'),
    tool: pickString('tool'),
    tools: Array.isArray(rawTools) ? (rawTools as string[]) : undefined,
    timeout: pickNumber('timeout'),
    description: pickString('description'),
    outputKey: pickString('output_key'),
    conditionExpr: skip?.expr ?? (payload['condition_expr'] as string | undefined),
    falseBranchReason: skip?.reason,
    multiAgentMode: canvas?.multiAgentMode ?? declaredModeFromEngine(node) ?? multiAgentModeFor(kind),
    instances: Array.isArray(rawInstances) ? (rawInstances as CanvasInstance[]) : undefined,
    pro: pickString('pro'),
    con: pickString('con'),
    arbiter: pickString('arbiter'),
  };
}

/** 单个引擎节点 → 画布节点：x_canvas 投影优先，缺失时按 type 推断 kind、按 id 取标签。 */
function mapEngineNode(node: EngineNode): CanvasNode {
  const payload = (node.payload || {}) as Record<string, unknown>;
  const canvas = payload['x_canvas'] as Partial<CanvasNodeData> & { kind?: CanvasNodeKind } | undefined;
  const kind = canvas?.kind ?? kindForEngineType(String(node.type || 'llm'));
  return {
    id: String(node.id),
    kind,
    position: { x: 0, y: 0 },
    data: nodeDataFrom(payload, node, kind, canvas),
  };
}

/**
 * 手写 YAML 通常只给 `depends_on` 不给 `edges`（010 loader 两者都接受）。
 * 画布需要显式的边才能渲染，因此缺失 `edges` 时按 `depends_on` 反推（source = 依赖方，target = 当前节点）。
 */
export function deriveEdgesFromDependsOn(nodes: EngineNode[]): Array<{ source: string; target: string }> {
  const edges: Array<{ source: string; target: string }> = [];
  const seen = new Set<string>();
  nodes.forEach((node) => {
    const dependsOn = Array.isArray(node.depends_on) ? node.depends_on : [];
    dependsOn.forEach((dep) => {
      const key = `${String(dep)}->${String(node.id)}`;
      if (seen.has(key)) return;
      seen.add(key);
      edges.push({ source: String(dep), target: String(node.id) });
    });
  });
  return edges;
}

/** 单个引擎边 → 画布边（id 带下标避免同源同宿点重复）。 */
function mapEngineEdge(edge: { source: string; target: string }, index: number): CanvasEdge {
  return {
    id: `e_${edge.source}_${edge.target}_${index}`,
    source: String(edge.source),
    target: String(edge.target),
  };
}

/** 解析 orchestration 头部：mode 仅识别 sequential，其余归为 graph；可选字段按需附加。 */
function resolveOrchestrationHeader(header: EngineHeader): CanvasDocument['orchestration'] {
  const result: CanvasDocument['orchestration'] = {
    id: String(header.id || ''),
    version: String(header.version || '1'),
    mode: (header.mode === 'sequential' ? 'sequential' : 'graph') as SupportedMode,
  };
  if (typeof header.max_concurrency === 'number') result.maxConcurrency = header.max_concurrency;
  if (typeof header.timeout === 'number') result.timeout = header.timeout;
  if (header.retry && typeof header.retry === 'object') result.retry = header.retry as CanvasDocument['orchestration']['retry'];
  return result;
}

/** 恢复节点位置：显式 layout 优先，否则按入度做分层自动布局（位置可丢失）。 */
function applyLayout(nodes: CanvasNode[], edges: CanvasEdge[], layout: EngineDocument['layout']): void {
  const positions = (layout || {}) as Record<string, CanvasPosition>;
  const layered = autoLayout(nodes, edges);
  nodes.forEach((node) => {
    const explicit = positions[node.id];
    node.position = explicit && typeof explicit.x === 'number' ? { x: explicit.x, y: explicit.y } : layered[node.id] ?? { x: 0, y: 0 };
  });
}

/**
 * 引擎权威文档 → 画布。
 *
 * * 双向不丢信息（FR-007）：画布 kind/标签从 `payload.x_canvas` 恢复；
 *   无 x_canvas 的手工 YAML 节点按 type 映射 kind，描述性字段（skill/tools/
 *   timeout/description/output_key）payload 优先、节点顶层兜底。
 * * 缺 `edges` 时按 `depends_on` 反推边（手写 YAML 常态）。
 * * 位置可丢（FR-012）：顶层 `layout` 缺失或损坏时给默认自动布局。
 * * 未知顶层键（data_contract/audit 等）收进 `raw`，保存时原样透传（FR-009）。
 */
export function engineDocumentToCanvas(document: EngineDocument): CanvasDocument {
  const engineNodes = document.nodes || [];
  const nodes: CanvasNode[] = engineNodes.map(mapEngineNode);
  const rawEdges =
    Array.isArray(document.edges) && document.edges.length
      ? document.edges
      : deriveEdgesFromDependsOn(engineNodes);
  const edges: CanvasEdge[] = rawEdges.map((edge, index) => mapEngineEdge(edge, index));

  const canvasDoc: CanvasDocument = {
    orchestration: resolveOrchestrationHeader(document.orchestration || {}),
    nodes,
    edges,
    layout: {},
  };
  applyLayout(nodes, edges, document.layout);
  const raw = unknownTopLevelKeys(document);
  if (Object.keys(raw).length) canvasDoc.raw = raw;
  return canvasDoc;
}

/** 画布不认识的顶层键（FR-009 原样保留）：除引擎契约字段外一律透传。 */
const KNOWN_TOP_LEVEL_KEYS = new Set(['orchestration', 'nodes', 'edges', 'layout']);

function unknownTopLevelKeys(document: EngineDocument): Record<string, unknown> {
  const raw: Record<string, unknown> = {};
  Object.entries(document as unknown as Record<string, unknown>).forEach(([key, value]) => {
    if (KNOWN_TOP_LEVEL_KEYS.has(key)) return;
    raw[key] = value;
  });
  return raw;
}

/** 极简分层自动布局（layered by longest-path depth）。投影元数据，非权威。 */
export function autoLayout(nodes: CanvasNode[], edges: CanvasEdge[]): Record<string, CanvasPosition> {
  const depth: Record<string, number> = {};
  const indegree: Record<string, number> = {};
  const children: Record<string, string[]> = {};
  nodes.forEach((node) => {
    depth[node.id] = 0;
    indegree[node.id] = 0;
    children[node.id] = [];
  });
  edges.forEach((edge) => {
    if (!(edge.source in children)) return;
    children[edge.source].push(edge.target);
    indegree[edge.target] = (indegree[edge.target] || 0) + 1;
  });

  const queue = nodes.filter((node) => (indegree[node.id] || 0) === 0).map((node) => node.id);
  while (queue.length) {
    const id = queue.shift() as string;
    for (const child of children[id]) {
      depth[child] = Math.max(depth[child] || 0, (depth[id] || 0) + 1);
      indegree[child] = (indegree[child] || 0) - 1;
      if (indegree[child] === 0) queue.push(child);
    }
  }

  const byDepth: Record<string, string[]> = {};
  nodes.forEach((node) => {
    const d = String(depth[node.id] || 0);
    (byDepth[d] = byDepth[d] || []).push(node.id);
  });

  const result: Record<string, CanvasPosition> = {};
  Object.entries(byDepth).forEach(([depthKey, ids]) => {
    const level = Number(depthKey);
    ids.forEach((id, index) => {
      result[id] = { x: level * 240 + 40, y: index * 120 + 60 };
    });
  });
  return result;
}