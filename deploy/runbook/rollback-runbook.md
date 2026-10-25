# 回滚 Runbook（024 T083）

本 runbook 覆盖两类回滚：**人工回滚**（值班人工执行）与**自动回滚**（`auto-rollback.sh` 按条件自动触发）。
两者共用同一份回滚记录 `deploy/runbook/rollbacks/<date>-<version>.md` 与同一基线校验
`scripts/verify_rollback_baseline.py`。

## 1. 何时回滚

- 灰度任一档位触发 `deploy/canary/rollback-conditions.yml` 任一 P0 条件（见 §3）。
- 发布后 P0 指标劣化超过基线容差（`scripts/verify_rollback_baseline.py`，默认 10%）。
- 数据变更未完成"扩展-收缩"的 Contract 阶段（见 `deploy/runbook/expand-contract.md`）。

## 2. 人工回滚步骤

1. **判断阶段**：是否处于 Contract 阶段（旧字段已删除）？
   - 是 → **先执行** `python3 scripts/migrations/<n>_<desc>.down.py --direction down`（回到迁移完成态），否则稳定版因读不到字段会失败。
   - 否 → 直接回滚（新旧结构并存，稳定版可读）。
2. **确认档位**：读取 `deploy/canary/.canary-state.json` 当前档位与版本。
3. **执行回滚**：
   ```bash
   ./mogo canary rollback --reason "<事件号或原因>" --yes
   ```
   - 会自动停掉 `*-canary` 容器、恢复 nginx 分流到 stable、写回滚记录。
4. **验证基线**：
   ```bash
   python3 scripts/verify_rollback_baseline.py --baseline-file <基线> --post-file <回滚后> --json
   ```
   任一指标越界（容差默认 10%）需继续排查，不得直接放行。
5. **业务校验**：若回滚涉及恢复备份，执行 `./mogo restore --verify` 或
   `python3 scripts/verify_restore_business.py --base-url <url> --json`。
6. **记录**：回滚记录已由 `canary.sh rollback` 自动写入
   `deploy/runbook/rollbacks/<日期>-<版本>.md`；人工补充 root cause 与后续 action。

## 3. 自动回滚触发说明

`deploy/cli/auto-rollback.sh` 每 60s 评估 `deploy/canary/rollback-conditions.yml` 的 5 条条件：

| 条件 | PromQL | 触发阈值 | 等级 |
| --- | --- | --- | --- |
| error_rate_delta | 错误率差 | > 基线 +2pct | P0 |
| p95_latency_delta | P95 延迟差 | > 基线 +20% | P0 |
| http_5xx_rate | 5xx 比例 | > 0.01 | P1 |
| timeout_rate | 超时比例 | > 0.02 | P1 |
| availability | 可用率 | < 0.99 | P0 |

触发行为（`--dry-run` 仅告警不动作）：
- 任一命中 → 调 `./mogo canary rollback --reason "auto:<条件id>" --yes`。
- 冷却 **10 分钟**（`cooldown_minutes`），同一窗口最多 2 次（`max_rollbacks_per_window`）。
- 触发时通过 `./mogo notify <severity> "<标题>"` 通知（log / webhook / alertmanager）。

## 4. 权限与决策

- **人工回滚**：SRE 值班可直接执行（见 `dr-plan.md` §2 决策链）。
- **自动回滚**：仅作用于灰度流量（canary），不自动回滚 stable；stable 回滚必须人工确认。
- 回滚后必须走 §2 步骤 4-6 验证，未验证不得进入下一轮发布。

## 5. 记录与审计

| 字段 | 来源 |
| --- | --- |
| 开始 / 结束时间、实测耗时 | `canary.sh rollback` 自动写入 |
| 触发原因、触发指标 | 人工 `--reason` 或 `auto:<条件id>` |
| 基线比对结果 | `scripts/verify_rollback_baseline.py` 输出 |

## 6. 版本与更新

- 版本：v1
- 更新日期：2026-10-26
- 关联：`deploy/canary/rollback-conditions.yml`、`deploy/cli/auto-rollback.sh`、`deploy/runbook/data-rollback-matrix.md`、`deploy/runbook/expand-contract.md`。