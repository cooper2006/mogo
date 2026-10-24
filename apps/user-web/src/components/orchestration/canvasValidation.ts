/**
 * 画布校验（特性 039 FR-003 / FR-006 / 决策 3）。
 *
 * 校验口径与 010 引擎侧保持一致（`graph.GraphError` / `topo.CycleError` / loader 语义），
 * 环与自环**阻断保存**并在画布上高亮；错误信息格式与引擎侧同：
 * ``cycle detected: A -> B -> C -> A``。
 *
 * 首期仅支持 ``sequential`` 与 ``graph``（supervisor/hybrid 在 UI 明示暂不支持）。
 */

import type { CanvasDocument, CanvasEdge, CanvasNode } from './canvasSchema';

export type Severity = 'error' | 'warning';

export interface ValidationIssue {
  severity: Severity;
  /** 引擎/画布通用错误码。 */
  code: string;
  message: string;
  /** 命中节点 id（用于画布高亮）。 */
  nodeIds: string[];
  /** 命中连线 id（用于画布高亮）。 */
  edgeIds: string[];
}

/** 环路径（与 topo.CycleError 同格式）。 */
export function formatCyclePath(cycle: string[]): string {
  return `cycle detected: ${cycle.join(' -> ')}`;
}

/** 用 Kahn 拓扑排序找出一个环（返回构成环的节点序列，无环返回 null）。 */
export function findCycle(nodes: CanvasNode[], edges: CanvasEdge[]): string[] | null {
  const indegree: Record<string, number> = {};
  const children: Record<string, string[]> = {};
  const nodeIds = nodes.map((node) => node.id);
  nodeIds.forEach((id) => {
    indegree[id] = 0;
    children[id] = [];
  });
  edges.forEach((edge) => {
    if (!(edge.source in children) || !(edge.target in children)) return;
    children[edge.source].push(edge.target);
    indegree[edge.target] += 1;
  });

  const queue = nodeIds.filter((id) => indegree[id] === 0);
  const remaining = new Set(nodeIds);
  while (queue.length) {
    const id = queue.shift() as string;
    remaining.delete(id);
    for (const child of children[id]) {
      indegree[child] -= 1;
      if (indegree[child] === 0) queue.push(child);
    }
  }

  if (remaining.size === 0) return null;

  // 剩余节点构成环（含自环）。顺着 children 走出一条闭路。
  const start = remaining.values().next().value as string;
  const path: string[] = [start];
  const seen = new Set([start]);
  let current = start;
  for (;;) {
    const next = children[current]?.find((id) => remaining.has(id));
    if (!next) break;
    if (next === start) {
      path.push(next);
      break;
    }
    if (seen.has(next)) break;
    path.push(next);
    seen.add(next);
    current = next;
  }
  return path;
}

/** 校验画布文档，返回问题清单（error 阻断保存/发布）。 */
export function validateCanvas(canvas: CanvasDocument): ValidationIssue[] {
  const issues: ValidationIssue[] = [];

  if (!canvas.orchestration.id.trim()) {
    issues.push(issue('error', 'orchestration_id_required', '请填写编排 ID', [], []));
  }

  if (canvas.nodes.length === 0) {
    issues.push(issue('error', 'empty_graph', '画布为空，至少需要一个节点', [], []));
    return issues;
  }

  // 重复 ID（FR：重复 ID 即时禁止）
  const seenIds = new Set<string>();
  const duplicateIds = new Set<string>();
  canvas.nodes.forEach((node) => {
    if (seenIds.has(node.id)) duplicateIds.add(node.id);
    seenIds.add(node.id);
  });
  duplicateIds.forEach((id) => {
    issues.push(issue('error', 'duplicate_node_id', `节点 ID 重复：${id}`, [id], []));
  });

  // 连线端点必须存在
  const validIds = new Set(canvas.nodes.map((node) => node.id));
  canvas.edges.forEach((edge) => {
    if (!validIds.has(edge.source) || !validIds.has(edge.target)) {
      issues.push(
        issue('error', 'dangling_edge', '连线的起点或终点节点不存在', [], [edge.id]),
      );
    }
  });

  // 自环（graph.GraphError: self-loop not allowed）
  canvas.edges.forEach((edge) => {
    if (edge.source === edge.target) {
      issues.push(
        issue('error', 'self_loop', '不允许自环（self-loop not allowed）', [edge.source], [edge.id]),
      );
    }
  });

  // 环（topo.CycleError，格式与引擎一致）
  const cycle = findCycle(canvas.nodes, canvas.edges);
  if (cycle && cycle.length) {
    const cycleIds = new Set(cycle);
    const edgeIds = canvas.edges
      .filter((edge) => cycleIds.has(edge.source) && cycleIds.has(edge.target))
      .map((edge) => edge.id);
    issues.push(
      issue('error', 'cycle_detected', formatCyclePath(cycle), [...cycleIds], edgeIds),
    );
  }

  // 模式约束（决策 3：首期 sequential + graph）
  if (canvas.orchestration.mode === 'sequential' && canvas.nodes.length > 1) {
    // sequential 需要一条线性链：每个节点至多一个入边/出边，除头尾外。
    const indegree: Record<string, number> = {};
    const outdegree: Record<string, number> = {};
    canvas.nodes.forEach((node) => {
      indegree[node.id] = 0;
      outdegree[node.id] = 0;
    });
    canvas.edges.forEach((edge) => {
      if (edge.source in indegree) outdegree[edge.source] += 1;
      if (edge.target in indegree) indegree[edge.target] += 1;
    });
    const broken = canvas.nodes.filter(
      (node) => (indegree[node.id] || 0) > 1 || (outdegree[node.id] || 0) > 1,
    );
    if (broken.length) {
      issues.push(
        issue(
          'error',
          'sequential_not_linear',
          'sequential 模式要求线性链：每个节点至多一个入边与一个出边',
          broken.map((node) => node.id),
          [],
        ),
      );
    }
  }

  // 孤立节点（无入边无出边，且画布非单节点）—— 不阻断，但提示（FR-003 边界）
  const hasEdge = (id: string) =>
    canvas.edges.some((edge) => edge.source === id || edge.target === id);
  const isolated = canvas.nodes
    .filter((node) => !hasEdge(node.id))
    .map((node) => node.id);
  if (isolated.length && canvas.nodes.length > 1) {
    issues.push(
      issue('warning', 'isolated_node', '以下节点没有连线，可能不会被引擎执行', isolated, []),
    );
  }

  // 条件节点必须有表达式
  canvas.nodes.forEach((node) => {
    if (node.kind === 'condition' && !node.data.conditionExpr) {
      issues.push(issue('warning', 'condition_missing_expr', '条件节点未填写条件表达式', [node.id], []));
    }
  });

  return issues;
}

function issue(
  severity: Severity,
  code: string,
  message: string,
  nodeIds: string[],
  edgeIds: string[],
): ValidationIssue {
  return { severity, code, message, nodeIds, edgeIds };
}