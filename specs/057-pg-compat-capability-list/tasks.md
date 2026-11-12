# Tasks: pg_compat 能力清单与 CI 静态扫描（057-pg-compat-capability-list）

**Input**: Design documents from `/specs/057-pg-compat-capability-list/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **治理能力增强**——不引入新业务功能，对既有 `pg_compat.py` 补全可枚举能力矩阵与静态扫描门禁。

**Tests**: `tests/test_pg_compat_manifest.py`、`tests/test_pg_compat_runtime_guard.py`、`GET /api/v1/admin/compatibility/pipeline-support` 契约测试、CI 冒烟。

**Organization**: Phase 0 研究与澄清 → Phase 1 清单常量 → Phase 2 扫描脚本 → Phase 3 运行时守卫 → Phase 4 Admin API 端点 → Phase 5 CI 集成与文档。任务编号 T001 起连续。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks/checklist 四件套（`specs/057-pg-compat-capability-list/`，本文件）
- [x] T002 `/speckit-clarify` 消解 D1/D2/D3：扫描范围、存量违规处置策略、caller_filename 实现方式；决策回填 spec「Clarify Decisions」节
- [x] T003 grep 全仓 `aggregate(` 调用点（排除 tests/），统计当前使用的阶段分布（match/sort/unwind/facet/lookup 等计数）
- [x] T004 确认 `services/admin-api/app/core/pg_compat.py:1129` 处分派逻辑的可扩展性（是否适合改为 dispatch table + manifest 联动）

## Phase 1: 清单常量与基线报告

- [x] T005 [P] 在 `services/admin-api/app/core/pg_compat.py` 顶部（头部注释区之后）新增 `SUPPORTED_AGGREGATION_STAGES: frozenset[str]` 常量，内容为当前 7 个处理器对应的阶段名
- [x] T006 [P] 新增 `UNSUPPORTED_STAGE_EXPLANATIONS: dict[str, str]`，为 `$unwind` / `$facet` / `$lookup` / `$replaceRoot` 填写原因说明与推荐替代写法
- [x] T007 写 `tests/test_pg_compat_manifest.py`：断言常量存在、大小与 processor 数量一致、每阶段均有 explanation
- [x] T008 运行一次 `scripts/check_pg_compat_pipeline_stages.py --full --json > /tmp/baseline.json`，手动整理输出到 `docs/pg-compat-capability-baseline.md`

## Phase 2: 静态扫描脚本

- [x] T009 [P] 新建 `scripts/check_pg_compat_pipeline_stages.py`，支持 `--full`（全仓）和 `--staged`（仅 git diff --cached 范围）两种模式
- [x] T010 [P] 实现管道提取逻辑：用 ast.parse 解析 .py 文件，找 `aggregate([...])` 或 `aggregate(list_var)`（后者标 dynamic_pipeline 不阻断）
- [x] T011 [P] 实现阶段比较逻辑：遍历管道每个 dict，取 key 去掉 `$` 前缀，与 SUPPORTED_AGGREGATION_STAGES 比较
- [x] T012 本地运行脚本（`--full`），确认 clean main 分支 exit 0（存量绕过点不计入本次扫描，见 spec R-5）
- [x] T013 把脚本注册到 `.githooks/pre-commit`（仅 `--staged` 模式，避免全量扫描拖慢提交体验）

## Phase 3: 运行时守卫增强

- [x] T014 [P] 在 `pg_compat.py` 的分派逻辑（处理未知阶段处）加 structured warning log：包含 stage name、collection name、allowed_alternative（来自 UNSUPPORTED_STAGE_EXPLANATIONS）、source_file（用 inspect.stack[2].filename 获取）
- [x] T015 [P] 写单测：mock collection，传入含 `$unwind` 的管道，断言：① 抛出 PgCompatUnsupported；② warning log 含推荐替代方案文本

## Phase 4: Admin API 端点

- [x] T016 [P] 新建 `services/admin-api/app/api/endpoints/compatibility.py`，注册到 `admin-api/app/main.py`
- [x] T017 [P] 实现 `GET /api/v1/admin/compatibility/pipeline-support`：import SUPPORTED_AGGREGATION_STAGES，调 scan script 的 internal function（不 spawn 子进程）得到 call_sites 清单，返回 JSON
- [x] T018 [P] 给端点加 admin RBAC 守卫（需 `admin:compatibility:read` 权限）
- [x] T019 写单测：mock 文件系统下的违规文件，断言响应 JSON 包含正确的 file/line/stages/status/recommended_fix 字段
- [x] T020 浏览器目视（若环境允许）：登录 admin 页 → 访问 `/api/v1/admin/compatibility/pipeline-support`，验证页面渲染

## Phase 5: CI 集成与文档

- [x] T021 [P] 在 `.github/workflows/quality-gate.yml` 的 `backend-quality` job 中新增 step：`python scripts/check_pg_compat_pipeline_stages.py --full`
- [x] T022 [P] 更新 `specs/INDEX.md`：新增 057 特性条目 + SDD 路径段
- [x] T023 更新 `CHANGELOG.md`
- [x] T024 跑 admin-api 全量测试（baseline 816 passed），确认无新增 failure
