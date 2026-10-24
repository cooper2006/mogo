// Frontend-side encoder / decoder for the composite_task skill markdown.
// The backend already understands this shape (see
// backend/app/runtime/skills/composite_task.py); the two must stay in sync.

// Signal bag for one user-authored locator. AND-combined at match
// time; every field optional. Mirrors
// backend/app/runtime/browser/rules/locator.py.
export type Locator = {
  role?: string
  name?: string
  name_contains?: string
  aria_label?: string
  icon_class?: string
  text?: string
  ancestor_role?: string
  ancestor_contains_text?: string
  nth?: number
}

// Per-op locator bag. ``primary`` is the default key used by Line A
// (manual) authors and the recorder; CRUD-aware steps may also emit
// per-op locators (update/delete/...).
export type LocatorBag = Record<string, Locator>

export type CompositeStep = {
  instruction: string
  site_profile_id?: string
  kind?: string
  title?: string
  locators?: LocatorBag
  locator_vars?: Record<string, string>
}

export type CompositeSkillDraft = {
  triggers: string[]
  steps: CompositeStep[]
}

// Minimal YAML emitter for our narrow schema — avoids pulling js-yaml
// into the bundle. We only need to produce a subset (lists of scalars,
// and a list of shallow objects). Any string that isn't "safe" gets
// block-scalar encoded.
function isSafeInline(s: string): boolean {
  return !!s && !/[\n:#"'`{}[],&*!|>%@`]/.test(s) && s.trim() === s
}

function dumpScalar(value: string): string {
  if (value === '') return '""'
  if (isSafeInline(value)) return value
  const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return `"${escaped}"`
}

function dumpMultiline(key: string, value: string, indent: string): string {
  // Use literal block scalar for strings with newlines.
  const lines = value.split('\n').map(l => `${indent}  ${l}`).join('\n')
  return `${indent}${key}: |\n${lines}`
}

// 编码 locators 块：op → locator 字段（缩进 6 / 8）。
function pushLocatorLines(lines: string[], locators: LocatorBag): void {
  lines.push('    locators:')
  for (const [op, loc] of Object.entries(locators)) {
    if (!loc || !Object.keys(loc).length) continue
    lines.push(`      ${op}:`)
    for (const [k, v] of Object.entries(loc)) {
      if (v === undefined || v === '' || v === null) continue
      lines.push(`        ${k}: ${typeof v === 'number' ? String(v) : dumpScalar(String(v))}`)
    }
  }
}

// 编码单个 step 为 YAML 片段并追加到 lines。
function pushStepLines(lines: string[], step: CompositeStep): void {
  lines.push('  - instruction: ' + (step.instruction.includes('\n') ? '|' : dumpScalar(step.instruction)))
  if (step.instruction.includes('\n')) {
    for (const l of step.instruction.split('\n')) lines.push(`      ${l}`)
  }
  if (step.site_profile_id) lines.push(`    site_profile_id: ${dumpScalar(step.site_profile_id)}`)
  if (step.kind) lines.push(`    kind: ${dumpScalar(step.kind)}`)
  if (step.title) lines.push(`    title: ${dumpScalar(step.title)}`)
  if (step.locators && Object.keys(step.locators).length) {
    pushLocatorLines(lines, step.locators)
  }
  if (step.locator_vars && Object.keys(step.locator_vars).length) {
    lines.push('    locator_vars:')
    for (const [k, v] of Object.entries(step.locator_vars)) {
      lines.push(`      ${k}: ${dumpScalar(String(v ?? ''))}`)
    }
  }
}

export function encodeCompositeSkill(
  draft: CompositeSkillDraft,
  meta: { name: string; description: string },
): string {
  const lines: string[] = ['---']
  if (meta.name) lines.push(`name: ${dumpScalar(meta.name)}`)
  if (meta.description) {
    if (meta.description.includes('\n')) {
      lines.push('description: |')
      for (const l of meta.description.split('\n')) lines.push(`  ${l}`)
    } else {
      lines.push(`description: ${dumpScalar(meta.description)}`)
    }
  }
  if (draft.triggers.length) {
    lines.push('triggers:')
    for (const t of draft.triggers) lines.push(`  - ${dumpScalar(t)}`)
  }
  lines.push('steps:')
  for (const step of draft.steps) {
    pushStepLines(lines, step)
  }
  lines.push('---')
  return lines.join('\n') + '\n'
}

// 解码状态：section 为当前顶层段，nested 为 steps 段内的嵌套块。
type DecodeState = {
  triggers: string[]
  steps: CompositeStep[]
  section: 'none' | 'triggers' | 'steps'
  nested: 'none' | 'locators' | 'locator_vars'
  nestedOp: string
  currentStep: CompositeStep | null
}

// 结束当前 step：instruction 非空才落库。
function flushStep(state: DecodeState): void {
  if (state.currentStep && state.currentStep.instruction.trim()) state.steps.push(state.currentStep)
  state.currentStep = null
}

// 顶层段头：triggers: / steps: / 其它无关键（跳过）。
function parseSectionHeader(line: string, state: DecodeState): boolean {
  if (/^triggers:\s*$/.test(line)) {
    flushStep(state)
    state.section = 'triggers'
    return true
  }
  if (/^steps:\s*$/.test(line)) {
    flushStep(state)
    state.section = 'steps'
    return true
  }
  if (/^[a-zA-Z_]+:\s*/.test(line) && !line.startsWith('  ')) {
    // Unrelated top-level keys (name / description) — skip; we get them from props.
    flushStep(state)
    state.section = 'none'
    return true
  }
  return false
}

// triggers 段：单行 `- <值>`，去掉包裹引号后收集。
function parseTriggerLine(line: string, state: DecodeState): void {
  const mm = /^\s*-\s*(.*)$/.exec(line)
  if (!mm) return
  const v = mm[1].trim().replace(/^"|"$/g, '')
  if (v) state.triggers.push(v)
}

// steps 段：新的 step 头部（缩进 2 的 `- instruction: <值>`）。
function parseStepHeader(line: string, state: DecodeState): boolean {
  const newItem = /^\s{2}-\s*instruction:\s*(.*)$/.exec(line)
  if (!newItem) return false
  flushStep(state)
  const raw = newItem[1].trim().replace(/^"|"$/g, '')
  state.currentStep = { instruction: raw === '|' ? '' : raw }
  state.nested = 'none'
  state.nestedOp = ''
  return true
}

// steps 段：step 顶层字段（缩进 4 的 `key: value`）。
function parseStepField(line: string, state: DecodeState): boolean {
  const step = state.currentStep
  if (!step) return false
  const kv = /^\s{4}([a-zA-Z_]+):\s*(.*)$/.exec(line)
  if (!kv) return false
  const key = kv[1]
  const val = kv[2].trim().replace(/^"|"$/g, '')
  if (key === 'site_profile_id') { step.site_profile_id = val; state.nested = 'none' }
  else if (key === 'kind') { step.kind = val; state.nested = 'none' }
  else if (key === 'title') { step.title = val; state.nested = 'none' }
  else if (key === 'locators') { step.locators = {}; state.nested = 'locators'; state.nestedOp = '' }
  else if (key === 'locator_vars') { step.locator_vars = {}; state.nested = 'locator_vars' }
  else { state.nested = 'none' }
  return true
}

// steps 段：locators 块内的 op 行（缩进 6）与字段行（缩进 8）。
function parseLocatorLine(line: string, state: DecodeState): boolean {
  if (state.nested !== 'locators') return false
  const step = state.currentStep
  if (!step) return false
  const locators = step.locators
  const opLine = /^\s{6}([a-zA-Z_]+):\s*$/.exec(line)
  if (opLine) {
    state.nestedOp = opLine[1]
    if (locators) locators[state.nestedOp] = {}
    return true
  }
  const locKv = /^\s{8}([a-zA-Z_]+):\s*(.*)$/.exec(line)
  if (!locKv || !state.nestedOp || !locators) return false
  const bag = locators[state.nestedOp]
  if (!bag) return false
  const k = locKv[1]
  const v = locKv[2].trim().replace(/^"|"$/g, '')
  if (k === 'nth') {
    const n = Number(v)
    if (!Number.isNaN(n)) (bag as any).nth = n
  } else {
    (bag as any)[k] = v
  }
  return true
}

// steps 段：locator_vars 块内的字段行（缩进 6）。
function parseLocatorVarsLine(line: string, state: DecodeState): boolean {
  if (state.nested !== 'locator_vars') return false
  const step = state.currentStep
  if (!step) return false
  const kv2 = /^\s{6}([a-zA-Z_]+):\s*(.*)$/.exec(line)
  if (!kv2) return false
  const v = kv2[2].trim().replace(/^"|"$/g, '')
  if (!step.locator_vars) step.locator_vars = {}
  step.locator_vars[kv2[1]] = v
  return true
}

// steps 段：多行 instruction 的续行（缩进 6 且不在嵌套块内）。
function parseInstructionContinuation(line: string, state: DecodeState): void {
  if (state.nested !== 'none') return
  const step = state.currentStep
  if (!step) return
  const cont = /^\s{6}(.*)$/.exec(line)
  if (!cont) return
  step.instruction = (step.instruction ? step.instruction + '\n' : '') + cont[1]
}

// Tiny decoder: read back what encodeCompositeSkill wrote. Good enough for
// reload/edit of skills authored by our own editor; any skill authored by
// hand with exotic YAML will still survive because the server is the
// source of truth.
export function decodeCompositeSkill(markdown: string): CompositeSkillDraft {
  const m = /^---\s*\n([\s\S]*?)\n---/m.exec(markdown || '')
  if (!m) return { triggers: [], steps: [] }

  const state: DecodeState = {
    triggers: [],
    steps: [],
    section: 'none',
    nested: 'none',
    nestedOp: '',
    currentStep: null,
  }

  for (const rawLine of m[1].split(/\r?\n/)) {
    const line = rawLine
    if (parseSectionHeader(line, state)) continue
    if (state.section === 'triggers') {
      parseTriggerLine(line, state)
      continue
    }
    if (state.section === 'steps') {
      if (parseStepHeader(line, state)) continue
      if (!state.currentStep) continue
      if (parseStepField(line, state)) continue
      if (parseLocatorLine(line, state)) continue
      if (parseLocatorVarsLine(line, state)) continue
      parseInstructionContinuation(line, state)
    }
  }
  flushStep(state)
  return { triggers: state.triggers, steps: state.steps }
}
