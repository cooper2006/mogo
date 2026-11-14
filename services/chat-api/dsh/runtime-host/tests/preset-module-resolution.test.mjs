import assert from 'node:assert/strict'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

import { resolvePresetModules } from '../src/official-host/preset-module-resolution.mjs'

const installation = {
  resolveDependency(name) {
    return `/installed/${name.replaceAll('/', '_')}`
  },
}

test('resolve package modules inside declarative preset groups without rewriting custom modules', () => {
  const source = [{ insert: [{
    id: 'preset-test', name: '@deepseek-ai/dsh-agent-preset',
    config: { id: 'test', plugins: [{
      id: 'group', group: true, config: [
        { id: 'native', name: '@deepseek-ai/dsh-tool-skill' },
        { id: 'custom', name: '/mogo/custom-plugin.mjs' },
      ],
    }] },
  }] }]

  const result = resolvePresetModules(source, installation)
  const native = '/installed/@deepseek-ai_dsh-tool-skill'
  const custom = '/mogo/custom-plugin.mjs'
  assert.equal(result[0].insert[0].config.plugins[0].config[0].name,
    process.platform === 'win32' ? pathToFileURL(native).href : native)
  assert.equal(result[0].insert[0].config.plugins[0].config[1].name,
    process.platform === 'win32' ? pathToFileURL(custom).href : custom)
  assert.equal(source[0].insert[0].config.plugins[0].config[0].name, '@deepseek-ai/dsh-tool-skill')
})

test('drop unmounted schedule tools from shipped subagent deny list only', () => {
  const patches = [{ insert: [{
    id: 'preset-test', name: '@deepseek-ai/dsh-agent-preset',
    config: { id: 'test', plugins: [{
      id: 'tool-subagent', name: '@deepseek-ai/dsh-tool-subagent',
      config: { toolFilter: { deny: ['schedule_create', 'read', 'schedule_list'] } },
    }] },
  }] }]

  const result = resolvePresetModules(patches, installation)
  assert.deepEqual(result[0].insert[0].config.plugins[0].config.toolFilter.deny, ['read'])
})

test('Windows declarative preset rows use importable file URLs for package and custom paths', () => {
  const nativePath = installation.resolveDependency('@deepseek-ai/dsh-tool-skill')
  const customPath = import.meta.filename
  const source = [{ insert: [{
    name: '@deepseek-ai/dsh-agent-preset',
    config: { id: 'test', plugins: [
      { id: 'native', name: '@deepseek-ai/dsh-tool-skill' },
      { id: 'custom', name: customPath },
      { id: 'relative', name: './relative-plugin.mjs' },
    ] },
  }] }]
  const rows = resolvePresetModules(source, installation)[0].insert[0].config.plugins
  assert.equal(rows[0].name, process.platform === 'win32' ? pathToFileURL(nativePath).href : nativePath)
  assert.equal(rows[1].name, process.platform === 'win32' ? pathToFileURL(customPath).href : customPath)
  assert.equal(rows[2].name, './relative-plugin.mjs')
  assert.equal(source[0].insert[0].config.plugins[0].name, '@deepseek-ai/dsh-tool-skill')
})
