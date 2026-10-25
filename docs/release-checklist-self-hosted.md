# MOGO 自托管企业部署发布检查单（024 T061 / FR-032 / FR-033）

本检查单覆盖**自托管企业部署**路径，聚焦两类差异：

1. **配置差异**：各环境（dev / staging / prod）的配置清单与取值差异。
2. **依赖差异**：镜像 digest、运行时版本、数据库/中间件版本。

格式强制两项字段 —— **执行人** 与 **结论**，机器可校验（`deploy/cli/checklist-verify.sh`）。
**空值视为未通过**（FR-033）。结论取值：`通过` / `不适用`（不适用必须附理由）。

- [ ] C01 | 三环境配置清单 `deploy/config/{dev,staging,prod}.yml` 均通过 `deploy/cli/config-lint.sh --env all`（210 条，codeRef 指向 `services/<svc>/app/core/config.py:<行号>`） | 执行人: | 结论: | 理由:
- [ ] C02 | prod 环境敏感键（`_SECRET/_PASSWORD/_KEY/_TOKEN` 后缀或含 `API_KEY/ACCESS_KEY_ID/PRIVATE_KEY`）`source` 均为 `deployment-secrets` 或 `vault`，无硬编码 | 执行人: | 结论: | 理由:
- [ ] C03 | 各环境 `.env` 与配置清单一致：必填键（`required: true`）在目标环境全部非空（`deploy/cli/startup-config-check.sh --env <env>` rc=0） | 执行人: | 结论: | 理由:
- [ ] C04 | 声明态与运行态一致（`deploy/cli/drift-check.sh --service <svc>`），read_only / cap_drop / 挂载 / 镜像无漂移 | 执行人: | 结论: | 理由:
- [ ] C05 | 镜像 digest 与发布记录一致（`deploy/cli/verify-artifact.sh`，依据 `deploy/releases/latest.json` 的 images 段） | 执行人: | 结论: | 理由:
- [ ] C06 | 镜像带 `org.mogo.version` / `org.mogo.git.sha` / `org.mogo.built.at` 标签且 `SHA256SUMS` 已签名（cosign verify-blob 通过） | 执行人: | 结论: | 理由:
- [ ] C07 | 运行时版本（Python / Node / 数据库 / Redis / Weaviate / Nginx）与 `docs/observability/rto-rpo.md` 与 compose 声明一致，记录实际版本号 | 执行人: | 结论: | 理由:
- [ ] C08 | 迁移门禁通过：`deploy/cli/migration-gate.sh --migration-max <N> --code-migration-base <M>`，M ≤ N（FR-029） | 执行人: | 结论: | 理由:
- [ ] C09 | 本次破坏性变更附迁移说明 `docs/migration-notes/<名称>.md`（模板 TEMPLATE.md，FR-030） | 执行人: | 结论: | 理由:
- [ ] C10 | 在线迁移不阻塞验证：`scripts/migrations/probe_throughput.py` 结论 PASS（吞吐下降 ≤ 20%，FR-031） | 执行人: | 结论: | 理由:
- [ ] C11 | 灰度档位推进记录完整（`deploy/canary/canary-plan.yml` 每档 checkpoints 满足），当前档位与 `deploy/canary/.canary-state.json` 一致 | 执行人: | 结论: | 理由:
- [ ] C12 | 自动回滚条件生效：`deploy/cli/auto-rollback.sh --dry-run` 无告警，回滚 T1 ≤ 300s 有实测记录（`deploy/runbook/rollbacks/`） | 执行人: | 结论: | 理由:
- [ ] C13 | 回滚后指标基线校验：`scripts/verify_rollback_baseline.py` 越界指标为 0（FR-026） | 执行人: | 结论: | 理由:
- [ ] C14 | 特性开关 `deploy/flags/flags.yml` 四项登记齐全、无到期、属主在职（`deploy/cli/flag-check.sh` rc=0） | 执行人: | 结论: | 理由:
- [ ] C15 | 发布计划 diff 已预审：`deploy/cli/deploy-dry-run.sh` 无破坏性变更（删除服务 / 镜像变更） | 执行人: | 结论: | 理由:
- [ ] C16 | IaC 变更日志完整：PR body 含「计划输出」「实际变更」「偏差原因」表（`.github/workflows/iac-gate.yml`） | 执行人: | 结论: | 理由:
- [ ] C17 | 备份前置：破坏性变更前已 `./mogo backup` 并记录备份时间 | 执行人: | 结论: | 理由:
- [ ] C18 | 值班与告警就位：`deploy/cli/*` 告警通道可达，值班人确认（FR-032 依赖差异项） | 执行人: | 结论: | 理由:

## 使用方式

- 发布前逐条填写 `执行人` 与 `结论`（`通过` / `不适用`+理由）。
- 跑 `deploy/cli/checklist-verify.sh` 校验：任一项执行人或结论为空 → exit 1（视为未通过）。
- 空结论视为未通过，不依赖人工判断。