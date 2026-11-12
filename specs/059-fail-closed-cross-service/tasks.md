# Tasks: 跨服务 fail-closed 可机检约束（059-fail-closed-cross-service）

**Input**: Design documents from `/specs/059-fail-closed-cross-service/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **安全治理类特性**——修复 P1-16（四处已知 fail-open 漏洞）+ P1-17（错误码契约双权威）两项结构不一致问题。无新业务功能。

**Tests**: `tests/test_fail_open_guard.py`、`tests/test_risk_canon_fail_closed.py`、`tests/test_topic_admission_mode_off.py`、`tests/test_ontology_enforcement.py`、`tests/test_im_gateway_bindings_fail_closed.py`、三服务健康检查契约测试、`tests/` 全量回归。

**Organization**: Phase 0 研究与澄清 → Phase 1 guard 工具函数 → Phase 2 四处漏洞修复 → Phase 3 CI 静态扫描 → Phase 4 错误码文档 + API-Version → Phase 5 验收。任务编号 T001 起连续。

---

## Phase 0: 研究与澄清

- [ ] T001 建立 spec/plan/tasks/checklist 四件套（`specs/059-fail-closed-cross-service/`，本文件）
- [ ] T002 `/speckit-clarify` 消解 D1/D2/D3：豁免审批流程、api-specification.md 裁撤范围、info.version 是否本轮同步；决策回填 spec「Clarify Decisions」节
- [ ] T003 逐项核实复审报告 P1-16 列出的四处漏洞点的当前代码（读取对应文件相关行，确认现状与报告一致）
- [ ] T004 核实 `docs/error-codes.md` 与 `docs/api-specification.md:51-80` 的差异点清单（逐字段对比错误码命名、HTTP 状态码、response body schema）

## Phase 1: 统一 fail-closed 工具函数

- [ ] T005 [P] 新建 `services/common/fail_open_guard.py`：
  - `enforce_fail_closed(value: bool | None, context: str = "") -> bool`
  - `FAIL_OPEN_EXEMPT_MARKER = "fail-open-exempt:"`
  - `parse_exempt_comment(line: str) -> str | None`（从行内 comment 中提取豁免理由）
- [ ] T006 [P] 写 `tests/test_fail_open_guard.py`：None→False、True→True、False→False、exempt marker 识别、context 日志内容

## Phase 2: 四处已知漏洞逐处修复

- [ ] T007 [P] 修复 `admin-api/app/governance/risk.py:141-143`：
  - 原 `return "allow"` for unknown cell → `return enforce_fail_closed(None, context="risk._canon(cell)").or_return("deny")` + `logger.warning(...)`
  - 写 `tests/test_risk_canon_fail_closed.py`：unknown cell → denied
- [ ] T008 [P] 修复 `admin-api/app/topic_admission/service.py:17-18,55`：
  - 原 `mode=off → allowed=True` → `allowed=enforce_fail_closed(False, context="topic_admission.mode_off")`
  - 写 `tests/test_topic_admission_mode_off.py`：mode=off → denied
- [ ] T009 [P] 修复 `admin-api/app/ontology_permission/service.py:103,107`：
  - 原 `effectiveDefault="allow"` → `"deny"`（无论 enforce 开关）
  - 写 `tests/test_ontology_enforcement.py`：enforce=False → empty permission set
- [ ] T010 [P] 修复 `chat-api/app/im_gateway/bindings.py:269-273`：
  - 原 `db is None or row is None → return True` → 加一次 50ms retry，仍 None → `return False` + error log
  - 写 `tests/test_im_gateway_bindings_fail_closed.py`：mock db=None / row=None → denied

## Phase 3: CI 静态扫描

- [ ] T011 [P] 新建 `scripts/check_fail_open_patterns.py`：
  - 用 ast 模块遍历 Python AST
  - Pattern 1：`ExceptHandler` body 中含无条件 `Return(value=Constant(value=True))`
  - Pattern 2：`If(test=is_none_check)` 且 body 中 `Return(True)`
  - Pattern 3：字符串字面量 `default="allow"` / `effectiveDefault="allow"`
  - Pattern 4：`mode == "off"` 分支中 `allowed = True` 赋值
  - 支持 `# fail-open-exempt:` 注释豁免
  - 输出 JSON 清单 + 人类可读摘要
- [ ] T012 [P] 本地全仓运行脚本，确认 clean main 分支 exit 0（四处修复后应已全部通过）
- [ ] T013 注册到 `.githooks/pre-commit`（`--staged` 模式）
- [ ] T014 在 `.github/workflows/quality-gate.yml` 的 `backend-quality` job 中新增 `fail-open-scan` step

## Phase 4: 错误码文档合并 + API-Version 中间件

- [ ] T015 [P] 修改 `docs/error-codes.md`：
  - 顶部加声明 `# 唯一权威错误码字典 · Schema v2 · 2026-11-12`
  - 补充缺失的错误码：`approval.actor_mismatch`、`approval.conflict`、`tenant_id_required`
  - 明确 `fields[]`、`error_detail`、配额 429 的统一结构
- [ ] T016 [P] 修改 `docs/api-specification.md` 第 51-80 行：替换为指向 error-codes.md 的链接 + deprecated 说明（其余章节保留）
- [ ] T017 [P] 新建 `docs/error-codes-v2.md`：承载 v1 内容作历史归档
- [ ] T018 [P] 在 `services/chat-api/app/main.py` 注册 `ApiVersionMiddleware(version="1.0.0")`
- [ ] T019 [P] 在 `services/document-parser/app/main.py` 注册同样中间件
- [ ] T020 写契约测试 `tests/test_api_version_header.py`：三服务 healthz 端点均返回 `API-Version: 1.0.0` 响应头

## Phase 5: 验收与文档

- [ ] T021 跑 admin-api 全量测试，目标 ≥ baseline 816 passed
- [ ] T022 跑 chat-api 全量测试，目标 ≥ baseline 2589 passed
- [ ] T023 跑 document-parser 全量测试，目标 ≥ baseline 72 passed
- [ ] T024 更新 `specs/INDEX.md`（059 条目 + SDD 路径段）
- [ ] T025 更新 `CHANGELOG.md`
