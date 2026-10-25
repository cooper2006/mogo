# Release process

MOGO Community releases are immutable Git commits, Git tags and matching GHCR
image tags. Do not publish a release while an item in
`docs/open-source-productization/release-checklist.md` remains unresolved.

## One-time GitHub setup

1. Create the public repository and push the reviewed history.
2. Enable branch protection for `main` and require the Runtime, Web, Community
   and DSH guards.
3. Enable Discussions and private vulnerability reporting.
4. Run the `Container Release` workflow manually once. This publishes only
   commit-SHA candidate tags and validates both `linux/amd64` and `linux/arm64`.
5. Set every `mogo-*` GHCR package to public visibility so Docker users can pull
   anonymously. Confirm each package is linked to the repository.

## Release candidate

1. Resolve the legal copyright owner, security contact and asset-distribution
   review recorded in the release checklist.
2. Update `CHANGELOG.md` and choose a semantic version such as `v0.1.0-rc.1`.
3. Run all required checks and the manual container workflow on the exact
   candidate commit.
4. On fresh amd64 and arm64 hosts, clone the tag, set `MOGO_VERSION` to that
   tag, run `./mogo up`, complete setup, and exercise chat, document parsing,
   knowledge retrieval and presentation generation.
5. Restore a backup into a disposable installation and exercise rollback to
   the previous image tag.
6. Create and push the signed tag only after those checks pass.

The tag workflow publishes seven image families, creates build provenance and
SBOM attestations, and rejects images with known fixable high or critical
vulnerabilities. Prerelease tags never update `latest`.

## Stable release

Publish GitHub release notes from the corresponding `CHANGELOG.md` entry. A
stable `vX.Y.Z` tag also updates `latest`, but production documentation and
support responses must continue recommending an explicit version tag.

If any image build, vulnerability scan or attestation fails, do not create a
GitHub Release. Fix the cause, create a new candidate commit and use a new tag;
never move or overwrite an existing public release tag.

## 依赖冻结期 (Dependency Freeze)

发布前 **7 天** 进入依赖冻结期（QF-908）：

1. **冻结范围**：`services/*/requirements.txt`、`apps/*/pnpm-lock.yaml`、
   `.github/dependabot.yml`、`services/*/pyproject.toml` 中的依赖声明。
2. **例外审批**：
   - P0 安全漏洞修复：需 security team 批准 + 单独 PR + 回滚方案。
   - 阻塞发布的构建问题：需 release manager 批准 + 记录在 release checklist。
   - 其余依赖变更延后到下一个发布周期。
3. **豁免清单**：
   - `services/document-parser` 的 docling 2.108.0 / rapidocr 3.8.4 钉死版本
     （因 ARM 镜像与模型兼容性，见 WORK_LOG 2026-10-11 记录）。
4. **检查时机**：
   - 冻结期开始：依赖变更 PR 自动打 `do-not-merge` 标签。
   - 冻结期结束：release checklist 中确认"依赖变更已清零"。
5. **Dependabot 节奏**：见 `.github/dependabot.yml`，默认 weekly；冻结期期间
   将 `open-pull-requests-limit` 临时设为 0。

## 一键安装验证 (FR-017, QF-024)

每次发布在干净机器上必须跑通下面的一键安装 + 最小可用性验证，结果记录在
release checklist 的"一键安装验证"行，未通过不得标记 Stable。

### 一键安装

```bash
# 1. 克隆并进入仓库
git clone <release-tag-url> mogo && cd mogo

# 2. 一次性安装（中文提示）
./mogo --lang zh-CN up
```

安装完成后按输出中的初始化地址打开用户端，完成首次管理员初始化。

### 最小可用性验证命令清单

```bash
# 3. 栈健康：三个数据服务应 Up (healthy)
./mogo status

# 4. 基线扫描：非 root / 只读 / 能力 / 体积四项无 FAIL
./mogo baseline

# 5. 配置清单 ↔ 代码读取点一致
./mogo config --env all

# 6. 运行态与 compose 声明无漂移
./mogo drift

# 7. 运行镜像与发布记录一致
./mogo verify

# 8. 预审部署计划 diff（应显示"无破坏性变更"）
./mogo deploy --dry-run
```

若第 6/7 项失败：镜像/容器不是本次发布产物，回退到上一致版本再跑。

### 判定标准

- `./mogo status` 中 `mongo` / `redis` / `weaviate` 均为 `Up (healthy)`；
- `./mogo baseline` 无 FAIL 项；
- `./mogo config` / `./mogo drift` / `./mogo verify` 均退出码 0；
- `./mogo deploy --dry-run` 无破坏性变更提示。

## 自托管企业部署路径 (024 T063 / FR-032, FR-033)

企业客户自托管部署走**独立发布检查单**，比社区路径额外校验配置差异与依赖差异：

- **检查单**：`docs/release-checklist-self-hosted.md`（18 项 C01-C18）。
- **校验脚本**：`deploy/cli/checklist-verify.sh` —— 每项必须有 `执行人` 与 `结论`
  （`通过` / `不适用`+理由），**空值视为未通过**，任一项缺失则阻塞发布（exit 1）。

### 配置差异（各环境）

- 三环境配置清单 `deploy/config/{dev,staging,prod}.yml` 必须先通过
  `deploy/cli/config-lint.sh --env all`（210 条，codeRef 精确到 `services/<svc>/app/core/config.py:<行号>`）。
- 目标环境必填键非空：`deploy/cli/startup-config-check.sh --env <dev|staging|prod>`。
- prod 敏感键 `source` 必须为 `deployment-secrets` 或 `vault`，无硬编码。
- 配置回滚：`./mogo config rollback <ref>`（先 lint 通过再 `mogo_compose up -d --pull never`）。

### 依赖差异（镜像 digest、运行时版本）

- 镜像与发布记录比对：`deploy/cli/verify-artifact.sh`（依据 `deploy/releases/latest.json`）。
- 镜像标签 `org.mogo.version` / `org.mogo.git.sha` / `org.mogo.built.at` 必须齐全，
  `SHA256SUMS` 已签名（cosign verify-blob）。
- 运行时版本（Python / Node / MongoDB / Redis / Weaviate / Nginx）在检查单 C07 记录实际版本号。
- 运行态与声明态一致：`deploy/cli/drift-check.sh`（read_only / cap_drop / 挂载 / 镜像）。

### 灰度与回滚

- 灰度档位推进：`./mogo canary start|promote|rollback|status`（`deploy/canary/canary-plan.yml`）。
- 自动回滚：`deploy/cli/auto-rollback.sh`（依据 `deploy/canary/rollback-conditions.yml`）。
- 回滚后基线校验：`scripts/verify_rollback_baseline.py`。

### 发布门禁（检查单 C08-C10）

- 迁移先于代码：`deploy/cli/migration-gate.sh`（FR-029）。
- 破坏性变更迁移说明：`docs/migration-notes/<名称>.md`（FR-030）。
- 在线迁移不阻塞：`scripts/migrations/probe_throughput.py`（FR-031）。

自托管企业发布必须逐条填写并跑 `deploy/cli/checklist-verify.sh`，全部 OK 才可 `./mogo up`。
