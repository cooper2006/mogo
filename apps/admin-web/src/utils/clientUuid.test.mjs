import assert from 'node:assert/strict'
import test from 'node:test'
import { createClientUuid } from './clientUuid.ts'

test('uses randomUUID when it is available', () => {
  assert.equal(createClientUuid({ randomUUID: () => 'native-id' }), 'native-id')
})

test('generates a valid UUID when randomUUID is unavailable on HTTP', () => {
  const id = createClientUuid({ getRandomValues: bytes => bytes.fill(0) })
  assert.match(id, /^00000000-0000-4000-8000-000000000000$/)
})

test('does not throw when Web Crypto is unavailable', () => {
  assert.match(createClientUuid(null), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
})
