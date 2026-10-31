import assert from 'node:assert/strict'
import test from 'node:test'

import { compatibleModelToolCall } from '../src/official-host/model-tool-call-compat.mjs'

function call(name, args) {
  return { type: 'tool-call', id: 'call-a', name, arguments: JSON.stringify(args) }
}

test('redundant workspace-write is removed from sandboxed Code calls', () => {
  const result = compatibleModelToolCall(call(process.platform === 'win32' ? 'pwsh' : 'bash', {
    command: 'pwd', description: 'Show workspace', sandbox_permissions: 'workspace-write',
    justification: 'Inspect the workspace.',
  }))
  assert.deepEqual(JSON.parse(result.arguments), { command: 'pwd', description: 'Show workspace' })
})

test('real danger-full-access escalation remains intact', () => {
  const event = call('write', {
    file_path: '/outside/result.txt', content: 'x', sandbox_permissions: 'danger-full-access',
    justification: 'Write the requested external file.',
  })
  assert.deepEqual(compatibleModelToolCall(event), event)
})

test('external tools cannot lose a same-named business argument', () => {
  const event = call('askai_http_policy', {
    sandbox_permissions: 'workspace-write', justification: 'business data',
  })
  assert.deepEqual(compatibleModelToolCall(event), event)
})

test('broad glob is bounded through the platform shell mounted by the Code preset', () => {
  for (const pattern of ['*', '**']) {
    const event = call('glob', { pattern, path: '/workspace' })
    const result = compatibleModelToolCall(event)
    assert.equal(result.name, process.platform === 'win32' ? 'pwsh' : 'bash')
    assert.deepEqual(JSON.parse(result.arguments), {
      command: process.platform === 'win32'
        ? 'Get-ChildItem -File -Recurse -Depth 1 -Force | Select-Object -First 200 -ExpandProperty FullName'
        : 'find . -maxdepth 2 -type f -print | LC_ALL=C sort | head -n 200',
      description: 'List bounded project files',
      workdir: '/workspace',
    })
  }
  const narrow = call('glob', { pattern: 'src/**/*.ts', path: '/workspace' })
  assert.deepEqual(compatibleModelToolCall(narrow), narrow)
})
