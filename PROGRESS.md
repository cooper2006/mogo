# PROGRESS — movo→mogo 三项归一（2026-10-21）

任务：① X-MOVO-* header → X-MOGO-*（双 header 兼容过渡）② Dockerfile MOVO_* ARG → MOGO_* 优先回退 ③ document-parser ENV_PREFIX → MOGO_DOC_PROCESSING_*

## 状态
- [ ] ① 进行中：header 双读方案已定（新名优先、旧名回退，全链路 fail-closed）
- [ ] ② 未开始
- [ ] ③ 未开始

## ① 涉及文件（X-MOVO 全量清单已 grep，docs/specs 历史文件不改）
- services/chat-api/app/security/service_token.py:39 SERVICE_TOKEN_HEADER（admin-api 同文件内容一致）
- Header alias 消费端（chat-api）: app/api/principal.py:106, app/api/endpoints/auth.py:986
- Header alias 消费端（admin-api）: routes/gatekeeper_internal.py:132,193,223,263; skill_canary.py:63,105,141,174; capability_assets.py:33,59,85,118,134,154,172; personal_knowledge_internal.py:31,49,75; skill_monitoring.py:50,76; ontology_permission_internal.py:40
- 发送端: chat-api services/personal_knowledge/lifecycle_client.py:18,47; services/gatekeeper_client.py:154; admin-api routes/skills.py:99; routes/tools.py:154; services/model_connectivity.py:34; model_image_connectivity.py:48; skill_package_proxy.py:36
- 附属头: chat-api services/external_tools.py:504-505 X-MOVO-Main-ID/User-ID（发往外部 MCP，保留旧名并新增 X-MOGO-*）; admin-api routes/tools.py:305,316 响应头 X-MOVO-Operation-Result + system_audit/middleware.py:34 读同名
- CORS 白名单: 两服务 app/middleware/cors.py:64
- 测试: 两服务 tests/test_security_service_token.py:325; test_security_cors.py:118; chat-api tests/services/test_external_tools_mcp_transport.py:38,47
- 样例: docs/samples/portal-sso-integration/{portal_backend.py:40,README.md}

## ② Dockerfile ARG 清单（grep 已确认全部无 MOGO_ 兜底）
- apps/admin-web/Dockerfile:7,42 (NPM_REGISTRY, SECURITY_REFRESH)
- apps/user-web/Dockerfile.prod:6,35
- services/document-parser/Dockerfile:32-34,219-220,254 (APT, APT_SECURITY, PYPI, HF_ENDPOINT, HF_TIMEOUT, SECURITY_REFRESH)
- services/chat-api/Dockerfile:21,22,254
- services/chat-api/dsh/runtime-host/Dockerfile:8,9,17,27,33,34,38,77-82,92,95
- services/admin-api/Dockerfile:72,73,85
- deploy/docker/gateway.Dockerfile (APK_MIRROR, SECURITY_REFRESH?)
- docker-compose.build.yml:8,19,27,47,50-52,64,74,82 (MOVO_SECURITY_REFRESH, MOVO_HF_*)
- 脚本: scripts/apt_packages_bundle.sh, scripts/docling_models_bundle.sh (MOVO_HF_ENDPOINT/TIMEOUT), scripts/check_compose_image_modes.sh 等传 build-arg 处需同步
- README.md/README.zh-CN.md 文档表格需同步

## ③ document-parser
- app/core/config.py:9 ENV_PREFIX="MOVO_DOC_PROCESSING_"；:61 env_prefix=；:181 _apply_legacy_env_prefix 已存在，需读
- 注入侧: docker-compose.yml:542-564; deploy/production/docker-compose.portainer.yml.tpl; services/document-parser/.env.example; README
- 相关: scripts/dev/internal_service_auth.sh 的 MOVO_DOC_PROCESSING_* export；docker-compose.yml bootstrap 段 echo 的 token 文件键名(:161-164)

## 验证
- 每步后跑对应 pytest 子集；最后按 Round 6 配方跑相关模块

## 完成记录（2026-10-21 本轮）
- ① 完成：SERVICE_TOKEN_HEADER=X-MOGO-Service-Token + LEGACY 常量；ServiceTokenHeader 依赖双读（新名优先旧名回退）；发送端双写；X-MOVO-Operation-Result→X-MOGO（同服务内直接换名）；MCP 外部头新增 X-MOGO-* 保留旧名；CORS 白名单双放行；测试 68(admin)+71(chat) 全绿；样例文档同步。
- ② 完成（子代理 004320a4）：7 Dockerfile + compose.build + 2 脚本 + README×2 + 契约测试；ARG 链式回退实测 4 语义 OK；docker compose config OK。
- ③ 完成（子代理 b04bed42 + 主线收尾）：config.py 三级前缀 MOGO_>MOVO_>ASKAI_ 回退（_promote_legacy_env_vars + _apply_legacy_env_prefix）；compose/tpl 双写 secrets 键；doc env 键全改 MOGO_；dev 脚本双导出+测试通过；Dockerfile ENV/libreoffice 改 MOGO_；knowledge_settings.py 三处 MOGO_ 优先回退；test_container_hardening 断言同步（pins_storage 4 passed）。
- ④ 完成：FastAPI titles（MOGO Backend / MOGO Admin API，实测 title 生效）、health service 字段（mogo-admin-api / mogo-document-processing-service）、pyproject name（mogo-chat-api/mogo-admin-api）+ authors（MOGO Team）+ description、PROJECT_NAME=MOGO Platform、默认镜像名 mogo-admin/mogo-backend/mogo-document-processing、SBOM generator 名。
- 已知环境预存失败：mongo parity 2 个（需 compose 网络内 MOGO_DATA_BACKEND=mongo，Round 6 起基线，非本轮引入）。

## 收尾轮完成记录（2026-10-21，品牌整体迁移到 mogo，不再保留 movo 回退）

用户决策：**不需要回退到 movo 了，品牌整体迁移到 mogo**。据此拆除全部 movo 过渡机制。

### 已拆除（全仓 `MOVO` 清零，剩余仅为说明性注释与历史存档）
- **compose 回退链**：docker-compose.yml 全部 `${MOGO_X:-${MOVO_X:-…}}` → `${MOGO_X:-…}`；
  image 字段统一 `${MOGO_<SVC>_IMAGE:-ghcr.io/mogoai/<service>:${MOGO_VERSION:-latest}}`；
  卷名 `${MOGO_VOLUME_PREFIX:-mogo}_<suffix>`（默认值 movo→mogo）；docker-compose.build.yml、
  deploy/production/docker-compose.portainer.yml.tpl、.env.example 同步。
- **secrets 双写**：bootstrap 只写 `MOGO_DOC_PROCESSING_*`（docker-compose.yml:161-164、portainer tpl:67-72）；
  scripts/dev/internal_service_auth.sh 只导出 MOGO_ 键，生成目录 `.movo-dev/`→`.mogo-dev/`（.gitignore 同步）。
- **LEGACY_* 常量 / 遗留头**：`LEGACY_SERVICE_TOKEN_HEADER` 与 `Header` 双读依赖已删除；
  `ServiceTokenHeader` 收敛为 `Annotated[str, Header(alias=SERVICE_TOKEN_HEADER)]`（见下方回归修复）；
  document-parser 仅保留更早一代 `ASKAI_DOC_PROCESSING_` 回退。
- **CLI/脚本内部命名**：`movo_*` 函数/变量 41 个 → `mogo_*`（deploy/cli/{backup,base-images,dsh-version,i18n,images,pull}.sh、
  根脚本 `mogo`、scripts/{export_base_images,test_backup_restore_rollback,test_serial_image_pull,check_compose_image_modes}.sh、
  scripts/dev/*、dev.sh）；`MOVO_VOLUME_SUFFIXES`/`MOVO_PULL_RETRY_DELAY_SECONDS` 等内部变量同步；
  备份产物 `backups/mogo-backup-*`、卷内 `mogo-version.txt`；破坏性操作确认口令 `MOVO`→`MOGO`。
- **services / apps 标识**：`movo_share`→`mogo_share`、`mogo_session_id` 旧键读兼容删除、`mogoSessionId`、
  `_SECRET_DIR=".mogo"`、`our_product="mogo"`、`boundary=mogo-skill-*`、`@mogo/dsh-runtime-host`、
  `movo-logo.png|svg`→`mogo-logo.png|svg`、DOM id `mogo-login-*`/`mogo-register-*`、localStorage 键、
  自定义事件 `mogo:install-skill-zip`、package.json name。
- **活跃文档 / 配置**：docs/{docker-deployment,installation-guide,migration-guide,TROUBLESHOOTING,windows-installation*,
  release-process,企业级智能体功能补强规划,SDD界面呈现对照表,MOGO-Web应用集成方案}.md、
  docs/open-source-productization/*、deploy/production/README.md、deploy/tls/README.md、
  .github/workflows/{container-release,container-promote,quality-gate}.yml、.specify/memory/constitution.md、
  CHANGELOG/README×2 的迁移说明段。

### 保持不动（有意保留）
- 历史存档：docs/specs/**、docs/WORK_LOG.md、docs/regression-*.md、docs/pending-review/**、specs/**、
  .workbuddy-ai/memory/**、Decisions/ADR-5、CHANGELOG 已发布条目、.round5/、deliverables/。
- 更早一代品牌 `ASKAI_` / `askai-api` / `askai-storage` 卷名与 `ASKAI_DOC_PROCESSING_` 回退（本轮范围外）。
- 说明性注释（如“MOVO_ 前缀已随品牌迁移移除”）与 scripts/release/test_plan_container_release.py 的
  `assertNotIn("MOVO", dockerfile)` 守卫。

### 本轮修复的阻断回归
`ServiceTokenHeader = Annotated[str, Header(default="", alias=…)]` 在 FastAPI 0.141.1 下抛
`Header default value cannot be set in Annotated`，导致 chat-api a2a 套件整体失败（c968dfa 引入）。
两服务（chat-api/admin-api `app/security/service_token.py`）均改为 `Header(alias=…)`，默认值只写在调用点 `= ""`。

### 验证结果（本轮实测）
- chat-api 改动测试子集 133 passed；admin-api security 68 passed；document-parser retrieval_scope 3 passed；
  runtime-host node 8 passed；user-web test:desktop-auth / test:new-session-project-context / test:execution-v3 全通过。
- deploy/tests 88 passed；scripts/release 14 passed；`check_compose_image_modes.sh`、`check_open_source_hygiene.py`、
  dsh 四个 contract/boundary 检查、`docker compose config` 全部通过；改动文件 bash -n / py_compile / JSON / YAML 全通过。
- `docker compose config` 实测卷名：mogo_admin-static / mogo_askai-storage / mogo_deployment-secrets /
  mogo_dsh-runtime-data / mogo_knowledge-storage / mogo_mongo-data / mogo_redis-data / mogo_weaviate-data。

### 运行环境数据卷迁移
按 `docs/migrate-volumes-movo-to-mogo.md` 方案 A 对 8 个实际存在的旧卷做克隆迁移，
停机→克隆→校验（项数/属主）→`MOGO_VERSION=60eff81 ./mogo up -d` 滚动重启。
旧卷 `movo_*` 保留作回滚，未删除。

