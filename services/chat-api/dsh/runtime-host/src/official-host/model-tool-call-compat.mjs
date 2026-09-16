const SANDBOXED_CODE_TOOLS = new Set(['bash', 'edit', 'write', 'run_code'])

function parseArguments(value) {
  if (typeof value !== 'string') return undefined
  try {
    const parsed = JSON.parse(value)
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

/** Normalize known model-call mismatches at the DSH bridge boundary. */
export function compatibleModelToolCall(event) {
  if (event?.type !== 'tool-call') return event
  const name = String(event.name ?? '')
  const args = parseArguments(event.arguments)
  if (args === undefined) return event
  let changed = false

  // Every MOVO desktop Code Session already runs at workspace-write. Some
  // providers echo that standing mode as an escalation, which DSH correctly
  // rejects because an escalation must be strictly wider. Treat the redundant
  // request as a no-op while preserving real danger-full-access approvals.
  if (SANDBOXED_CODE_TOOLS.has(name) && args.sandbox_permissions === 'workspace-write') {
    delete args.sandbox_permissions
    delete args.justification
    changed = true
  }

  // DSH 0.1.6 glob treats a separator-free "*" as a recursive whole-tree
  // search. In large repositories its subprocess can exceed the raw-output
  // seam before the tool applies its advertised result cap. This exact call is
  // normally a mistaken directory listing, so route it to a bounded, static
  // shell probe. Narrower glob patterns are untouched.
  if (name === 'glob' && (args.pattern === '*' || args.pattern === '**')) {
    return {
      ...event,
      name: 'bash',
      arguments: JSON.stringify({
        command: "find . -maxdepth 2 -type f -print | LC_ALL=C sort | head -n 200",
        description: 'List bounded project files',
        ...(typeof args.path === 'string' && args.path ? { workdir: args.path } : {}),
      }),
    }
  }

  return changed ? { ...event, arguments: JSON.stringify(args) } : event
}
