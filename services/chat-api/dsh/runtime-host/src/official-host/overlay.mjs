import { resolve } from 'node:path'

import { planOverlayRows } from './overlay-planner.mjs'

export const ASKAI_DSH_HOST_OVERLAY_VERSION = 'askai-dsh-host-v1'
export const ASKAI_ENTERPRISE_PRESET_ID = 'askai-enterprise'

// 0.1.7-rc.2 train：web-app preset patch 里的 preset 条目行（`@deepseek-ai/dsh-agent-preset`
// 挂载，config.plugins 完整）须随 composition boot 传入 overlay，registry 从中
// register preset 定义（standard/ptc/minimal/code/cordis + ASKAI code）。ASKAI 的
// `askai-enterprise` preset 由 ASKAI preset root（config/agent-presets/askai-enterprise/*.yml）
// 通过 `agent-preset` 挂载行注册（下方 hostRows 里动态解析 preset.yml + agent.cordis.yml）。
// 0.1.7 的 web-app preset 目录不再直接捆绑 `code` preset（0.1.6 起 ASKAI 的 code preset
// 由 `api-compat.mjs` 的 resolveNativePreset fallback 承担：requested=code 未注册时
// 回退 standard）。因此此处只透传 web-app 已有的条目，不再伪造 code 条目。
// 旧 train（0.1.2–0.1.6）的 preset 由 roster 行（`dsh-agent-presets`）通过 roots 加载，
// 不需要这里。
async function hostRows({ askaiPresetRoot, shippedPresetRoot, storageDomainRoot, hostFeatures, isPresetRegistryTrain, webAppPatches, hostRoot }) {
  const rosterRows = isPresetRegistryTrain ? [] : [{
    id: 'agent-presets',
    name: '@deepseek-ai/dsh-agent-presets',
    config: {
      default: ASKAI_ENTERPRISE_PRESET_ID,
      includeShippedRoot: false,
      roots: [
        { path: resolve(askaiPresetRoot), trust: 'system' },
        { path: resolve(shippedPresetRoot), trust: 'system' },
      ],
      includeUserRoot: false,
    },
  }]
  // 0.1.7 train：registry 行提供 `agentPresets` service，config.default 由 ASKAI
  // 指定为 `askai-enterprise`（ASKAI 自有 preset）。web-app patch 的 registry 行
  // （default: standard）不重复注入。
  const registryRow = isPresetRegistryTrain
    ? [{
        id: 'agent-preset-registry',
        name: '@deepseek-ai/dsh-agent-preset-registry',
        config: { default: ASKAI_ENTERPRISE_PRESET_ID },
      }]
    : []
  // web-app patch 的 preset 条目行（standard/ptc/minimal/code/cordis）+ ASKAI 本地
  // yml 解析出的 `agent-preset` 行。registry 从这些行 register definitions。
  const presetEntryRows = isPresetRegistryTrain
    ? await extractPresetEntryRows(webAppPatches ?? [], askaiPresetRoot, hostRoot)
    : []
  return [
    ...rosterRows,
    ...registryRow,
    ...presetEntryRows,
    ...(hostFeatures.subagentModelSelection
      ? [{
          id: 'subagent-model-selection-settings',
          name: '@deepseek-ai/dsh-tool-subagent/model-selection-settings',
        }]
      : []),
    { id: 'storage', name: '@deepseek-ai/dsh-storage' },
    {
      id: 'storage-json',
      name: '@deepseek-ai/dsh-storage-json',
      config: { root: storageDomainRoot },
    },
    {
      id: 'storage-domain',
      name: '@deepseek-ai/dsh-storage-domain',
      config: { backend: 'json' },
    },
    { id: 'workspace', name: '@deepseek-ai/dsh-workspace' },
    { id: 'plugin-inventory', name: '@deepseek-ai/dsh-host-plugin-inventory' },
  ]
}

// 从 web-app patch 和 ASKAI 本地 yml 收集 preset 条目，展开为
// `@deepseek-ai/dsh-agent-preset` 挂载行。registry（`agent-preset-registry`
// 行）依赖这些条目填充 definitions。
async function extractPresetEntryRows(webAppPatches, askaiPresetRoot, hostRoot) {
  const { readdirSync, readFileSync, existsSync, statSync } = await import('node:fs')
  const { join } = await import('node:path')
  const { load: loadYaml } = await import('js-yaml')
  const rows = []
  // web-app patch 的 preset 条目行（`agent-preset` insert 行，config.plugins 完整）
  for (const patch of webAppPatches) {
    if (!Array.isArray(patch?.insert)) continue
    for (const entry of patch.insert) {
      if (entry?.name !== '@deepseek-ai/dsh-agent-preset') continue
      rows.push({
        id: entry.id,
        name: '@deepseek-ai/dsh-agent-preset',
        config: entry.config,
      })
    }
  }
  // ASKAI 本地 config/agent-presets/*.yml（askai-enterprise）
  // 0.1.7-rc.2 起 registry 不再扫描 preset roots，而是由 `agent-preset` 挂载行
  // 显式 register。ASKAI 本地 preset 的 plugin 行（agent.cordis.yml）里是相对
  // preset 目录的路径（如 `enterprise-preset-plugin.mjs`），须按 preset 目录解析
  // 为绝对路径，否则 registry train 下锚点错位导致 plugin 行 never started。
  if (existsSync(askaiPresetRoot)) {
    for (const dir of readdirSync(askaiPresetRoot)) {
      const presetDir = join(askaiPresetRoot, dir)
      try {
        if (!statSync(presetDir).isDirectory()) continue
      } catch { continue }
      const presetYml = join(presetDir, 'preset.yml')
      const agentYml = join(presetDir, 'agent.cordis.yml')
      if (!existsSync(presetYml)) continue
      const meta = loadYaml(readFileSync(presetYml, 'utf8'))
      const plugins = existsSync(agentYml) ? loadYaml(readFileSync(agentYml, 'utf8')) : []
      rows.push({
        id: `agent-preset-askai-${dir}`,
        name: '@deepseek-ai/dsh-agent-preset',
        config: {
          id: dir,
          name: meta?.name ?? dir,
          description: meta?.description ?? '',
          order: meta?.order ?? 99,
          plugins: anchorLocalPluginPaths(Array.isArray(plugins) ? plugins : [], presetDir, hostRoot),
        },
      })
    }
  }
  return rows
}

// 0.1.7-rc.2 train：ASKAI 本地 preset 的 plugin 行 `name` 若为相对路径
// （如 `../../../src/official-host/enterprise-preset-plugin.mjs`），须按
// preset 目录（config/agent-presets/<preset>/）解析为绝对路径。`..` 段
// 相对 preset 目录逐级上升，等价于 0.1.6 roster roots 的锚点行为。
// npm 包名（`@scope/pkg`）与内置组名（`cordis:`）原样保留。
// hostRoot 保留在签名上供未来 preset 目录迁移；当前锚点一律是 presetDir。
function anchorLocalPluginPaths(plugins, presetDir, hostRoot) {
  return plugins.map((row) => {
    if (typeof row?.name === 'string' && !row.name.startsWith('@') && !row.name.startsWith('cordis:')) {
      const resolved = resolve(presetDir, row.name)
      if (resolved !== row.name) {
        return { ...row, name: resolved }
      }
    }
    return row
  })
}

// 0.1.7-rc.2 train：web-app 的 `cordis.patch.yml` 用**顶层 `{ id, disabled: true }` 行**
// 把 host 平面的 per-agent 行关掉，改由各 preset 在其 scope 内挂载（官方注释：
// "Only the per-agent rows move behind presets"）。这些行必须原样透传给 loader，
// 否则 host 平面与 preset 会各挂一份同名插件：以 `tool-skill` 为例，两份实例会让
// `ctx.tools.get('skill', agent) === skillTool` 的身份判定失败，skill catalog 静默
// 不再注入模型请求（官方 `tool-skill` README 称之为 "scoped same-name shadow"）。
// 仅取顶层行：`insert` 内的 disabled 属于 web 客户端 UI 行，不参与 host 平面装配。
function disabledHostRows(webAppPatches) {
  const rows = new Map()
  for (const patch of webAppPatches ?? []) {
    for (const row of Array.isArray(patch) ? patch : [patch]) {
      if (typeof row?.id !== 'string' || row.id.length === 0) continue
      if (row.disabled === undefined) continue
      // 后出现的 patch 覆盖先出现的同 id 行，与 loader 的 patch 语义一致。
      rows.set(row.id, { id: row.id, disabled: row.disabled })
    }
  }
  return [...rows.values()]
}

export async function buildAskaiHostOverlay({
  storageRoot,
  askaiPresetRoot,
  shippedPresetRoot = askaiPresetRoot,
  webSearchProvider,
  occupiedIds = new Set(),
  hostFeatures = { subagentModelSelection: false },
  isPresetRegistryTrain = false,
  webAppPatches = [],
  hostRoot = undefined,
}) {
  const sessionRoot = resolve(storageRoot)
  const runtimeHome = resolve(storageRoot, 'dsh-home')
  const storageDomainRoot = resolve(storageRoot, 'host-storage')
  const rows = await hostRows({
    askaiPresetRoot,
    shippedPresetRoot,
    storageDomainRoot,
    hostFeatures,
    isPresetRegistryTrain,
    webAppPatches,
    hostRoot,
  })
  // 禁用行必须保持**顶层 patch 行**形状（`{ id, disabled }`）才能覆盖官方 bundle 的
  // 同名行；`planOverlayRows` 会把已存在的 id 降级为只带 config，故不经它处理。
  // ASKAI 自有禁用行优先，同 id 时覆盖 web-app 的行（Map 后写覆盖先写）。
  const disabledRows = new Map([
    ['hmr', { id: 'hmr', disabled: true }],
    // ASKAI owns the durable conversation title in its enterprise database.
    // Keep DSH's title service/API, but do not pay for a second first-prompt LLM
    // title that has no authoritative consumer in this deployment.
    ['session-title-llm', { id: 'session-title-llm', disabled: true }],
  ])
  // web-app patch 的 host 平面禁用行（tool-skill / skill-filesystem / tool-bash 等），
  // 原样透传以免与 preset 内同名插件重复挂载。
  for (const row of disabledHostRows(webAppPatches)) disabledRows.set(row.id, row)
  return [
    ...disabledRows.values(),
    {
      id: 'session-persistence-jsonl',
      config: { root: sessionRoot, compression: 'none' },
    },
    { id: 'settings', config: { dshHome: runtimeHome, watch: false } },
    { id: 'credentials', config: { dshHome: runtimeHome, watch: false } },
    { id: 'attachment-local', config: { dshHome: runtimeHome } },
    ...(webSearchProvider
      ? [{ id: 'web', config: { searchProvider: webSearchProvider } }]
      : []),
    ...planOverlayRows(rows, occupiedIds),
  ]
}
