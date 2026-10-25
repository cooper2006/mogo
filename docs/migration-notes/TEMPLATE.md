# 破坏性变更迁移说明（模板）

> 024 T060（FR-030）。**每次破坏性变更 MUST 附一份迁移说明**（本模板），随 PR 提交，
> 并纳入发布检查单（`docs/release-checklist-self-hosted.md` 的「迁移与兼容性」段）。
> 覆盖历史 QualityForge 项 QF-021（blocked）。

## 变更概要

- **变更标题**：<一句话说明破坏性变更内容>
- **PR / Issue**：<链接>
- **影响服务**：admin-api / chat-api / document-api / mongo / redis / weaviate（多选）
- **变更类型**：改字段类型 / 删字段 / 改枚举 / 改索引 / 改唯一约束 / 改 collection schema / 其他
- **风险等级**：低 / 中 / 高（参照 `deploy/runbook/data-rollback-matrix.md`）

## 兼容性分析

| 项 | 说明 |
| --- | --- |
| 旧版本（vN）能否继续读写 | 能 / 不能（不能则阻塞发布，需双写窗口） |
| 迁移阶段（expand / migrate / contract） | 见 `deploy/runbook/expand-contract.md` |
| 是否需要双写窗口 | 是（窗口时长）/ 否 |
| 是否破坏性（不可逆） | 是（需备份 + 前向修复脚本）/ 否 |

## 迁移步骤

1. **前置**：`./mogo backup`，记录备份时间；确认低峰期窗口（默认 02:00-05:00 本地时区）。
2. **迁移脚本**：`scripts/migrations/<序号>_<描述>.py`（up），成对提供 `<序号>_<描述>.down.py`（down）。
3. **执行**：在 `scripts/migrations/` 下跑 `--direction up`；幂等可重跑；长事务按 README 拆分。
4. **验证**：`scripts/migrations/probe_throughput.py` 确认迁移未阻塞线上（吞吐下降 ≤ 20%）。
5. **门禁**：`deploy/cli/migration-gate.sh --migration-max <N> --code-migration-base <M>`，M ≤ N 才允许代码发布。

## 回滚路径

- **阶段**：expand / migrate / contract（见回滚决策树）。
- **动作**：跑 `<序号>_<描述>.down.py` → `./mogo canary rollback`。
- **未完成收缩禁止回滚**：若已进入 contract 阶段，必须先用 down 回到 migrate 完成态再回滚。

## 数据验证

- 迁移后抽样校验字段可用、数值正确；对比迁移前后关键指标（`scripts/verify_rollback_baseline.py`）。

## 执行人 / 结论

- **执行人**：<名字>
- **结论**：通过 / 不适用（附理由）
