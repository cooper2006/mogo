# Changelog

All notable MOVO Community Edition changes are recorded here. Releases use
semantic version tags and the same tag is applied to every published container
image.

## Unreleased

### Added

- **021 unified context address space — production entry**：
  `POST /api/context/resolve` 与 `GET /api/context/trace/{id}` 暴露 `mogo://`
  地址空间（memory / resource / skill / session 四根）。此前 router 与四个
  tenant 适配器仅被测试引用，生产不可达。
- **009 hook 事件派发**（`app/dsh_runtime/hooks/dispatcher.py`）：`subscribe` /
  `dispatch` / `dispatch_session_end` 等，闭合 `emit_*` 产出却无人消费的断链；
  订阅者异常隔离，不影响调用方。
- **002 会话结束语义**：`SessionPersistenceService.end_session()` +
  `POST /api/sessions/{id}/end` + `chat_sessions.ended_at` / `end_reason` 字段。
  会话结束时触发 009 `SessionEnd` → 017 分层记忆沉淀（幂等，账本去重）。
- **017 契约文档** `contracts/memory-context-contract.md`：两条正交轴、地址语法、
  可见性委托矩阵、HTTP 契约与沉淀接线图。
- **Python 3.13 运行时升级 + 依赖哈希锁定（供应链完整性）**：`chat-api` 与
  `admin-api` 的基础镜像升级到 `python:3.13-slim-bookworm`；两者的
  `requirements.txt` 全量锁定 sha256（chat-api **2773** 条 / admin-api **1063** 条），
  安装改为 `pip install --require-hashes` —— 依赖树任何一环被替换都会构建失败。
  新增 `scripts/generate-hashes.sh` 生成与刷新哈希（走清华源，实测 >5min → ~3min）。
  **`document-parser` 保持 `python:3.10-slim-bookworm`**：Docling 钉死
  `numpy==1.26.4`，无 3.13 轮子，故不随迁；该服务的 `requirements.txt` 亦不做
  哈希锁定（同样受 Docling 约束）。
- **生产离线发布链路** `deploy/production/`：面向无外网 / 内网 Portainer 的交付。
  `prepare-release.sh` 九步流水线 —— 确定版本号（默认取 `git rev-parse --short HEAD`）
  → 前置检查 → 固定 compose 变量 → 收集镜像清单 → 交叉构建 amd64 应用镜像 →
  校验应用镜像 → 生成基础镜像 amd64 变体 → 打包 → 渲染清单 / 校验 / 出部署单。
  产出 `01-base.tar`、`02-app-small.tar`、`03-chat-api.tar`、`04-document-parser.tar`
  （大镜像单独成包，网页上传可单独重传），外加已渲染的
  `docker-compose.portainer.yml`、自包含的 `DEPLOY.md`（含实测体积与 sha256）与
  `bundle.json`。配套 `verify_bundle.py` 校验三条硬约束：每条 manifest 条目的
  `RepoTags` 与预期完全一致、config 的 `architecture/os` 为 `amd64/linux`、
  `len(Layers) == len(rootfs.diff_ids)`（经典 `docker load` 的硬性前提）；
  `render_deploy_doc.py` 生成部署单。
- **跨架构基础镜像导出** `scripts/export_base_images.sh`：`save --platform linux/amd64`
  借助 Docker 28+ 的 `docker save --platform`，可在 Apple Silicon 上产出 amd64
  归档。**load 侧默认拒绝跨平台归档**，须显式加 `--allow-platform-mismatch` ——
  单平台归档会**替换**同 tag 的多平台清单，误 load 会把本机镜像降级为单架构。
  另有 `--mirror`（解析 Docker Hub 走镜像站）与 `--manifest-only`（只出清单不导出）。
- **备份 / 恢复 / 回滚演练脚本** `scripts/test_backup_restore_rollback.sh`：
  把"备份 → 恢复 → 回滚"作为可重复执行的验证，而不是一次性手工步骤。

### Fixed

- **CI 测试门禁必红（P0）**：`pytest-asyncio` 在 strict 模式下拒绝执行裸
  `async def` 测试，而 `services/chat-api/pyproject.toml` 与 Quality Gate
  都没有设置 `asyncio_mode`。此前"本机全绿"依赖临时传入 `-o asyncio_mode=auto`；
  还原为仓库真实配置后全量 **43 failed / exit=1**。现已在 `pyproject.toml`
  写入 `asyncio_mode = "auto"`，并把 `pytest-asyncio` / `pytest-timeout`
  显式声明进 dev 依赖。
- **021 地址层越权：URI 被当成凭证（P0）**：`check_memory_visibility` 从 URI
  的 `scope` / `owner_id` 段**构造**判定对象，导致 `u2` 可用
  `mogo://memory/org/u1/m-1/L2` 读到 `u1` 的私密内容。现改为接收**真实存储
  记录**，缺失即 fail closed；`session` 适配器同步补 `user_id` 查询条件
  （此前同租户任一成员可读他人会话，含 L2 逐字稿）。
- **`707c8ea` 机械 sweep 引入的系统性回归（P1）**：该提交为 165 个文件批量
  改写 `except` 块，引入四类缺陷，已全部恢复并归零：
  - **8 处 try 体真实语句被删**（`yield _sse(...)`、`return {"healthy": ...}`、
    `return EffectContract(...)`、`parser.close()`、`raw = resp.json()`、
    `package = validate_skill_package(archive)` 等）；
  - **23 处 except 回退值被删** —— 16 处导致 `UnboundLocalError`
    （含安全函数 `utils/ssrf_guard.py`）、6 处破坏 `-> bool/int/str/List`
    返回契约、1 处 `ping_loop` 失去早退；
  - **6 处重复 `except` 子句**（后者不可达，新加的日志永不执行；其中
    `content/evaluation/streaming.py` 使 SSE 流异常时永久挂起）；
  - **18 个文件调用未导入的 `log_print`** —— 异常分支自身抛 `NameError`。
- **021 检索轨迹无租户隔离（P1）**：`_TRACE_RING` 现按 `tenant_id` 分键，
  跨租户读取返回 404。
- **`POST /memory` 允许任意角色写 org 作用域（P1，017 FR-4）**：非
  `ORG_PROMOTION_ROLES` 角色写入 org 作用域现返回 403。
- **记忆 `HARD_MAX` 按字符而非字节计量（P1，017 FR-16）**：中文内容实际占用
  3 倍字节，上限可被穿透；改为按 UTF-8 字节计算。
- **`MEMORY_SUMMARY_REFRESH_DAYS` 为死配置（P1）**：该环境变量从不被读取，
  刷新周期硬编码 30 天；现由 `_configured_refresh_days()` 统一解析。
- **`orchestration/store.py` 落库主键为空 + 未导入 `load_orchestration_document`（P1）**：
  `_document_shape` 读的是 `loaded.definition.id`（真实字段为 `orchestration_id`）。
- **`revoke_share` 引用未定义变量（P1）**：`main_id, _ = await _authorize(...)`
  丢弃 `user_id` 后仍引用它，端点必 500。
- **`memory/address.py` 未拒绝超长 URI（P2）**：段数 > 4 现抛 `ValueError`。
- **017 记忆永不落库（P0）**：`MemoryStore.save` 对 motor 的 `replace_one` 未
  `await`，协程创建即丢弃，API 返回成功但记录不存在。`save` 改为 `async`，
  调用链（memory 端点 ×2、sediment ×2、sessions ×1）同步补 `await`。
- **009→017 闭环语义**（P1）：会话沉淀此前只挂在 `delete_session`，导致会话
  正常结束不沉淀。现由 `end_session` 驱动，`delete_session` 降级为去重兜底。
- **021 KG 单节点读取**（P1）：`resource/kg` 适配器此前调用私有
  `_ensure_loaded()`，为读一个节点拉取租户全图（最多 2000 节点 + 5000 边）。
  新增公开 `TenantKgStore.get_node_direct()`。
- **版本一致性**：manifest 版本此前与 CHANGELOG 声明不一致
  （chat-api/admin-api/admin-web 为 0.1.0、user-web 为 0.0.0，CHANGELOG 为
  0.2.0）。已统一为 0.2.0，并在 Quality Gate 新增 `version-consistency` job
  阻断此类漂移。
- **全仓非静默宽泛 `except Exception` 补日志（R4）**：改用 AST 安全改写器
  （只增不删 / 不遮蔽变量 / 保留尾注释 / 排除异常已传播 / 绝不碰 `log_print`
  定义模块），落盘 **95 文件 · 209 条 `log_print` · 66 个 import · 147 行
  `except` 补 `as exc` 绑定**，**非-except 删除行 = 0**。显式排除 73 处异常已
  传播（`raise` / re-raise helper）与 38 处有意 `pass`（吞取消异常的关停惯用法、
  链式尝试的预期失败、以及日志基础设施自身 `emit()` / `_log_stage()`）。
  与 `707c8ea` 的 165 文件正则 sweep 形成对照：后者一次引入 4 类缺陷。

### Changed

- **CI 质量门禁扩为五 job**（`.github/workflows/quality-gate.yml`）：
  `version-consistency`（manifest 版本与 CHANGELOG 声明一致）、`frontend-quality`、
  `backend-quality`、`dsh-host-e2e`、`security-quality`。
- **`backend-quality` 内置两道针对"单测全绿但生产零引用"的特殊门禁**：
  - `services/chat-api/scripts/check_production_wiring.py` —— 校验新增子系统的
    生产接线（router / 消费方）确实存在，拦住"只有测试在引用"的假落地；
  - `services/chat-api/scripts/check_module_coverage.py` —— 对新增子系统设
    **模块级覆盖率下限**：021 `context_space` 85%、017 `memory` 80%、
    009 `dsh_runtime/hooks` 75%。仓级 `fail_under = 55` 对大型遗留代码是合理的
    粗门禁，但对新子系统要么形同虚设、要么被遗留代码拖累，故单独设限。
- 017 文档补齐密度轴用法与地址契约：`specs/017-three-scope-memory/quickstart.md`。

## v0.2.0 - 2026-10-03

### Added

- Platform multi-tenancy (spec 020): a platform super-admin console for tenant
  lifecycle management (create / list / rename / enable / disable / reset
  password / archive / restore / purge), a `tenants` registry collection, tenant
  isolation guards, soft-archive semantics, and staged purge of MongoDB records,
  vectors and files with a one-month tombstone.
- Quota "unlimited" now propagates as a flag (`unlimited` / `points_unlimited`),
  with `remainingPoints: -1` meaning "no limit"; clients must not do arithmetic
  on `-1`.

### Upgrade notes (required reading)

- **Published container images were renamed: the `movo-` prefix is gone.**
  `ghcr.io/himovo/movo-chat-api` is now `ghcr.io/himovo/chat-api`, and likewise
  for `movo-admin-api`, `movo-admin-web`, `movo-user-web`, `movo-gateway` and
  `movo-dsh-runtime-host` (all 7 images, including `movo-document-parser`). The
  images are named `<registry>/<service>`; a local source build still uses the
  bare `service:tag` form (`chat-api:latest`) so local images never collide with
  the published ones. If your deployment pins the old names in a compose file,
  a Kubernetes manifest or a pull script, **update it to the new names before
  upgrading** — otherwise the pull fails, or an unchanged image reference keeps
  you on the old release while everything else moves ahead.
  The related `MOVO_IMAGE_PREFIX` environment variable is **no longer
  supported**: its old meaning was a name prefix (`${MOVO_IMAGE_PREFIX}-chat-api`
  → `ghcr.io/himovo/movo-chat-api`), which the new `<registry>/<service>` naming
  cannot express. It is ignored with a warning and the default registry is used,
  rather than building a non-existent path such as
  `ghcr.io/himovo/movo/chat-api`. Replace it with `MOVO_IMAGE_REGISTRY`
  (e.g. `ghcr.io/himovo`), or set the per-service `MOVO_*_IMAGE` variables
  directly.
- **Set `ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD` before the first start after
  upgrading.** A deployment that already completed the setup wizard will not see
  the wizard again, so this environment variable is the only way to provision the
  platform super-admin — without it the platform console is unreachable.
  `ASKAI_ADMIN_PLATFORM_ADMIN_USERNAME` and
  `ASKAI_ADMIN_PLATFORM_ADMIN_DISPLAY_NAME` are optional (defaults: `admin` /
  `平台超级管理员`).
- Existing tenants are backfilled into the new `tenants` collection on startup
  (idempotent, reserved identifiers skipped); no data migration is needed.
- **MongoDB database name changed from `gragentic` to `mogo_dev`.** This is a
  rename, not a copy: an existing deployment that keeps the old database name
  will appear to have lost all data, because the services connect to a fresh,
  empty `mogo_dev`. There is **no automatic migration**. Choose one:
  - keep existing data — set `ASKAI_ADMIN_MONGODB_DB` (admin-api), `MONGODB_DB`
    (chat-api) and `MOVO_DOC_PROCESSING_MONGODB_DB` (document-parser) back to
    `gragentic`; or
  - adopt the new name — before starting the upgraded stack, migrate the data,
    e.g. `mongodump --db gragentic` then `mongorestore --nsFrom 'gragentic.*'
    --nsTo 'mogo_dev.*'`, or rename each collection with
    `db.adminCommand({renameCollection: "gragentic.<c>", to: "mogo_dev.<c>"})`.
  Both `docker-compose.yml` and `prod-images-caf21d4/docker-compose.portainer.yml`
  already default to `mogo_dev`.
- `ASKAI_ADMIN_BOOTSTRAP_ADMIN_*` was renamed to
  `ASKAI_ADMIN_TENANT_BOOTSTRAP_ADMIN_*` — update your environment files.

## v0.1.15 - 2026-09-16

### Added

- Add configurable image-generation request and response mappings for OpenAI-compatible
  and custom image model endpoints.

### Changed

- Upgrade the embedded DeepSeek Harness runtime to `0.1.6-alpha.1` and refresh its
  compatibility adapters, supply-chain evidence, and regression coverage.
- Improve desktop and Web Code-session recovery, workspace selection, and execution
  activity presentation.

### Fixed

- Implement the MCP Streamable HTTP initialization and session lifecycle while
  retaining compatibility with legacy MCP HTTP endpoints.
- Send image-model options only when explicitly configured and parse configurable
  JSON response paths without assuming one provider-specific payload shape.
- Refresh Skill feedback state when new feedback notifications arrive without
  interrupting the current page with a loading state.
- Copy Skill sharing links in desktop WebViews that expose the Clipboard API
  but deny direct clipboard writes.

## v0.1.14 - 2026-09-15

### Fixed

- Avoid rebuilding unchanged container images when only the release workflow or
  release planner changes; full rebuilds now require an explicit operator request.
- Apply available Debian security updates to runtime images before publishing.
- Build and scan immutable candidate images before promoting a release to its
  version and `latest` tags, and use the last successful container release as
  the incremental-build baseline.

## v0.1.13 - 2026-09-15

### Added

- Complete the Skill distribution lifecycle with publishing, direct sharing,
  update discovery, feedback, and organization-level management.
- Support installing external Skills from ZIP packages and show their source,
  version, update status, and local modifications in the Web workspace.
- Add clearer Windows installation guidance for Docker Desktop, WSL 2, Ubuntu,
  and common WSL environment mistakes.

### Changed

- Use the official GHCR images by default so both `./mogo up` and native
  `docker compose up -d` work without an `.env` file.
- Pull container images sequentially and keep retrying interrupted downloads
  until they succeed or the user stops the launcher.
- Improve the English and Chinese README onboarding, quick start, capability
  boundaries, and community feedback entry points.

### Fixed

- Allow users to switch models between turns in the same conversation while
  preserving the selected model when conversation history is reopened.
- Correct packaged Skill editing actions and labels so imported Skills are not
  presented as unpublished authoring drafts.
- Improve Skill list and detail UI state handling, including safe rendering of
  optional feedback data and clearer local-change indicators.

## v0.1.5 - 2026-09-05

### Security

- Upgrade the Community Web runtime base image to the current minimal
  Nginx/Alpine release to remove fixable high-severity OS vulnerabilities.

## v0.1.4 - 2026-09-05

### Added

- Add durable DSH turn recovery and idempotent terminal-state finalization.
- Preserve evidence from manually recorded browser events to improve workflow
  portability and target matching.

### Changed

- Make chat cancellation wait for authoritative backend acknowledgement before
  releasing the active UI state.
- Improve stream startup, interrupted-turn handling and browser recording review.

## v0.1.1 - 2026-09-04

### Added

- Add configurable Python package, PyTorch and Hugging Face mirrors for source builds.
- Support externally provisioned Docling models and preserve reusable document-build caches.
- Add MOVO Desktop service-address and update controls to the Community Web workspace.
- Add selective promotion of validated container candidates.

### Changed

- Improve document-model download reliability and timeout handling.
- Expand the English and Chinese product documentation, including MOVO positioning,
  Desktop capability boundaries and official website links.

### Security

- Upgrade vulnerable DSH Runtime Host dependencies and republish the affected images.

## v0.1.0 - 2026-09-02

- Prepare the independent Community Edition repository.
- Remove Community Edition member limits and cloud billing behavior.
- Add isolated `movo_*` Docker volumes and first-run setup.
- Add resumable presentation generation.
- Add source-build and prebuilt-container deployment modes.
