import { basename, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdir, readFile, writeFile } from 'node:fs/promises'

import { loadAssociatedAppBoot, resolveDshInstallation } from './installation.mjs'
import {
  ASKAI_DSH_HOST_OVERLAY_VERSION,
  buildAskaiHostOverlay,
} from './overlay.mjs'
import { collectInsertedEntryIds } from './overlay-planner.mjs'
import { extractOfficialPresetIsolation } from './preset-isolation.mjs'
import { resolvePresetModules } from './preset-module-resolution.mjs'
import { readPluginInventory } from './inventory-compat.mjs'
import { prepareManagedProfile } from './managed-profile.mjs'
import { reconcileProfilePlugins } from './plugin-reconciler.mjs'
import { recoverWindowsStaleModuleLock } from './windows-stale-module-lock.mjs'
import { recoverWindowsEmptyModuleFallbacks } from './windows-empty-module-fallbacks.mjs'

const MODULE_DIR = dirname(fileURLToPath(import.meta.url))
const RUNTIME_HOST_ROOT = resolve(MODULE_DIR, '..', '..')
const ROOT_CONFIG = resolve(RUNTIME_HOST_ROOT, 'config', 'official-host-root.yml')
const ASKAI_PRESET_ROOT = resolve(RUNTIME_HOST_ROOT, 'config', 'agent-presets')

export class OfficialDshHostComposition {
  #ctx
  #inventory

  constructor({ storageRoot, webSearchProvider, plugins = [] }) {
    this.storageRoot = resolve(storageRoot)
    this.webSearchProvider = webSearchProvider
    this.plugins = plugins
  }

  async start() {
    if (this.#ctx !== undefined) throw new Error('official DSH Host composition is already started')
    await this.#boot()
    try {
      const unavailable = new Map()
      if (await reconcileProfilePlugins(this.#ctx.get('pluginManager'), this.plugins, {
        onUnavailable: (plugin, error) => unavailable.set(plugin.name, { name: plugin.name, reason: error.code }),
      })) {
        await this.dispose()
        await this.#boot()
      }
      this.unavailablePlugins = [...unavailable.values()]
      this.availablePlugins = this.plugins.filter(plugin => !unavailable.has(plugin.name))
      const active = new Map((await this.#ctx.get('pluginManager').listBundles())
        .map(item => [item.name, item]))
      for (const plugin of this.availablePlugins) {
        const item = active.get(plugin.name)
        if (!item?.enabled || item.version !== plugin.version || item.error) {
          throw new Error(`DSH plugin ${plugin.name} did not activate in this Runtime Profile`)
        }
        for (const row of item.rows ?? []) {
          const entry = this.#inventory.entries.find(candidate => candidate.entryId === row.entryId)
          if (!entry || (entry.enabled && entry.fiberPhase !== 'active')) {
            throw new Error(`DSH plugin ${plugin.name} row ${row.rowId} did not become active (${entry?.fiberPhase ?? 'missing'})`)
          }
        }
      }
      return this.#ctx
    } catch (error) {
      await this.dispose()
      throw error
    }
  }

  async #boot() {
    const installation = await resolveDshInstallation()
    const appBoot = await loadAssociatedAppBoot(installation)
    // Host 配置 profile 必须落在“能向上回溯到 node_modules”的目录（本地修复）：
    // 容器里 storageRoot 是独立数据卷（/data/dsh-runtime），其向上回溯目录没有
    // node_modules，会导致 preset 行 never started（ERR_MODULE_NOT_FOUND）。故
    // 放到运行时安装根目录；会话/工作区持久化仍用 storageRoot。用 storageRoot 的
    // basename 作子目录，保证同进程多实例（测试）互不覆盖。
    const moduleHome = resolve(RUNTIME_HOST_ROOT, 'host-profile-home', basename(this.storageRoot))
    await mkdir(moduleHome, { recursive: true })
    await recoverWindowsStaleModuleLock(moduleHome)
    await recoverWindowsEmptyModuleFallbacks(moduleHome)
    await healModuleFallback(appBoot, installation, moduleHome)
    const initialProfile = await prepareManagedProfile({
      appBoot, installation, moduleHome, overlays: [],
    })
    const basePatches = initialProfile.basePatches
    const webAppPatches = installation.webAppPatchPath.flatMap(path => appBoot.loadOverlayPatches(
      'askai-dsh-official-preset-isolation', path,
    ))
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
      declarativePresets: presetIsolation.declarative,
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
    const overlays = [...resolvePresetModules([...presetIsolation.patches, ...askaiOverlay], installation)]
    const managedProfile = await prepareManagedProfile({
      appBoot, installation, moduleHome, overlays,
    })
    await writeFile(managedProfile.root, await readFile(ROOT_CONFIG, 'utf8'))
    this.#ctx = await appBoot.boot(
      'askai-dsh-host',
      managedProfile.root,
      managedProfile.patches,
      async ctx => {
        ctx.provide('profileContext', managedProfile.context)
        await ctx.plugin(appBoot.PluginPackages, { resolution: managedProfile.resolution })
      },
      undefined,
    )
    this.installation = installation
    this.presetIsolation = presetIsolation
    const gateway = this.#ctx.get('pluginInventory')
    if (gateway === undefined) throw new Error('official DSH plugin inventory is unavailable')
    this.#inventory = await readPluginInventory(gateway)
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
