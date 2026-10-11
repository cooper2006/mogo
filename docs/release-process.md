# Release process

MOVO Community releases are immutable Git commits, Git tags and matching GHCR
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
4. On fresh amd64 and arm64 hosts, clone the tag, set `MOVO_VERSION` to that
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

