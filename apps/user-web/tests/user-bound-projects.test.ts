import assert from 'node:assert/strict'
import { availableUserProjects, boundProjectWorktree, reconcileUserBoundProjects } from '../src/composables/code/projectAuthorization'

const local = [
  { workspace_id: 'employee-project', title: 'Employee', path: '/employee', status: 'ok', session_ids: [], created_at: '1', updated_at: '3' },
  { workspace_id: 'other-user-project', title: 'Other user', path: '/other', status: 'ok', session_ids: [], created_at: '1', updated_at: '4' },
] as const

const bound = reconcileUserBoundProjects([
  { workspace_id: 'employee-project', title: 'My project', worktree: false, created_at: '1', updated_at: '3' },
], local, [], id => `Project ${id}`)
assert.deepEqual(bound.map(item => item.workspace_id), ['employee-project'])
assert.equal(bound[0].title, 'My project')
assert.equal(bound[0].path, '/employee')

const none = reconcileUserBoundProjects([], local, [], id => `Project ${id}`)
assert.deepEqual(none, [], 'a device-local Workspace alone must never become visible')

const legacyConversation = reconcileUserBoundProjects([], local, [{
  id: 'conversation', user_id: 'employee', title: 'Code', created_at: '1', updated_at: '5', message_count: 1,
  code_project: { workspace_id: 'employee-project', git_branch: 'main', worktree: false },
}], id => `Project ${id}`)
assert.deepEqual(legacyConversation.map(item => item.workspace_id), ['employee-project'])

const unavailable = reconcileUserBoundProjects([
  { workspace_id: 'remote-binding', title: 'Laptop project', worktree: true, created_at: '1', updated_at: '6' },
], local, [], id => `Project ${id}`, true) // 桌面端：无本地目录匹配 → 目录不可用
assert.equal(unavailable[0].status, 'missing-dir')
assert.equal(unavailable[0].path, '')
assert.deepEqual(availableUserProjects(unavailable), [])

// Web 端（默认 localDshRuntime=false）：服务器项目无本地目录存在性校验，标记可用。
const webAvailable = reconcileUserBoundProjects([
  { workspace_id: 'web-project', title: 'Web project', worktree: false, created_at: '1', updated_at: '7' },
], [], [], id => `Project ${id}`)
assert.equal(webAvailable[0].status, 'ok')
assert.deepEqual(availableUserProjects(webAvailable).map(item => item.workspace_id), ['web-project'])

assert.equal(boundProjectWorktree([
  { workspace_id: 'employee-project', title: 'My project', worktree: true, created_at: '1', updated_at: '3' },
], 'employee-project'), true, 'selecting an existing project must restore its saved worktree preference')
assert.equal(boundProjectWorktree([], 'employee-project'), false)

console.log('user-bound project reconciliation tests passed')
