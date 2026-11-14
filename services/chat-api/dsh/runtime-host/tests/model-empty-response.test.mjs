import assert from 'node:assert/strict'
import test from 'node:test'

import { AskaiModelGatewayAdapter } from '../src/askai-model-gateway-plugin.mjs'

test('a successful HTTP response with no model output is an error', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('{"type":"finish","reason":{"kind":"stop"}}\n', { status: 200 })
  try {
    const adapter = new AskaiModelGatewayAdapter({
      profileVersion: 'profile-a', modelInstanceId: 'model-a', modelName: 'test-model',
      gatewayUrl: 'https://gateway.example.test/generate', accessToken: 'test-token',
    })
    await assert.rejects(async () => {
      for await (const _event of adapter.stream({
        provider: 'askai-model-gateway', model: 'test-model',
        sessionId: 'session-a', messages: [{ role: 'user', content: [{ type: 'text', text: 'test' }] }],
      })) {}
    }, /no text or tool calls/)
  } finally {
    globalThis.fetch = originalFetch
  }
})
