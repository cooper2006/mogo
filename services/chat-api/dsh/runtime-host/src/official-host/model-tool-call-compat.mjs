const SANDBOXED_CODE_TOOLS = new Set(['bash', 'pwsh', 'edit', 'write', 'run_code'])
const SHELL_TOOL = process.platform === 'win32' ? 'pwsh' : 'bash'
const BOUNDED_FILE_LIST_COMMAND = process.platform === 'win32'
  ? 'Get-ChildItem -File -Recurse -Depth 1 -Force | Select-Object -First 200 -ExpandProperty FullName'
  : 'find . -maxdepth 2 -type f -print | LC_ALL=C sort | head -n 200'

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

  // Every MOGO desktop Code Session already runs at workspace-write. Some
  // providers echo that standing mode as an escalation, which DSH correctly
  // rejects because an escalation must be strictly wider. Treat the redundant
  // request as a no-op while preserving real danger-full-access approvals.
  if (SANDBOXED_CODE_TOOLS.has(name) && args.sandbox_permissions === 'workspace-write') {
    delete args.sandbox_permissions
    delete args.justification
    changed = true
  }

  // A bare wildcard is interpreted as a whole-tree search by this DSH train.
  // Bound the directory-listing probe and use the shell tool actually mounted
  // by the shipped Code preset (pwsh on Windows, bash elsewhere).
  if (name === 'glob' && (args.pattern === '*' || args.pattern === '**')) {
    return {
      ...event,
      name: SHELL_TOOL,
      arguments: JSON.stringify({
        command: BOUNDED_FILE_LIST_COMMAND,
        description: 'List bounded project files',
        ...(typeof args.path === 'string' && args.path ? { workdir: args.path } : {}),
      }),
    }
  }

  return changed ? { ...event, arguments: JSON.stringify(args) } : event
}
