import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdir, readFile, writeFile } from 'node:fs/promises'

import { loadAssociatedAppBoot, resolveDshInstallation } from './installation.mjs'
import {
  ASKAI_DSH_HOST_OVERLAY_VERSION,
  buildAskaiHostOverlay,
} from './overlay.mjs'
import { collectInsertedEntryIds } from './overlay-planner.mjs'
import { extractOfficialPresetIsolation } from './preset-isolation.mjs'
import { readPluginInventory } from './inventory-compat.mjs'

const MODULE_DIR = dirname(fileURLToPath(import.meta.url))
const RUNTIME_HOST_ROOT = resolve(MODULE_DIR, '..', '..')
const ROOT_CONFIG = resolve(RUNTIME_HOST_ROOT, 'config', 'official-host-root.yml')
const ASKAI_PRESET_ROOT = resolve(RUNTIME_HOST_ROOT, 'config', 'agent-presets')

export class OfficialDshHostComposition {
  #ctx
  #inventory

  constructor({ storageRoot, webSearchProvider }) {
    this.storageRoot = resolve(storageRoot)
    this.webSearchProvider = webSearchProvider
  }

  async start() {
    if (this.#ctx !== undefined) throw new Error('official DSH Host composition is already started')
    const installation = await resolveDshInstallation()
    const appBoot = await loadAssociatedAppBoot(installation)
    const moduleHome = resolve(this.storageRoot, 'host-profile-home')
    const profileDir = resolve(moduleHome, 'profiles', 'askai-host')
    const profileRoot = resolve(profileDir, 'cordis.yml')
    await mkdir(profileDir, { recursive: true })
    await writeFile(profileRoot, await readFile(ROOT_CONFIG, 'utf8'))
    await healModuleFallback(appBoot, installation, moduleHome)
    const basePatches = appBoot.loadOverlayPatches('askai-dsh-host', installation.basePatchPath)
    // 0.1.7-rc.2 起 preset 隔离改由 dsh-web-app 的 `agent-preset-registry` roster +
    // `presets/*.patch.yml` 承载，旧的 `agent-presets` roster 行已移除，
    // 官方 preset-isolation 块不再适用；此时跳过提取，由 overlay 的 preset roots 生效。
    // 早期 train（0.1.2–0.1.6）仍走 webAppPatches 提取路径。
    const webAppPatchPaths = installation.webAppPatchPath
    const webAppPatches = webAppPatchPaths.map((patchPath) =>
      appBoot.loadOverlayPatches('askai-dsh-official-preset-isolation', patchPath),
    ).flat()
    const presetIsolation = extractOfficialPresetIsolation(webAppPatches)
    // 0.1.7-rc.2 train：preset 条目（standard/ptc/minimal/code/cordis）的
    // `agent-preset` insert 行在 web-app preset patch 里，registry 行在
    // web-app cordis.patch.yml 里。extractOfficialPresetIsolation 在 0.1.7
    // train 下返回空块（旧 agent-presets roster 行已移除），因此 overlay
    // 负责从 webAppPatches 提取 preset 条目行 + registry 行，注册进
    // agentPresets service。webAppPatches 全量透传给 overlay，overlay
    // 内部分类使用。
    const askaiOverlay = await buildAskaiHostOverlay({
      storageRoot: this.storageRoot,
      askaiPresetRoot: ASKAI_PRESET_ROOT,
      shippedPresetRoot: installation.shippedPresetRoot,
      webSearchProvider: this.webSearchProvider,
      occupiedIds: collectInsertedEntryIds(basePatches),
      hostFeatures: {
        subagentModelSelection: installation.canResolveDependency(
          '@deepseek-ai/dsh-tool-subagent/model-selection-settings',
        ),
      },
      isPresetRegistryTrain: installation.isPresetRegistryTrain,
      webAppPatches,
      hostRoot: RUNTIME_HOST_ROOT,
    })
    this.#ctx = await appBoot.boot(
      'askai-dsh-host',
      profileRoot,
      [...basePatches, ...presetIsolation.patches, ...askaiOverlay],
      undefined,
      installation.moduleBaseUrl,
    )
    this.installation = installation
    this.presetIsolation = presetIsolation
    const gateway = this.#ctx.get('pluginInventory')
    if (gateway === undefined) throw new Error('official DSH plugin inventory is unavailable')
    this.#inventory = await readPluginInventory(gateway)
    return this.#ctx
  }

  get ctx() {
    if (this.#ctx === undefined) throw new Error('official DSH Host composition is not started')
    return this.#ctx
  }

  inventory() {
    if (this.#inventory === undefined) throw new Error('official DSH plugin inventory is unavailable')
    return {
      overlayVersion: ASKAI_DSH_HOST_OVERLAY_VERSION,
      dshVersion: this.installation.version,
      presetIsolationRows: this.presetIsolation.disabledIds,
      ...this.#inventory,
    }
  }

  async dispose() {
    const ctx = this.#ctx
    this.#ctx = undefined
    this.#inventory = undefined
    if (ctx !== undefined) await ctx.fiber.dispose()
  }
}

async function healModuleFallback(appBoot, installation, moduleHome) {
  const heal = appBoot.healProfilesModuleFallback
  // 0.1.7-rc.2 起 dsh-app-boot 移除了 healProfilesModuleFallback 导出
  //（模块 fallback 由 boot 阶段的 bundle 装配内置处理）。无该 API 时跳过，不阻断启动。
  if (typeof heal !== 'function') {
    return
  }
  // DSH 0.1.2 moved module fallback healing to an asynchronous options
  // contract. Retain the positional call only for the approved rollback train.
  if (heal.constructor?.name === 'AsyncFunction') {
    await heal({ installAnchor: installation.dshManifestPath, home: moduleHome })
    return
  }
  await heal(installation.dshManifestPath, moduleHome)
}
