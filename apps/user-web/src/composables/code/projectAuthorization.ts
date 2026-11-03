import type { DesktopProject, SessionSummary } from '../../api/sessions'
import type { DshWorkspace } from '../../platform/types'

/** Local workspace presence is not authorization; MOGO employee ownership is. */
export function reconcileUserBoundProjects(
  projects: readonly DesktopProject[],
  localWorkspaces: readonly DshWorkspace[],
  sessions: readonly SessionSummary[],
  fallbackTitle: (workspaceId: string) => string,
  /** 桌面端才有「本地目录存在性」语义；Web 端项目为服务器项目，始终可用。 */
  localDshRuntime = false,
): DshWorkspace[] {
  const localById = new Map(localWorkspaces.map(workspace => [workspace.workspace_id, workspace]))
  const authorized = new Map<string, { title: string; updatedAt: string }>()

  for (const project of projects) {
    // 软删除（status=archived）的项目不再展示：删除后刷新不应重新出现。
    if (project.status === 'archived') continue
    // 后端默认项目（_id="default"）未持久化 workspace_id 字段，归一化为
    // DEFAULT_PROJECT_ID，与前端虚拟「默认工作区」合并，避免重复节点。
    const workspaceId = project.workspace_id || 'default'
    authorized.set(workspaceId, { title: project.title, updatedAt: project.updated_at })
  }
  for (const session of sessions) {
    const workspaceId = session.code_project?.workspace_id
    if (!workspaceId || authorized.has(workspaceId)) continue
    authorized.set(workspaceId, { title: fallbackTitle(workspaceId), updatedAt: session.updated_at })
  }

  return [...authorized.entries()].map(([workspaceId, binding]) => {
    const local = localById.get(workspaceId)
    if (local) return { ...local, title: binding.title || local.title }
    // Web 端项目为服务器项目（经浏览器目录选择器添加），无本地目录存在性
    // 校验，标记为可用；桌面端无本地目录匹配才标记 missing-dir（目录不可用）。
    return {
      workspace_id: workspaceId,
      title: binding.title || fallbackTitle(workspaceId),
      path: '', status: localDshRuntime ? ('missing-dir' as const) : ('ok' as const), session_ids: [],
      created_at: binding.updatedAt || '', updated_at: binding.updatedAt || '',
    }
  }).sort((left, right) => right.updated_at.localeCompare(left.updated_at))
}

export function availableUserProjects(workspaces: readonly DshWorkspace[]): DshWorkspace[] {
  return workspaces.filter(workspace => workspace.status === 'ok')
}

/** Reuses the isolation preference saved when the employee first added a project. */
export function boundProjectWorktree(projects: readonly DesktopProject[], workspaceId: string): boolean {
  return projects.find(project => project.workspace_id === workspaceId)?.worktree ?? false
}
