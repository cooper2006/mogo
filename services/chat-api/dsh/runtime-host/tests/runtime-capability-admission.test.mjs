import assert from 'node:assert/strict'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { KernelRuntime } from '../src/kernel-runtime.mjs'
import {
  modelProfile,
  ndjson,
  requestBody,
  sendText,
  waitFor,
  withModelServer,
} from './support/runtime-admission.mjs'

function tool(name) {
  return {
    name,
    version: `${name}-v1`,
    source_type: 'mcp',
    external_tool_id: name,
    mcp_tool_name: name,
    description: `MOVO governed ${name}`,
    input_schema: { type: 'object', properties: {}, additionalProperties: false },
    output_schema: {},
    output_validation: 'none',
    risk_level: 'read',
    approval_required: false,
    required_scopes: ['tools:read'],
    timeout_ms: 15_000,
  }
}

test('runtime exposes every MOVO-governed tool through the stable capability contract', async () => {
  const root = await mkdtemp(join(tmpdir(), 'askai-runtime-tools-admission-'))
  const profile = modelProfile('http://127.0.0.1:9/model', {
    toolProfile: {
      gatewayUrl: 'http://127.0.0.1:9/tools',
      accessToken: 'ephemeral-tool-token',
      tools: [tool('crm_lookup'), tool('document_publish')],
      nativeReplacements: [],
    },
  })
  const runtime = new KernelRuntime({
    runtimeId: 'runtime-tools-admission', isolationKey: 'tenant:runtime-tools-admission',
    profileVersion: profile.profileVersion, storageRoot: root, modelProfile: profile,
  })
  try {
    await runtime.start()
    const session = await runtime.createSession({ sessionId: 'tools' })
    for (const name of ['crm_lookup', 'document_publish']) {
      assert.ok(session.modelTools.includes(name), `${name} missing from model tools`)
      assert.ok(session.capabilityTools.includes(name), `${name} missing from capability tools`)
    }
  } finally {
    await runtime.dispose()
    await rm(root, { recursive: true, force: true })
  }
})

test('runtime discovers and loads a Skill installed in the MOVO workspace', async () => {
  const root = await mkdtemp(join(tmpdir(), 'askai-runtime-skill-admission-'))
  await mkdir(join(root, '.agents', 'skills', 'installed-audit'), { recursive: true })
  await writeFile(
    join(root, '.agents', 'skills', 'installed-audit', 'SKILL.md'),
    '---\nname: installed-audit\ndescription: Verify installed Skill discovery.\n---\n# Installed audit\nReturn INSTALLED_SKILL_OK.\n',
  )
  const calls = []
  try {
    await withModelServer(async (request, response) => {
      const body = await requestBody(request)
      calls.push(body)
      if (calls.length === 1) return ndjson(response, [
        { type: 'tool-call', id: 'load-installed-skill', name: 'skill', arguments: JSON.stringify({ name: 'installed-audit' }) },
        { type: 'finish', reason: { kind: 'tool-calls' } },
      ])
      return ndjson(response, [
        { type: 'text-delta', text: 'INSTALLED_SKILL_OK' },
        { type: 'finish', reason: { kind: 'stop' } },
      ])
    }, async baseUrl => {
      const profile = modelProfile(`${baseUrl}/model`)
      const runtime = new KernelRuntime({
        runtimeId: 'runtime-skill-admission', isolationKey: 'tenant:runtime-skill-admission',
        profileVersion: profile.profileVersion, storageRoot: root, modelProfile: profile,
      })
      try {
        await runtime.start()
        const session = await runtime.createSession({ sessionId: 'skill', presetId: 'code', cwd: root })
        assert.ok(session.modelTools.includes('skill'))
        sendText(runtime, 'skill', 'Use the installed audit Skill.')
        await waitFor(() => calls.length >= 2, 'installed Skill was not loaded')
        await waitFor(
          () => runtime.events('skill', -1).some(event => event.nativeType === 'turn/end'),
          'installed Skill turn did not complete',
        )
        assert.match(JSON.stringify(calls[0]), /installed-audit/)
        assert.match(JSON.stringify(calls[1]), /INSTALLED_SKILL_OK/)
      } finally {
        await runtime.dispose()
      }
    })
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
