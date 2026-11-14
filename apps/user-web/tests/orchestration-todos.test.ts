/**
 * 050 编排审批待办 —— API 契约单测（P0-2 接线，2026-11-12）。
 *
 * 覆盖点：
 * * 决策请求体形状：camelCase `nodeId`（后端 `DecisionPayload` 只有
 *   validation_alias、无 populate_by_name，snake_case 会被 422 拒绝）；
 * * 请求体不携带 userId/tenantId（后端 `_assert_end_user_scope` 对 body 里的
 *   身份字段做一致性校验，出现即 403 —— 身份只能来自 Bearer 会话）。
 *
 * 运行：`npm run test:orchestration-todos`（esbuild 打包后由 node 执行，仓库既有约定）。
 */
import assert from 'node:assert/strict'
import { buildDecisionPayload } from '../src/api/orchestrationRuns'

// ------------------------------------------------------------- decision body
{
  const payload = buildDecisionPayload('approve', '', 'node-1')
  assert.deepEqual(payload, { decision: 'approve', reason: '', nodeId: 'node-1' })
  console.log(' ok buildDecisionPayload(approve): camelCase nodeId, 空 reason 原样传递')

  const rejected = buildDecisionPayload('reject', '材料不全', 'approve-step')
  assert.deepEqual(rejected, { decision: 'reject', reason: '材料不全', nodeId: 'approve-step' })
  console.log(' ok buildDecisionPayload(reject): reason 与 nodeId 原样传递')
}

// ------------------------------------------------- no identity fields in body
{
  for (const decision of ['approve', 'reject'] as const) {
    const payload = buildDecisionPayload(decision, 'r', 'n')
    for (const forbidden of ['userId', 'user_id', 'tenantId', 'tenant_id']) {
      assert.ok(!(forbidden in payload), `请求体不得携带 ${forbidden}`)
    }
  }
  console.log(' ok 决策请求体不携带 userId/tenantId（身份来自 Bearer 会话）')
}

console.log('orchestration-todos.test.ts: all assertions passed')
