import { ref, type Ref } from 'vue'
import type { DesktopProject, SessionSummary } from '../../api/sessions'
import { listDesktopProjects, updateDesktopProjectStatus } from '../../api/sessions'
import { listDshWorkspaces } from '../../platform'
import type { DshWorkspace } from '../../platform/types'
import { reconcileUserBoundProjects } from './projectAuthorization'

interface UserBoundProjectOptions {
  authToken: Ref<string>
  canUseCode: Ref<boolean>
  localWorkspacePicker: boolean
  /** 桌面端才有「本地目录 ↔ 项目状态」的对账语义；Web 端项目为服务器项目。 */
  localDshRuntime: boolean
  identity: () => string
  sessions: Ref<SessionSummary[]>
  fallbackTitle: (workspaceId: string) => string
}

/** Owns the account boundary for desktop projects and rejects stale responses. */
export function useUserBoundProjects(options: UserBoundProjectOptions) {
  const bindings = ref<DesktopProject[]>([])
  const workspaces = ref<DshWorkspace[]>([])
  const titles = ref<Record<string, string>>({})
  const loading = ref(false)
  const loadedIdentity = ref('')
  let refreshEpoch = 0

  function clear(): void {
    refreshEpoch += 1
    loadedIdentity.value = ''
    bindings.value = []
    workspaces.value = []
    titles.value = {}
    loading.value = false
  }

  function add(binding: DesktopProject, workspace: DshWorkspace): void {
    bindings.value = [binding, ...bindings.value.filter(item => item.workspace_id !== binding.workspace_id)]
    workspaces.value = [workspace, ...workspaces.value.filter(item => item.workspace_id !== workspace.workspace_id)]
    titles.value = { ...titles.value, [workspace.workspace_id]: workspace.title }
  }

  /** 本地即时移除项目（软删除：服务端归档已由调用方 PATCH，此处仅清前端缓存）。 */
  function remove(workspaceId: string): void {
    if (!workspaceId) return
    bindings.value = bindings.value.filter(item => item.workspace_id !== workspaceId)
    workspaces.value = workspaces.value.filter(item => item.workspace_id !== workspaceId)
    if (workspaceId in titles.value) {
      const next = { ...titles.value }
      delete next[workspaceId]
      titles.value = next
    }
  }

  /** Local workspace dirs decide archive state: missing → archived, present → active. */
  function syncArchiveState(nextBindings: DesktopProject[], localWorkspaces: DshWorkspace[], token: string): void {
    const localIds = new Set(localWorkspaces.map(w => w.workspace_id))
    for (const project of nextBindings) {
      // 默认项目（_id = "default"）没有 workspace_id，且服务端禁止归档（046 Edge Case 3），
      // 跳过避免对空 id 发 PATCH → 重定向到 collection 根 → 405。
      if (!project.workspace_id) continue
      const nextStatus = localIds.has(project.workspace_id) ? 'active' : 'archived'
      if ((project.status || 'active') === nextStatus) continue
      updateDesktopProjectStatus(project.workspace_id, nextStatus, token).catch(() => {})
      project.status = nextStatus
    }
  }

  async function loadLocalWorkspaces(): Promise<DshWorkspace[]> {
    try { return await listDshWorkspaces() }
    catch { return [] } // Server-owned projects remain visible as unavailable on this device.
  }

  async function refresh(): Promise<void> {
    if (!options.canUseCode.value || !options.localWorkspacePicker) return
    const identity = options.identity()
    const token = options.authToken.value
    if (!identity || !token) return
    refreshEpoch += 1
    if (loadedIdentity.value !== identity) clear()
    const activeEpoch = refreshEpoch
    const isStale = () => activeEpoch !== refreshEpoch
      || identity !== options.identity()
      || token !== options.authToken.value
    loading.value = true
    try {
      const nextBindings = await listDesktopProjects(token)
      const localWorkspaces = await loadLocalWorkspaces()
      if (isStale()) return
      const nextWorkspaces = reconcileUserBoundProjects(
        nextBindings, localWorkspaces, options.sessions.value, options.fallbackTitle,
      )
      bindings.value = nextBindings
      workspaces.value = nextWorkspaces
      titles.value = Object.fromEntries(nextWorkspaces.map(workspace => [workspace.workspace_id, workspace.title]))
      loadedIdentity.value = identity
      // 046 FR-009: 对账后自动归档/恢复——目录不存在 → archived，恢复 → active。
      // 该语义只在桌面端成立（Web 端项目为服务器项目，localWorkspaces 恒为空，
      // 若据此归档会把所有项目误标 archived → 删除后刷新又出现）。
      if (options.localDshRuntime) syncArchiveState(nextBindings, localWorkspaces, token)
    } catch { /* Keep the last same-employee snapshot on a control-plane outage. */ }
    finally {
      if (activeEpoch === refreshEpoch) loading.value = false
    }
  }

  return { bindings, workspaces, titles, loading, identity: options.identity, clear, add, remove, refresh }
}
