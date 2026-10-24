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
  /** 044 多智能体模式（roundRobin / debate 节点）。 */
  multiAgentMode?: MultiAgentMode;
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

/** 序列化单个画布节点的业务属性到引擎 payload（不含 x_canvas 回程信息）。 */
function enginePayload(node: CanvasNode): Record<string, unknown> {
  const { data, kind } = node;
  const payload: Record<string, unknown> = {};
  if (data.skill) payload['skill'] = data.skill;
  if (data.tool) payload['tool'] = data.tool;
  if (data.tools && data.tools.length) payload['tools'] = data.tools;
  if (data.timeout !== undefined) payload['timeout'] = data.timeout;
  if (data.description) payload['description'] = data.description;
  if (data.outputKey) payload['output_key'] = data.outputKey;
  if (kind === 'condition' && data.conditionExpr) {
    // 自然语言面：引擎侧装载时会用 not 包装成 condition（loader 行为，不在此透出极性）。
    payload['condition_expr'] = data.conditionExpr;
  }
  if (kind === 'roundRobin' || kind === 'debate') {
    payload['mode'] = data.multiAgentMode ?? (kind === 'roundRobin' ? 'round_robin' : 'debate');
  }
  return payload;
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
  const byId = new Map(canvas.nodes.map((node) => [node.id, node]));
  const engineNodes: EngineNode[] = canvas.nodes.map((node) => {
    const incoming = canvas.edges.filter((edge) => edge.target === node.id).map((edge) => edge.source);
    const engineNode: EngineNode = {
      id: node.id,
      type: engineTypeForKind(node.kind),
      depends_on: incoming.length ? incoming : undefined,
      payload: {
        ...enginePayload(node),
        x_canvas: { kind: node.kind, label: node.data.label, multiAgentMode: node.data.multiAgentMode },
      },
    };
    if (node.data.conditionExpr) engineNode['skip_condition'] = { expr: node.data.conditionExpr, reason: node.data.falseBranchReason };
    return engineNode;
  });

  const edges = canvas.edges.map((edge) => ({ source: edge.source, target: edge.target }));

  const document: EngineDocument = {
    orchestration: {
      id: canvas.orchestration.id,
      version: canvas.orchestration.version || '1',
      mode: canvas.orchestration.mode,
    },
    nodes: engineNodes,
    edges,
  };
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
        expr: `!(${node.data.conditionExpr})`,
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

/** 单个引擎节点 → 画布节点：x_canvas 投影优先，缺失时按 type 推断 kind、按 id 取标签。 */
function mapEngineNode(node: EngineNode): CanvasNode {
  const payload = (node.payload || {}) as Record<string, unknown>;
  const canvas = payload['x_canvas'] as Partial<CanvasNodeData> & { kind?: CanvasNodeKind } | undefined;
  const kind = canvas?.kind ?? kindForEngineType(String(node.type || 'llm'));
  return {
    id: String(node.id),
    kind,
    position: { x: 0, y: 0 },
    data: {
      label: canvas?.label ?? String(node.id),
      skill: stringField(payload, 'skill'),
      tool: stringField(payload, 'tool'),
      tools: Array.isArray(payload['tools']) ? (payload['tools'] as string[]) : undefined,
      timeout: numberField(payload, 'timeout'),
      description: stringField(payload, 'description'),
      outputKey: stringField(payload, 'output_key'),
      conditionExpr: (node.skip_condition as { expr?: string } | undefined)?.expr ?? (payload['condition_expr'] as string | undefined),
      falseBranchReason: (node.skip_condition as { reason?: string } | undefined)?.reason,
      multiAgentMode: canvas?.multiAgentMode ?? (kind === 'roundRobin' ? 'round_robin' : kind === 'debate' ? 'debate' : undefined),
    },
  };
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
 *   无 x_canvas 的手工 YAML 节点按 type 映射 kind，标签取 id。
 * * 位置可丢（FR-012）：顶层 `layout` 缺失时给默认自动布局。
 * * 未知顶层键（data_contract/audit）与本函数无关，不修改、不删除。
 */
export function engineDocumentToCanvas(document: EngineDocument): CanvasDocument {
  const nodes: CanvasNode[] = (document.nodes || []).map(mapEngineNode);
  const edges: CanvasEdge[] = (document.edges || []).map((edge, index) => mapEngineEdge(edge, index));

  const canvasDoc: CanvasDocument = {
    orchestration: resolveOrchestrationHeader(document.orchestration || {}),
    nodes,
    edges,
    layout: {},
  };
  applyLayout(nodes, edges, document.layout);
  return canvasDoc;
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