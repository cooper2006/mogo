# MOVO Constitution
<!-- 项目：MOVO Community Edition — 基于 DeepSeek Harness (DSH) 的自托管企业级 Agent 平台 -->

## Core Principles

### I. Specification-First (NON-NEGOTIABLE)
所有新功能与架构变更必须先有规格（spec.md），后有实现。规格描述"做什么"与"为什么"，不写技术栈；计划（plan.md）承载实现细节。按 SDD 流程执行：/speckit-specify → /speckit-plan → /speckit-tasks → /speckit-implement → /speckit-converge；生产特性追加 /speckit-clarify、/speckit-checklist、/speckit-analyze 作为质量门禁。规格与实现收敛（converged）之前，不进入 PR 评审。

### II. Enterprise Production Readiness
MOVO 的定位是将 DSH Agent 带入企业生产环境。任何变更不得引入：不可观测的失败路径、未经验证的镜像发布、绕过审计的管理操作。容器镜像必须通过 CI 的构建与推送校验；回滚必须针对已发布的 DSH 运行时验证。发布遵循 docs/release-process.md 与 docs/open-source-productization/release-checklist.md。

### III. Security and Data Protection
用户输入必须校验；管理面（admin-api）操作必须可审计（system_audit）。密钥管理遵循 .env.example 约定，不允许将凭据提交进仓库。升级第三方依赖时必须评估已知 CVE（参考 commit 约定：fix: upgrade X to resolve critical CVE）。开源卫生由 scripts/check_open_source_hygiene.py 与 NOTICE/LICENSE 文件守护。

### IV. Cross-Platform and i18n
项目支持自托管（Linux/Docker）与 Windows 安装（docs/windows-installation.md）。用户界面变更必须保持中英文双语（README.md 与 README.zh-CN.md 同步维护；界面文案本地化）。

### V. Observability and Simplicity
结构化日志优先；镜像构建模式通过 scripts/check_compose_image_modes.sh 守护。遵循 YAGNI：不引入没有明确需求的架构复杂度。容器注册表镜像（如中国区 registry）策略变更需记录在 CHANGELOG.md。

## Technology Constraints
- 运行时基础：DeepSeek Harness (DSH)；平台由 DSH 负责 Agent 运行时，MOVO 负责部署、工作区、知识、身份权限、管理与治理。
- 前端：apps/admin-web、apps/user-web（pnpm 工作区，提交 lockfile 与 workspace 文件）。
- 后端：services/（admin-api、chat-api、document-parser），Python 生态。
- 交付：Docker Compose（docker-compose.yml / docker-compose.build.yml），入口脚本 movo。
- 规格工件存放于 .specify/ 与特性目录（specs/ 或特性编号目录），由 specify-cli 管理。

## Development Workflow
- 提交信息遵循 Conventional Commits 风格（feat:/fix:/docs:/ci:/chore:），与 CHANGELOG.md 对齐。
- 特性目录按编号顺序递增（001-xxx、002-xxx），活跃特性记录在 .specify/feature.json。
- 代码评审必须核对 constitution 合规性；复杂度需要时必须在规格或计划中论证。
- 既有代码采用 SDD 时遵循 existing-projects 指南：先为关键既有特性回溯补规格，再走标准 SDD 路径。

## Agent Operating Rules（代理操作规约，NON-NEGOTIABLE）
所有在本仓库内工作的编码代理（含 DSH Agent、Claude Code、Copilot 等）必须遵守：
- 默认使用简体中文回复；思考过程与反馈也用中文。
- 只允许操作当前项目文件夹（movo 工作区内），不越出工作区。
- 禁止删除任何文件；需要移除时移入"待确认清单"而非删除。
- 需要确认的操作（不可逆、影响面大、涉及远端仓库）先问用户，不擅自执行。
- 无法判断归属/用途的文件放入"待确认清单"（docs/pending-review/ 或等价位置），不要强行处理。
- 每次实际修改后更新 `docs/WORK_LOG.md`（日期 + 做了什么 + 改了哪些文件 + 验证方式）。
- 每轮只读取 `AGENTS.md`、`WORK_LOG.md` 最新状态和本轮相关文件，不重复扫描整个项目、不重复读无关文档。
- 只修改当前任务必要文件，不顺手重构、格式化、升级依赖或扩展功能。
- 已明确的低风险任务一次完成，减少重复确认与拆轮次。
- 测试只做本轮必要范围，未受影响模块不重复全量测试。
- 出错先定位原因，再做最小修改，不盲目重写。
- 远端仓库写入边界：只推送到 cooper2006/mogo（`mogo` remote）；origin（himovo/movo）push 已锁定为 no-push，任何对 origin 的写操作必须显式征得用户同意并临时解锁。

## Governance
本宪法优先于其他开发实践。修订宪法需要：记录理由、更新版本号、在 PR 中审批。每次修订更新 Last Amended 日期。规格质量由 /speckit-checklist 与 /speckit-analyze 守护。

### Amendment Log

- **1.1.1 (2026-09-24)** — 更新远端仓库写入边界。理由：`cooper2006/mogong` 已改名为 `cooper2006/mogo`，remote 名同步由 `mogong` 改为 `mogo`；旧地址由 GitHub 重定向。推送边界本身不变（仍不触碰 origin）。批准：仓库所有者指令。

**Version**: 1.1.1 | **Ratified**: 2026-07-08 | **Last Amended**: 2026-09-24
