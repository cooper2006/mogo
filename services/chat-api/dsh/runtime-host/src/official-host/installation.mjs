import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { readFile, readdir } from 'node:fs/promises'

const requireFromHost = createRequire(import.meta.url)

async function readManifest(path) {
  return JSON.parse(await readFile(path, 'utf8'))
}

async function resolveShippedPresetRoot(candidates) {
  for (const candidate of candidates) {
    try {
      if ((await readdir(candidate)).length > 0) return candidate
    } catch (error) {
      if (error?.code !== 'ENOENT' && error?.code !== 'ENOTDIR') throw error
    }
  }
  throw new Error('the installed DSH release does not expose a shipped agent preset root')
}

export async function resolveDshInstallation() {
  const dshManifestPath = requireFromHost.resolve('@deepseek-ai/dsh/package.json')
  const dshPackageDir = dirname(dshManifestPath)
  const requireFromDsh = createRequire(dshManifestPath)
  const baseManifestPath = requireFromDsh.resolve('@deepseek-ai/dsh-base/package.json')
  const baseManifest = await readManifest(baseManifestPath)
  const basePatch = baseManifest?.dsh?.bundle?.patch
  if (typeof basePatch !== 'string' || !basePatch) {
    throw new Error('@deepseek-ai/dsh-base does not declare dsh.bundle.patch')
  }
  const webAppManifestPath = requireFromDsh.resolve('@deepseek-ai/dsh-web-app/package.json')
  const webAppManifest = await readManifest(webAppManifestPath)
  const webAppPatchField = webAppManifest?.dsh?.bundle?.patch
  // 0.1.7-rc.2 起 dsh-web-app 的 dsh.bundle.patch 是补丁清单（string[]）；
  // 早期 train 是单个字符串。两种形态都接受，逐项解析为绝对路径。
  const webAppPatchList = Array.isArray(webAppPatchField) ? webAppPatchField : [webAppPatchField]
  if (!webAppPatchList.length || webAppPatchList.some((item) => typeof item !== 'string' || !item)) {
    throw new Error('@deepseek-ai/dsh-web-app does not declare dsh.bundle.patch')
  }
  const webAppDir = dirname(webAppManifestPath)
  const webAppPatchPath = webAppPatchList.map((item) => join(webAppDir, item))
  const dshManifest = await readManifest(dshManifestPath)
  // 0.1.7-rc.2 将 `@deepseek-ai/dsh-agent-presets`（复数）更名为 `@deepseek-ai/dsh-agent-preset`（单数）；
  // 两种形态都接受，先试单数（新版）再试复数（旧版 train）。
  let presetManifestPath
  let presetPackageName = '@deepseek-ai/dsh-agent-presets'
  for (const candidate of [
    '@deepseek-ai/dsh-agent-preset/package.json',
    '@deepseek-ai/dsh-agent-presets/package.json',
  ]) {
    try {
      presetManifestPath = requireFromDsh.resolve(candidate)
      presetPackageName = candidate.includes('dsh-agent-preset/')
        ? '@deepseek-ai/dsh-agent-preset'
        : '@deepseek-ai/dsh-agent-presets'
      break
    } catch {
      presetManifestPath = undefined
    }
  }
  if (!presetManifestPath) {
    throw new Error('the installed DSH release does not ship an agent-preset package')
  }
  // 0.1.7-rc.2 train：preset 条目类（AgentPreset）由 `dsh-agent-preset` 包挂载，
  // `agentPresets` 服务由 `dsh-agent-preset-registry` 挂载（overlay 的 registry 行）；
  // ASKAI overlay 不再显式挂 roster 行（preset 条目由 DSH 上游 patch 管理）。
  // 旧 train（0.1.2–0.1.6）保留 roster 行挂载 `dsh-agent-presets` 包。
  const isPresetRegistryTrain = presetPackageName === '@deepseek-ai/dsh-agent-preset'
  if (isPresetRegistryTrain) {
    presetPackageName = '@deepseek-ai/dsh-agent-presets'
  }
  // 0.1.7-rc.2 起 preset 数据从 `dsh-agent-preset` 包移入 `dsh-web-app/presets/`；
  // 旧 train（0.1.2 起）preset 数据在 `dsh-agent-presets/presets/`，0.1.1 回滚 train 在 dsh 主包。
  const shippedPresetRoot = await resolveShippedPresetRoot([
    // 0.1.7 train: preset roster ships inside the web-app bundle.
    join(webAppDir, 'presets'),
    // 0.1.2 packages presets with the roster implementation.
    join(dirname(presetManifestPath), 'presets'),
    // The approved 0.1.1 rollback train packages them with the DSH launcher.
    join(dshPackageDir, 'config', 'agent-presets'),
  ])
  return Object.freeze({
    version: String(dshManifest.version),
    dshManifestPath,
    dshPackageDir,
    moduleBaseUrl: pathToFileURL(dshManifestPath).href,
    basePatchPath: join(dirname(baseManifestPath), basePatch),
    webAppPatchPath,
    shippedPresetRoot,
    presetPackageName,
    isPresetRegistryTrain,
    resolveDependency(specifier) {
      return requireFromDsh.resolve(specifier)
    },
    canResolveDependency(specifier) {
      try {
        requireFromDsh.resolve(specifier)
        return true
      } catch (error) {
        if (
          error?.code === 'ERR_PACKAGE_PATH_NOT_EXPORTED'
          || error?.code === 'MODULE_NOT_FOUND'
        ) return false
        throw error
      }
    },
  })
}

export async function loadAssociatedAppBoot(installation) {
  const entry = installation.resolveDependency('@deepseek-ai/dsh-app-boot')
  return import(pathToFileURL(entry).href)
}
