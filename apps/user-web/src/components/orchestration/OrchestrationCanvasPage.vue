<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { VueFlow, useVueFlow, type Node, type Edge, type Connection, MarkerType } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { NButton, NSelect, NInput, NTag, NAlert, NSpin, NDivider } from 'naive-ui'
import { t } from '../../composables/i18n'
import {
  canvasToEngineDocument,
  engineDocumentToCanvas,
  createCanvasNode,
  generateNodeId,
  type CanvasNode,
  type CanvasNodeKind,
  type SupportedMode,
} from './canvasSchema'
import { validateCanvas, findCycle } from './canvasValidation'
import NodePropertyPanel from './NodePropertyPanel.vue'
import { fetchSkills } from '../../api/skills'
import { fetchTools } from '../../api/tools'
import {
  listOrchestrations,
  fetchOrchestration,
  saveOrchestrationDraft,
  publishOrchestration,
  errorMessage,
  type OrchestrationOverview,
} from '../../api/orchestration'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

/**
 * 可视化编排画布（特性 039 FR-001/FR-003/FR-005/FR-006/FR-010）。
 *
 * - 节点-连线图编辑工作流：拖拽节点、连线、属性面板编辑、校验后保存/发布。
 * - 画布为投影、文档为权威：保存时经 canvasSchema 唯一转换层序列化为 010 引擎文档。
 * - 首期支持 sequential / graph；supervisor / hybrid UI 明示暂不支持。
 * - 044 联动：画布节点支持 round_robin / debate 模式（本特性只做 UI + 序列化）。
 */

const emit = defineEmits<{ (e: 'back'): void }>()

const props = defineProps<{
  userId?: string
  tenantId?: string
}>()

// ------------------------------------------------------------------ state
// Narrow structural types instead of vue-flow's deeply generic `Node`/`Edge`
// (see CanvasFlowNode below): tsc otherwise raises TS2589 on every `.map()`.
const nodes = ref<CanvasFlowNode[]>([])
const edges = ref<CanvasFlowEdge[]>([])
const selectedNodeId = ref<string | null>(null)
/** 画布不认识的顶层键（data_contract / audit 等），保存时原样透传（FR-009）。 */
const rawDocument = ref<Record<string, unknown> | undefined>(undefined)
const issues = ref<ReturnType<typeof validateCanvas>>([])
const busy = ref(false)
const loading = ref(true)
const pageError = ref('')
const notice = ref('')
const saving = ref(false)
const published = ref(false)
const mode = ref<SupportedMode>('graph')
const orchestrationId = ref('customer_research')
const orchestrations = ref<OrchestrationOverview[]>([])
const releaseNotes = ref('')
const skillOptions = ref<Array<{ label: string; value: string }>>([])
const toolOptions = ref<Array<{ label: string; value: string }>>([])
const previewState = ref<Record<string, 'running' | 'done' | 'error'>>({})
const previewing = ref(false)
const paletteOpen = ref(true)

const { project } = useVueFlow()

// ------------------------------------------------------------------ helpers
function toVueNode(canvas: CanvasNode): Node {
  return {
    id: canvas.id,
    type: 'canvas',
    position: { x: canvas.position.x, y: canvas.position.y },
    data: { kind: canvas.kind, canvas },
  }
}

/**
 * Minimal structural view of a vue-flow node.
 *
 * `@vue-flow/core`'s `Node` is a deeply generic union; referencing it in a
 * `.map()` callback makes tsc blow up with TS2589 ("Type instantiation is
 * excessively deep"). Only these three fields are ever read, so the canvas keeps
 * its own narrow shape and casts at the boundary.
 */
type CanvasFlowNode = { id: string; position: { x: number; y: number }; data?: Record<string, unknown> }
type CanvasFlowEdge = { id: string; source: string; target: string }

function fromVueNode(node: CanvasFlowNode): CanvasNode {
  const canvas = (node.data as { canvas?: CanvasNode } | undefined)?.canvas
  return canvas ?? { id: node.id, kind: 'llm', position: node.position, data: { label: node.id } }
}

function toVueEdge(source: string, target: string, index: number): Edge {
  return {
    id: `e_${source}_${target}_${index}`,
    source,
    target,
    markerEnd: MarkerType.ArrowClosed,
    animated: true,
  }
}

function toCanvasDocument(): import('./canvasSchema').CanvasDocument {
  const canvasNodes = (nodes.value as unknown as CanvasFlowNode[]).map(fromVueNode)
  const canvasEdges = (edges.value as unknown as CanvasFlowEdge[]).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
  }))
  return {
    orchestration: {
      id: orchestrationId.value.trim() || 'untitled',
      version: '1',
      mode: mode.value,
    },
    nodes: canvasNodes,
    edges: canvasEdges,
    layout: Object.fromEntries(canvasNodes.map((node) => [node.id, node.position])),
    raw: rawDocument.value,
  }
}

function refreshIssues() {
  issues.value = validateCanvas(toCanvasDocument())
}

const errors = computed(() => issues.value.filter((issue) => issue.severity === 'error'))
const warnings = computed(() => issues.value.filter((issue) => issue.severity === 'warning'))

const selectedNode = computed(() => {
  const flowNodes = nodes.value as unknown as CanvasFlowNode[]
  const found = flowNodes.find((node) => node.id === selectedNodeId.value)
  return found ? fromVueNode(found) : null
})

// ------------------------------------------------------------------ palette
const palette: Array<{ kind: CanvasNodeKind; label: string }> = [
  { kind: 'start', label: t('orchestration.node.start') },
  { kind: 'llm', label: t('orchestration.node.llm') },
  { kind: 'tool', label: t('orchestration.node.tool') },
  { kind: 'condition', label: t('orchestration.node.condition') },
  { kind: 'end', label: t('orchestration.node.end') },
  { kind: 'parallel', label: t('orchestration.node.parallel') },
  { kind: 'aggregate', label: t('orchestration.node.aggregate') },
  { kind: 'roundRobin', label: t('orchestration.node.roundRobin') },
  { kind: 'debate', label: t('orchestration.node.debate') },
]

function addNode(kind: CanvasNodeKind, position?: { x: number; y: number }) {
  const id = generateNodeId(kind, new Set(nodes.value.map((node) => node.id)))
  const canvas = createCanvasNode(kind, id, position ?? { x: 0, y: 0 })
  // 直接写 v-model 源（nodes ref），vue-flow 内部 watcher 会同步进 store 渲染；
  // 若改用 useVueFlow().addNodes()，store→ref 的回写在 vue-flow v1 走的是异步
  // watcher（useWatchProps），紧随其后的 refreshIssues() 会读到空数组，
  // 报出 empty_graph（"画布为空"）假错误且不会自愈。
  nodes.value.push(toVueNode(canvas))
  selectedNodeId.value = id
  refreshIssues()
}

function onDrop(event: DragEvent) {
  const kind = event.dataTransfer?.getData('orchestration/kind') as CanvasNodeKind | ''
  if (!kind) return
  const position = project({ x: event.offsetX, y: event.offsetY })
  addNode(kind, position)
}

function onDragStart(event: DragEvent, kind: CanvasNodeKind) {
  event.dataTransfer?.setData('orchestration/kind', kind)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

// ------------------------------------------------------------------ interactions
function onConnect(connection: Connection) {
  if (!connection.source || !connection.target) return
  edges.value.push(toVueEdge(connection.source, connection.target, edges.value.length))
  refreshIssues()
}

function onNodeClick(event: { node: Node }) {
  selectedNodeId.value = event.node.id
}

function onNodeDragStop() {
  refreshIssues()
}

function onNodeDelete(event: { nodes: Node[] }) {
  const ids = new Set(event.nodes.map((node) => node.id))
  edges.value = edges.value.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target))
  if (selectedNodeId.value && ids.has(selectedNodeId.value)) selectedNodeId.value = null
  refreshIssues()
}

function onEdgeDelete() {
  refreshIssues()
}

function applyPatch(patch: Record<string, unknown>) {
  if (!selectedNodeId.value) return
  const node = nodes.value.find((item) => item.id === selectedNodeId.value)
  if (!node) return
  const canvas = fromVueNode(node)
  Object.assign(canvas.data, patch)
  node.data = { ...(node.data || {}), canvas }
  refreshIssues()
}

function deleteSelectedNode() {
  if (!selectedNodeId.value) return
  const id = selectedNodeId.value
  nodes.value = nodes.value.filter((node) => node.id !== id)
  edges.value = edges.value.filter((edge) => edge.source !== id && edge.target !== id)
  selectedNodeId.value = null
  refreshIssues()
}

// ------------------------------------------------------------------ load / save
async function loadList() {
  try {
    orchestrations.value = await listOrchestrations()
  } catch {
    orchestrations.value = []
  }
}

async function openOrchestration(id: string) {
  loading.value = true
  pageError.value = ''
  try {
    const detail = await fetchOrchestration(id)
    // 统一走转换层：手写 YAML 只给 depends_on 时补出边、缺 layout 时自动布局、
    // 未知顶层键存 raw 以便保存时透传（FR-007/FR-009/FR-012）。
    const canvasDoc = engineDocumentToCanvas(detail.document)
    orchestrationId.value = detail.orchestrationId
    mode.value = canvasDoc.orchestration.mode
    rawDocument.value = canvasDoc.raw
    nodes.value = canvasDoc.nodes.map(toVueNode)
    edges.value = canvasDoc.edges.map((edge, index) => toVueEdge(edge.source, edge.target, index))
    published.value = detail.status === 'published'
    refreshIssues()
  } catch (err) {
    pageError.value = errorMessage(err, t('orchestration.load_failed'))
  } finally {
    loading.value = false
  }
}

async function save(publish: boolean) {
  refreshIssues()
  if (errors.value.length) {
    notice.value = t('orchestration.validate.blocked', { count: errors.value.length })
    return
  }
  saving.value = true
  notice.value = ''
  try {
    const canvas = toCanvasDocument()
    // 落库的必须是引擎权威文档（画布只是投影）：否则 `dag_definitions.document`
    // 里存的是 kind/data/position 形状，010 引擎装载后拿不到 skill/依赖/条件。
    const document = canvasToEngineDocument(canvas)
    const result = publish
      ? await publishOrchestration(orchestrationId.value, document, canvas.layout, releaseNotes.value)
      : await saveOrchestrationDraft(orchestrationId.value, document, canvas.layout)
    notice.value = publish
      ? t('orchestration.published', { version: result.version })
      : t('orchestration.saved', { version: result.version })
    published.value = publish
    await loadList()
  } catch (err) {
    notice.value = errorMessage(err, t('orchestration.save'))
    if (String(err).includes('403') || String((err as { response?: { status?: number } })?.response?.status) === '403') {
      notice.value = t('orchestration.validate.publish_denied')
    }
  } finally {
    saving.value = false
  }
}

// ------------------------------------------------------------------ preview / dry run
function runPreview() {
  refreshIssues()
  if (errors.value.length) return
  const cycle = findCycle(nodes.value.map(fromVueNode), edges.value.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })))
  previewing.value = true
  previewState.value = {}

  const order: string[] = []
  if (!cycle) {
    const indegree: Record<string, number> = {}
    const children: Record<string, string[]> = {}
    nodes.value.forEach((node) => { indegree[node.id] = 0; children[node.id] = [] })
    edges.value.forEach((edge) => {
      if (!(edge.source in children)) return
      children[edge.source].push(edge.target)
      indegree[edge.target] = (indegree[edge.target] || 0) + 1
    })
    const queue = nodes.value.filter((node) => (indegree[node.id] || 0) === 0).map((node) => node.id)
    while (queue.length) {
      const id = queue.shift() as string
      order.push(id)
      for (const child of children[id]) {
        indegree[child] = (indegree[child] || 0) - 1
        if (indegree[child] === 0) queue.push(child)
      }
    }
  } else {
    order.push(...cycle)
  }

  let index = 0
  const timer = window.setInterval(() => {
    if (index >= order.length) {
      window.clearInterval(timer)
      previewing.value = false
      return
    }
    const id = order[index]
    previewState.value = { ...previewState.value, [id]: 'running' }
    const doneId = order[index - 1]
    if (doneId) previewState.value = { ...previewState.value, [doneId]: 'done' }
    index += 1
  }, 500)
}

function resetPreview() {
  previewState.value = {}
  previewing.value = false
}

// ------------------------------------------------------------------ node render helpers
// vue-tsc cannot parse TS type assertions inside template expressions
// (`(nodeProps.data as { canvas: CanvasNode }).canvas`), so the node slot keeps
// the template declarative and asks these helpers instead.
function canvasOf(nodeProps: { data?: unknown }): CanvasNode | null {
  const data = nodeProps?.data as { canvas?: CanvasNode } | undefined
  return data?.canvas || null
}

function nodeKind(nodeProps: { data?: unknown }): string {
  return canvasOf(nodeProps)?.kind || ''
}

function nodeLabel(nodeProps: { data?: unknown }): string {
  return canvasOf(nodeProps)?.data?.label || ''
}

function nodeCondition(nodeProps: { data?: unknown }): string {
  return ''.concat(canvasOf(nodeProps)?.data?.conditionExpr || '…')
}

// ------------------------------------------------------------------ boot
onMounted(async () => {
  try {
    const [skills, tools] = await Promise.all([
      fetchSkills(props.userId || '', props.tenantId || 'default'),
      fetchTools(props.userId || '', props.tenantId || 'default'),
    ])
    skillOptions.value = (skills || []).map((skill) => ({ label: skill.name || skill.id, value: skill.id }))
    toolOptions.value = (tools || []).map((tool) => ({ label: tool.name || tool.id, value: tool.id }))
  } catch {
    skillOptions.value = []
    toolOptions.value = []
  }
  await loadList()
  loading.value = false
  // 画布为空：放一个起始节点方便上手
  if (!nodes.value.length) addNode('start')
})
</script>

<template>
  <div class="orchestration-page">
    <header class="orchestration-header">
      <div class="orchestration-header__left">
        <n-button quaternary size="small" @click="emit('back')">{{ t('orchestration.back') }}</n-button>
        <h1>{{ t('orchestration.title') }}</h1>
        <p class="subtitle">{{ t('orchestration.subtitle') }}</p>
      </div>
      <div class="orchestration-header__right">
        <n-select
          :value="orchestrationId"
          :options="orchestrations.map((item) => ({ label: `${item.orchestrationId} (v${item.version})`, value: item.orchestrationId }))"
          size="small"
          style="width: 220px"
          filterable
          tag
          :placeholder="t('orchestration.load_yaml')"
          @update:value="(v: string) => openOrchestration(v)"
        />
        <n-select
          :value="mode"
          size="small"
          style="width: 180px"
          :options="[{ label: t('orchestration.mode.sequential'), value: 'sequential' }, { label: t('orchestration.mode.graph'), value: 'graph' }]"
          @update:value="(v: SupportedMode) => { mode = v; refreshIssues() }"
        />
        <n-button size="small" @click="runPreview">{{ t('orchestration.preview') }}</n-button>
        <n-button size="small" :disabled="saving" @click="save(false)">{{ t('orchestration.save') }}</n-button>
        <n-button size="small" type="primary" :disabled="saving" @click="save(true)">
          {{ t('orchestration.publish') }}
        </n-button>
      </div>
    </header>

    <n-alert v-if="pageError" type="error" :bordered="false" closable @close="() => (pageError = '')">
      {{ pageError }}
    </n-alert>
    <n-alert v-if="notice" :type="published ? 'success' : 'info'" :bordered="false" closable @close="() => (notice = '')">
      {{ notice }}
    </n-alert>

    <div class="validation-bar">
      <n-tag v-if="errors.length" type="error" size="small">
        {{ t('orchestration.validate.blocked', { count: errors.length }) }}
      </n-tag>
      <n-tag v-else type="success" size="small">{{ t('orchestration.validate.ok') }}</n-tag>
      <span v-for="issue in [...errors, ...warnings]" :key="issue.code" class="validation-bar__item">
        <span :class="issue.severity">{{ issue.message }}</span>
      </span>
    </div>

    <div class="orchestration-layout">
      <aside class="palette">
        <div class="palette__header" @click="paletteOpen = !paletteOpen">
          {{ t('orchestration.title') }}
        </div>
        <div v-show="paletteOpen" class="palette__list">
          <div
            v-for="item in palette"
            :key="item.kind"
            class="palette__item"
            draggable="true"
            @dragstart="onDragStart($event, item.kind)"
            @dblclick="addNode(item.kind)"
          >
            {{ item.label }}
          </div>
        </div>
        <div class="palette__hint">{{ t('orchestration.node.title_hint') }}</div>
      </aside>

      <div class="canvas-host" @drop="onDrop" @dragover.prevent>
        <n-spin :show="loading">
          <VueFlow
            v-model:nodes="nodes"
            v-model:edges="edges"
            :default-edge-options="{ animated: true }"
            :min-zoom="0.2"
            :max-zoom="2"
            :delete-key-code="['Backspace', 'Delete']"
            class="canvas-flow"
            @connect="onConnect"
            @node-click="onNodeClick"
            @node-drag-stop="onNodeDragStop"
            @nodes-delete="onNodeDelete"
            @edges-delete="onEdgeDelete"
          >
            <template #node-canvas="nodeProps">
              <div
                class="flow-node"
                :class="[`flow-node--${nodeKind(nodeProps)}`, { 'flow-node--selected': nodeProps.selected }]"
              >
                <span class="flow-node__label">{{ nodeLabel(nodeProps) }}</span>
                <span v-if="nodeKind(nodeProps) === 'condition'" class="flow-node__expr">
                  {{ nodeCondition(nodeProps) }}
                </span>
                <n-tag
                  v-if="previewState[nodeProps.id]"
                  size="tiny"
                  :type="previewState[nodeProps.id] === 'running' ? 'warning' : previewState[nodeProps.id] === 'error' ? 'error' : 'success'"
                >
                  {{ previewState[nodeProps.id] === 'running' ? '▶' : '✓' }}
                </n-tag>
              </div>
            </template>
            <Background pattern-color="#e5e7eb" :gap="24" />
            <Controls />
            <MiniMap pannable zoomable />
          </VueFlow>
        </n-spin>
      </div>

      <aside class="side-panel">
        <div v-if="selectedNode" class="side-panel__actions">
          <n-button size="tiny" type="error" quaternary @click="deleteSelectedNode">
            {{ t('orchestration.delete_node') }}
          </n-button>
        </div>
        <NodePropertyPanel
          :node="selectedNode"
          :skill-options="skillOptions"
          :tool-options="toolOptions"
          @patch="applyPatch"
          @close="selectedNodeId = null"
        />
        <n-divider />
        <div class="side-panel__release">
          <span class="label">{{ t('orchestration.release_notes') }}</span>
          <n-input v-model:value="releaseNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" size="small" />
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.orchestration-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
}
.orchestration-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.orchestration-header__left h1 {
  margin: 0;
  font-size: 18px;
}
.orchestration-header__left .subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-3, var(--mg-text-3));
}
.orchestration-header__right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.validation-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}
.validation-bar__item .error {
  color: var(--error-color, #e88080);
}
.validation-bar__item .warning {
  color: #e6a23c;
}
.orchestration-layout {
  flex: 1;
  display: grid;
  grid-template-columns: 170px 1fr 300px;
  gap: 10px;
  min-height: 0;
}
.palette {
  border: 1px solid var(--border-color, var(--mg-brand-soft-border));
  border-radius: 6px;
  padding: 8px;
  overflow: auto;
  background: var(--bg-2, var(--mg-bg-surface));
}
.palette__header {
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  margin-bottom: 8px;
}
.palette__list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.palette__item {
  padding: 6px 8px;
  border: 1px dashed var(--border-color, var(--mg-brand-soft-border));
  border-radius: 4px;
  font-size: 13px;
  cursor: grab;
  text-align: center;
}
.palette__item:hover {
  border-color: var(--mg-brand-soft-border);
  color: #2080f0;
}
.palette__hint {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-3, var(--mg-text-3));
}
.canvas-host {
  border: 1px solid var(--border-color, var(--mg-brand-soft-border));
  border-radius: 6px;
  overflow: hidden;
}
.canvas-flow {
  width: 100%;
  height: 100%;
  min-height: 480px;
}
.flow-node {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid #c0c4cc;
  border-radius: 6px;
  background: var(--mg-bg-surface);
  min-width: 90px;
  font-size: 12px;
}
.flow-node--selected {
  border-color: var(--mg-brand-soft-border);
  box-shadow: 0 0 0 2px rgba(32, 128, 240, 0.15);
}
.flow-node--start { border-left: 4px solid #18a058; }
.flow-node--llm, .flow-node--roundRobin, .flow-node--debate { border-left: 4px solid var(--mg-brand-soft-border); }
.flow-node--tool { border-left: 4px solid #f0a020; }
.flow-node--condition { border-left: 4px solid #e88080; }
.flow-node--end { border-left: 4px solid #7b7b7b; }
.flow-node--parallel, .flow-node--aggregate { border-left: 4px solid #9a6ee6; }
.flow-node__expr {
  font-size: 11px;
  color: var(--text-3, var(--mg-text-3));
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.side-panel {
  border: 1px solid var(--border-color, var(--mg-brand-soft-border));
  border-radius: 6px;
  padding: 8px 12px;
  overflow: auto;
  background: var(--bg-2, var(--mg-bg-surface));
}
.side-panel__actions {
  margin-bottom: 4px;
}
.side-panel__release .label {
  display: block;
  font-size: 12px;
  color: var(--text-2, var(--mg-text-3));
  margin-bottom: 4px;
}
</style>