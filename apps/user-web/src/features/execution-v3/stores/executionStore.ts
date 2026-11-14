import { computed, markRaw, reactive } from 'vue'
import type { ArtifactItem, EvidenceBundleItem } from '../domain/delivery'
import type { ExecutionItemV3, ExecutionStateV3, V3ItemStatus } from '../domain/model'
import { isExecutionEventV3, type ExecutionEventV3 } from '../domain/protocol'
import { TERMINAL_RUN_EVENT_TYPES } from '../domain/runTiming'

function freshState(): ExecutionStateV3 {
  return {
    items: {}, order: [], artifacts: [], evidenceBundles: [], errors: [], intervention: null,
    rawEvents: [], seenEventIds: new Set<string>(), runStatus: 'idle',
    runStartedAt: null, runEndedAt: null, finalAnswerComplete: false,
  }
}

function statusFor(type: ExecutionEventV3['type']): V3ItemStatus {
  if (type === 'item.completed') return 'completed'
  if (type === 'item.failed') return 'failed'
  return 'running'
}

// 运行终态事件对应的项目收尾状态
function statusForTerminalRun(type: ExecutionEventV3['type']): V3ItemStatus {
  if (type === 'run.completed') return 'completed'
  if (type === 'run.cancelled') return 'cancelled'
  return 'abandoned'
}

// 浏览器交付事件显式清场时绕过修订号去重
function clearsBrowserIntervention(existing: ExecutionItemV3 | undefined, event: ExecutionEventV3): boolean {
  return Boolean(
    existing
    && event.item_kind === 'browser_handoff'
    && event.type === 'item.completed'
    && event.payload?.cleared,
  )
}

// 合并既有 payload 与本次载荷，增量文本按段追加
function buildItemPayload(existing: ExecutionItemV3 | undefined, event: ExecutionEventV3): Record<string, any> {
  const payload = { ...(existing?.payload || {}), ...(event.payload || {}) }
  if (event.type === 'item.delta') payload.text = String(existing?.payload?.text || '') + String(event.payload?.text || '')
  return payload
}

// 组装项目行，终态行不因后续 running 事件回退
function buildExecutionItem(
  event: ExecutionEventV3,
  itemId: string,
  itemKind: ExecutionItemV3['kind'],
  existing: ExecutionItemV3 | undefined,
  clearsIntervention: boolean,
  payload: Record<string, any>,
): ExecutionItemV3 {
  const nextStatus = statusFor(event.type)
  const terminalExisting = existing && ['completed', 'failed', 'cancelled', 'abandoned'].includes(existing.status)
  return {
    id: itemId,
    kind: itemKind,
    parentId: event.parent_item_id || existing?.parentId,
    revision: clearsIntervention ? existing!.revision + 1 : event.revision,
    startedAt: existing?.startedAt || event.ts,
    updatedAt: event.ts,
    status: terminalExisting && nextStatus === 'running' ? existing.status : nextStatus,
    payload,
  }
}

export function createExecutionStoreV3() {
  const state = reactive<ExecutionStateV3>(freshState())

  function applyEvent(event: ExecutionEventV3) {
    if (!acceptEvent(event)) return
    applyRunLifecycle(event)
    finalizeRunningItems(event)
    const item = upsertItem(event)
    if (!item) return
    applyItemSideEffects(item, event, item.payload)
  }

  function reset() {
    Object.assign(state, freshState())
  }

  // 去重并记录原始事件，返回是否接受
  function acceptEvent(event: ExecutionEventV3): boolean {
    if (!isExecutionEventV3(event) || state.seenEventIds.has(event.event_id)) return false
    state.seenEventIds.add(event.event_id)
    state.rawEvents.push(event)
    return true
  }

  // 记录运行级状态与计时
  function applyRunLifecycle(event: ExecutionEventV3): void {
    if (event.type === 'run.started') {
      state.runStatus = 'running'
      if (state.runStartedAt === null) state.runStartedAt = event.ts
      state.runEndedAt = null
    }
    if (event.type === 'run.completed') state.runStatus = 'completed'
    if (event.type === 'run.failed') state.runStatus = 'failed'
    if (event.type === 'run.cancelled') state.runStatus = 'cancelled'
    if (event.type === 'run.blocked') state.runStatus = 'blocked'
    if (TERMINAL_RUN_EVENT_TYPES.has(event.type)) state.runEndedAt = event.ts
  }

  // 运行终止时收尾仍在运行的项目
  function finalizeRunningItems(event: ExecutionEventV3): void {
    if (!['run.completed', 'run.failed', 'run.cancelled'].includes(event.type)) return
    for (const id of state.order) {
      const item = state.items[id]
      if (item.status !== 'running') continue
      item.status = statusForTerminalRun(event.type)
    }
  }

  // 写入或更新项目行，被抑制的事件返回 null
  function upsertItem(event: ExecutionEventV3): ExecutionItemV3 | null {
    const itemId = event.item_id
    const itemKind = event.item_kind
    if (!itemId || !itemKind) return null
    const existing = state.items[itemId]
    const clearsIntervention = clearsBrowserIntervention(existing, event)
    if (existing && event.revision <= existing.revision && !clearsIntervention) return null
    const payload = buildItemPayload(existing, event)
    const item = buildExecutionItem(event, itemId, itemKind, existing, clearsIntervention, payload)
    state.items[item.id] = item
    if (!existing) state.order.push(item.id)
    return item
  }

  // 项目落地后的派生副作用（产物、证据、干预、错误）
  function applyItemSideEffects(item: ExecutionItemV3, event: ExecutionEventV3, payload: Record<string, any>): void {
    if (item.kind === 'final_answer' && event.type === 'item.completed') state.finalAnswerComplete = true
    if (item.kind === 'browser_handoff') {
      state.intervention = event.type === 'item.completed' ? null : payload
    }
    if (item.kind === 'error' && event.type === 'item.failed') state.errors.push(String(payload.message || 'unknown error'))
    if (item.kind === 'artifact' && event.type === 'item.completed') addArtifactFromPayload(item, payload)
    if (item.kind === 'evidence' && event.type === 'item.completed') addEvidenceBundleFromPayload(item, payload)
    if (item.kind === 'tool' && event.type === 'item.completed') applyToolCompletionSideEffects(item, payload)
  }

  function addArtifactFromPayload(item: ExecutionItemV3, payload: Record<string, any>): void {
    const artifact: ArtifactItem = { id: item.id, ts: item.updatedAt, kind: String(payload.kind || 'document'), ...payload }
    if (!isDuplicateArtifact(artifact)) state.artifacts.push(artifact)
  }

  function addEvidenceBundleFromPayload(item: ExecutionItemV3, payload: Record<string, any>): void {
    const bundle = { id: item.id, ts: item.updatedAt, ...payload } as EvidenceBundleItem
    if (!state.evidenceBundles.some((value) => value.id === bundle.id)) state.evidenceBundles.push(bundle)
  }

  function applyToolCompletionSideEffects(item: ExecutionItemV3, payload: Record<string, any>): void {
    const browserIntervention = payload.browser_intervention as Record<string, any> | undefined
    if (browserIntervention?.suspension_id) state.intervention = browserIntervention
    const evidence = payload.evidence_bundle as EvidenceBundleItem | undefined
    if (evidence && !state.evidenceBundles.some((value) => value.id === evidence.id)) {
      const { ts: _existingTs, ...evidenceRest } = evidence
      state.evidenceBundles.push({ ts: item.updatedAt, ...evidenceRest })
    }
    const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : []
    artifacts.forEach((value: Record<string, any>, index: number) => addArtifactFromToolPayload(item, value, index))
  }

  function addArtifactFromToolPayload(item: ExecutionItemV3, value: Record<string, any>, index: number): void {
    const artifact: ArtifactItem = {
      id: String(value.id || value.object_path || `${item.id}:${index}`),
      ts: item.updatedAt,
      kind: String(value.kind || value.type || 'document'),
      ...value,
    }
    if (!isDuplicateArtifact(artifact)) state.artifacts.push(artifact)
  }

  function isDuplicateArtifact(artifact: ArtifactItem): boolean {
    return state.artifacts.some((existing) => existing.id === artifact.id || (artifact.object_path && existing.object_path === artifact.object_path))
  }

  function loadHistory(events: any[] | undefined) {
    for (const event of events || []) if (isExecutionEventV3(event)) applyEvent(event)
    if (state.runStatus === 'running') {
      state.runStatus = 'failed'
      state.runEndedAt = Math.max(state.runStartedAt || 0, ...state.rawEvents.map((event) => Number(event.ts) || 0)) || null
      for (const id of state.order) if (state.items[id].status === 'running') state.items[id].status = 'abandoned'
    }
  }

  function resumeLive() {
    const hasTerminalEvent = state.rawEvents.some((event) => TERMINAL_RUN_EVENT_TYPES.has(event.type))
    if (hasTerminalEvent) return
    state.runStatus = 'running'
    state.runEndedAt = null
    for (const id of state.order) {
      const item = state.items[id]
      if (item.status !== 'abandoned') continue
      const latest = [...state.rawEvents].reverse().find((event) => event.item_id === id)
      if (latest && !['item.completed', 'item.failed'].includes(latest.type)) item.status = 'running'
    }
  }

  const visibleItems = computed(() => state.order
    .map((id) => state.items[id])
    .filter((item) => item.kind !== 'final_answer' || Boolean(item.payload?.provisional)))
  // Execution stores are service objects containing refs and methods. They can
  // be attached to a deeply-reactive message, but the service boundary itself
  // must not be proxied or Vue will auto-unwrap visibleItems.
  return markRaw({ state, applyEvent, loadHistory, resumeLive, reset, visibleItems })
}

export type ExecutionStoreV3 = ReturnType<typeof createExecutionStoreV3>
