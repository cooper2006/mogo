/**
 * 043 (session replay): step drill-down view model.
 *
 * The trajectory tab renders every assistant round; the replay adds a second
 * level — clicking one step opens its input / output / duration. This module
 * keeps the extraction pure (no Vue, no store) so it can be unit tested, and it
 * is deliberately honest: a missing payload field renders as an empty string,
 * never as a fabricated value (spec FR-004 / R-07).
 */

import type { ExecutionEventV3 } from './protocol'
import { elapsedRunMs } from './runTiming'

/** Shape of one item as stored by `createExecutionStoreV3` (`domain/model`). */
export type ReplayStepSource = {
  id: string
  kind: string
  status: string
  startedAt?: number | null
  updatedAt?: number | null
  payload?: Record<string, any>
}

export type ReplayStep = {
  id: string
  kind: string
  status: string
  durationMs: number | null
  running: boolean
  input: string
  output: string
  /** Only set when the event payload actually carried a cost (035 not landed yet). */
  costUsd: number | null
  payload: Record<string, any>
}

const MAX_SUMMARY_CHARS = 600

function textFrom(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value === null || value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function clamp(text: string, limit = MAX_SUMMARY_CHARS): string {
  const value = String(text || '').trim()
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

function firstText(payload: Record<string, any>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = payload[key]
    if (value === null || value === undefined || value === '') continue
    return textFrom(value)
  }
  return ''
}

/**
 * Read a per-step cost from the payload.
 *
 * Spec R-07/R-13: only a finite numeric `cost_usd` / `costUsd` counts; anything
 * else (missing, null, NaN, a string) means "no cost row" — never render `0`
 * for an unknown cost.
 */
export function readCostUsd(payload: Record<string, any> | undefined): number | null {
  if (!payload) return null
  for (const key of ['cost_usd', 'costUsd'] as const) {
    const raw = payload[key]
    // Strictly numeric: a string like "0.01" is not a measured cost, it is an
    // unknown one, so it must not be rendered as a value (spec R-07).
    if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  }
  return null
}

/** Input column: what the step was asked to do. */
export function stepInputText(item: ReplayStepSource): string {
  const payload = item.payload || {}
  const kind = String(item.kind || '')
  if (kind === 'tool') {
    return clamp(firstText(payload, ['args', 'arguments', 'input', 'params', 'query']))
  }
  if (kind === 'activity' || kind === 'commentary') {
    return clamp(firstText(payload, ['title', 'label', 'phase', 'input']))
  }
  if (kind === 'subagent') {
    return clamp(firstText(payload, ['task', 'prompt', 'input', 'title']))
  }
  return clamp(firstText(payload, ['input']))
}

/** Output column: what the step produced. */
export function stepOutputText(item: ReplayStepSource): string {
  const payload = item.payload || {}
  const kind = String(item.kind || '')
  if (kind === 'tool') {
    return clamp(
      firstText(payload, ['result', 'output', 'observation', 'summary', 'error', 'text']),
    )
  }
  if (kind === 'evidence') {
    return clamp(firstText(payload, ['summary', 'title', 'text']) || evidenceSourceSummary(payload))
  }
  if (kind === 'error') {
    return clamp(firstText(payload, ['message', 'error', 'text']))
  }
  if (kind === 'artifact') {
    return clamp(firstText(payload, ['title', 'name', 'object_path', 'summary']))
  }
  return clamp(firstText(payload, ['text', 'output', 'summary', 'message']))
}

function evidenceSourceSummary(payload: Record<string, any>): string {
  const sources = Array.isArray(payload.sources) ? payload.sources : []
  if (!sources.length) return ''
  return clamp(
    sources
      .slice(0, 5)
      .map((source: any) => String(source?.title || source?.citation_id || source?.document_id || ''))
      .filter(Boolean)
      .join('\n'),
  )
}

/**
 * Build the drill-down view model for one execution store snapshot.
 *
 * `now` is passed in (not read from the clock) so the running duration stays a
 * pure function of its inputs and the component can re-render it on a timer.
 */
export function extractReplaySteps(
  order: readonly string[] | undefined,
  items: Record<string, ReplayStepSource> | undefined,
  now: number,
): ReplayStep[] {
  if (!order || !items) return []
  const steps: ReplayStep[] = []
  for (const id of order) {
    const item = items[id]
    if (!item) continue
    const running = item.status === 'running'
    steps.push({
      id: String(item.id || id),
      kind: String(item.kind || ''),
      status: String(item.status || ''),
      durationMs: elapsedRunMs(
        item.startedAt ?? null,
        running ? null : item.updatedAt ?? null,
        now,
      ),
      running,
      input: stepInputText(item),
      output: stepOutputText(item),
      costUsd: readCostUsd(item.payload),
      payload: item.payload || {},
    })
  }
  return steps
}

/** Stable, human readable one-line label for a step (used by the drill list). */
export function stepLabel(step: ReplayStep): string {
  const payload = step.payload || {}
  const name = firstText(payload, ['name', 'tool', 'tool_name', 'title', 'label', 'kind'])
  return name || step.kind
}

/** Whether this event belongs to an item and may be drilled into. */
export function isDrillableEvent(event: ExecutionEventV3): boolean {
  return Boolean(event.item_id && event.item_kind)
}
