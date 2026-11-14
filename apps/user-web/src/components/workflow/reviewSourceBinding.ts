type WorkflowNode = {
  id?: string;
  type: string;
  outputAlias?: string;
  businessConfig?: Record<string, any>;
};

type UpstreamRef = { id: string; alias: string };

type ReviewRefKeys = [string, string];

function collectUpstream(nodes: WorkflowNode[], index: number): UpstreamRef[] {
  return nodes.slice(0, index).map(item => ({
    id: String(item.id || ''),
    alias: String(item.outputAlias || item.businessConfig?.outputAlias || '').trim(),
  })).filter(item => item.id && item.alias);
}

/** Explicit mode wins; otherwise infer inline when the criteria is free text. */
function resolveCriteriaMode(config: Record<string, any>, upstream: UpstreamRef[]): string {
  if (config.reviewCriteriaMode) return String(config.reviewCriteriaMode);
  const hasInlineCriteria = Boolean(String(config.reviewCriteria || '').trim());
  const matchesUpstreamAlias = upstream.some(item => item.alias === config.reviewCriteria);
  const inferredInline = !config.reviewCriteriaNodeId && hasInlineCriteria && !matchesUpstreamAlias;
  return inferredInline ? 'inline' : 'upstream';
}

function findUpstreamMatch(
  config: Record<string, any>,
  [idKey, labelKey]: ReviewRefKeys,
  upstream: UpstreamRef[],
): UpstreamRef | undefined {
  const currentId = String(config[idKey] || '');
  return currentId
    ? upstream.find(item => item.id === currentId)
    : upstream.find(item => item.alias === config[labelKey]);
}

export function bindReviewSources(nodes: WorkflowNode[]): string | null {
  for (const [index, node] of nodes.entries()) {
    if (node.type !== 'review_check') continue;
    const config = node.businessConfig || {};
    const upstream = collectUpstream(nodes, index);
    const criteriaMode = resolveCriteriaMode(config, upstream);
    config.reviewCriteriaMode = criteriaMode;
    const refs: ReviewRefKeys[] = criteriaMode === 'inline'
      ? [['reviewSubjectNodeId', 'reviewSubject']]
      : [['reviewSubjectNodeId', 'reviewSubject'], ['reviewCriteriaNodeId', 'reviewCriteria']];
    for (const refKeys of refs) {
      const match = findUpstreamMatch(config, refKeys, upstream);
      if (!match) return node.id || `node_${index + 1}`;
      config[refKeys[0]] = match.id;
      config[refKeys[1]] = match.alias;
    }
    if (criteriaMode === 'inline') {
      if (!String(config.reviewCriteria || '').trim()) return node.id || `node_${index + 1}`;
      config.reviewCriteriaNodeId = '';
    }
  }
  return null;
}
