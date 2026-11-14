# 特性开关属主转移流程（024 T055 / FR-028）

当某个 `deploy/flags/flags.yml` 登记的开关**属主离职或调岗**时，必须在发布前完成属主转移。
CI 检查（`deploy/cli/flag-check.sh` 的属主存活性扩展 + 发布检查单）在属主账号已注销时会**阻塞发布**。

## 触发条件

- 属主账号已注销 / 已停用（离职、账号过期）。
- 属主长期无响应（连续 ≥ 14 天未回复值班 @ 提及）。
- 属主书面申请转移（因组织架构调整）。

## 转移步骤（MUST 在发布前完成）

1. **确认新属主**：由 `platform-oncall` 指定接管人，写入 flags.yml 的 `owner` 字段。
2. **交接上下文**：新属主必须阅读该 flag 的 `cleanupPlan` 与 `codeRefs`，
   确认 `expiry` 与清理计划仍然成立；不成立则先更新 `expiry` / `cleanupPlan`。
3. **登记变更**：修改 `deploy/flags/flags.yml` 的 `owner`，随 PR 提交；PR 描述里写
   「属主转移：<旧> → <新>，原因：<离职/调岗/长期无响应>」。
4. **跑校验**：`deploy/cli/flag-check.sh`，确认四项登记齐全、无到期告警。
5. **CI 检查**：发布流水线在 `flag-check` 步骤失败即阻塞发布。
   若新属主账号不存在/未激活，`flag-check.sh` 输出 `FAIL <flag>: owner <name> 未注册` 并 exit 1。

## CI 属主存活性检查约定

`deploy/cli/flag-check.sh` 增加属主存活性检查时，按下列约定实现（供流水线引用）：

- 属主白名单来自 `deploy/flags/owners.yml`（登记 owner id / 别名 / 状态 active|departed）。
- `owner` 状态为 `departed` 或不在白名单 → 视为属主已注销 → **阻塞发布**（exit 1）。
- 属主转移必须在 PR 中一并更新 `owners.yml`（新属主状态 `active`，旧属主标记 `departed`）。

> 说明：本轮 T055 建立流程与约定；属主存活性检查的具体实现随 `deploy/flags/owners.yml`
> 引入后落地到 `flag-check.sh`（见 T053 的扩展点）。

## 检查单条目（纳入 docs/release-checklist-self-hosted.md）

| 检查项 | 结论 | 说明 |
| --- | --- | --- |
| 所有 flags 属主均为在职且未注销账号 | 通过 / 不适用 | `flag-check.sh` 校验；属主注销则阻塞发布 |
| 到期开关已有清理计划或已更新 expiry | 通过 | 到期未清理须在本次发布前解决 |
| 属主转移 PR 已同步更新 owners.yml | 通过 / 不适用 | 无转移则填不适用并附理由 |

## 记录

每次属主转移在 `deploy/flags/owners.yml` 的变更历史里追加一条 `transfers` 记录
（from / to / date / reason / pr），随 PR 合入主分支。