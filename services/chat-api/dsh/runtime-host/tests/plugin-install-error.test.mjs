import assert from 'node:assert/strict'
import test from 'node:test'

import { pluginInstallError } from '../src/official-host/plugin-install-error.mjs'

test('plugin install failure preserves DSH diagnostic details', () => {
  const error = pluginInstallError({ name: 'example' }, {
    application: 'failed',
    error: { code: 'operation-error', diagnostic: 'registry returned 404 for example@1.0.0' },
  })
  assert.match(error.message, /operation-error/)
  assert.match(error.message, /registry returned 404/)
  assert.match(error.message, /example@1\.0\.0/)
})
