# Tasks: 主键/用量/价格/配额单一来源收敛（058-identity-pricing-quota-consistency）

**Input**: Design documents from `/specs/058-identity-pricing-quota-consistency/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **数据可靠性治理**——修复 P1-11（ID 无序）、P1-13（用量日志静默丢账）、P1-14（常量双副本漂移）三项系统性风险。无新业务功能。

**Tests**: `tests/test_generate_hex32_id.py`、`tests/test_uuid_hex_usage_scan.py`、`tests/test_token_usage_dlq.py`、`tests/test_shared_constants_sync.py`、`tests/orchestration/` 全量回归。

**Organization**: Phase 0 研究与澄清 → Phase 1 ID 生成器 → Phase 2 用量日志 DLQ → Phase 3 共享常量 → Phase 4 tenant 缺省 → Phase 5 验收。任务编号 T001 起连续。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks/checklist 四件套（`specs/058-identity-pricing-quota-consistency/`，本文件）
- [x] T002 `/speckit-clarify` 消解 D1/D2/D3：ID 算法选型、dlq TTL、存量 uuid4().hex 替换策略；决策回填 spec「Clarify Decisions」节
- [x] T003 grep 全仓 `uuid\.uuid4\(\)\.hex` 调用点（排除 tests/、migrations/、.venv、__pycache__），输出清单到 `docs/uuid-hex-usage-inventory.md`
- [x] T004 grep 全仓 `MODEL_PRICES\s*=` 定义点，核对三份手抄内容是否完全一致（若有差异，记录以哪份为准）

## Phase 1: ID 生成器统一（P1-11）

- [x] T005 [P] 在 `services/admin-api/app/core/ids.py` 新增 `generate_hex32_id() -> str` 函数：基于 epoch millis 左移 16 bit + random 16 bit，保证字典序单调递增
- [x] T06 [P] 根据 T003 清单逐一替换以下文件的 `uuid.uuid4().hex` 调用：
  - `services/chat-api/app/employees/repository.py:83`（employee_id）
  - `services/chat-api/app/employees/repository.py:167`（event_id）
  - `services/admin-api/app/skill_lifecycle.py:58,93`
  - `services/admin-api/app/position_roles/repository.py:170`
  - `services/admin-api/app/tenant_registry.py:94`
  - `services/admin-api/app/eval_gate/*.py`（逐文件核查）
  - `services/admin-api/app/knowledge_documents.py:810`
  - `services/admin-api/app/capability_assets/registry.py:356`
- [x] T007 [P] 新建 `scripts/check_uuid_hex_usage.py`：扫描 `.py` 文件中 `uuid.uuid4().hex` 模式，支持 `--staged` 和 `--full` 模式，输出 JSON 清单
- [x] T008 [P] 写 `tests/test_generate_hex32_id.py`：断言单调递增性（序列插入后 distinct 排序与原顺序一致）、碰撞率 < 1/65536（压力测试 10000 次）
- [x] T009 注册 `check_uuid_hex_usage.py --staged` 到 `.githooks/pre-commit`

## Phase 2: 用量日志失败可观测性（P1-13）

- [x] T010 [P] 在 `services/chat-api/app/token_usage/dispatcher.py` 中：
  - 新增 `_DLQ_COLLECTION = "token_usage_dlq"` 常量
  - 新增 `_try_dlq_append(record, reason)` 私有方法（insert_one dlq 集合，字段含 record 副本 + `rejected_at` + `reason`）
  - `submit()` QueueFull 分支改为调 `_try_dlq_append` + metric increment
  - `_run()` 异常分支改为调 `_try_dlq_append` + metric increment + continue（不调 task_done）
- [x] T011 [P] 新建 `services/chat-api/app/token_usage/dispatcher_dlq.py`：实现 `reconcile_token_usage()` 函数
  - 从 dlq 读取积压记录，逐条 insert_one 到 token_usage_logs
  - 成功则 delete_one(dlq_doc)，失败则保留并重试（指数退避，最多 3 次）
  - metric：`dlq_replayed_total++` / `dlq_still_failed_total++`
- [x] T012 [P] 在 `services/chat-api/app/main.py` 启动时注册 reconcile 定时器（`asyncio.create_task(_reconciliation_loop())`，周期 3600s）
- [x] T013 写 `tests/test_token_usage_dlq.py`：
  - queue full → dlq 写入断言
  - persist error → dlq 写入断言
  - reconcile success → dlq 清空 + logs 集合增加
  - reconcile failed → dlq 保留 + metric 计数

## Phase 3: 共享常量单一来源（P1-14 前半）

- [x] T014 [P] 新建 `services/common/shared_constants.py`，搬运以下内容：
  - `MODEL_PRICES`（from chat-api/pricing.py:16，与 admin 两份核对一致后取唯一版本）
  - `DEFAULT_PRICE = (0.0, 0.0)`
  - `DEFAULT_TTL_SECONDS = 300.0`
  - `IDLE_TIMEOUT_SECONDS = 1800.0`
  - `utc_now()` 函数（timezone-aware UTC，用 `datetime.now(timezone.utc)`）
  - `points_unlimited_default = True`
- [x] T015 [P] 修改 `services/chat-api/app/llm/resilience/pricing.py`：删本地 MODEL_PRICES 定义，改为 `from services.common.shared_constants import MODEL_PRICES, DEFAULT_PRICE`
- [x] T016 [P] 修改 `services/admin-api/app/api/routes/dashboard.py`：同上
- [x] T017 [P] 修改 `services/admin-api/app/api/routes/analytics.py`：同上
- [x] T018 [P] 修改 `services/chat-api/app/core/quota_policy.py`：
  - 删本地 `utcnow()` naive UTC 定义，改为 import shared_constants.utc_now
  - 删 `:398` 的额外短路分支，与 admin 侧对齐
- [x] T019 [P] 修改 `services/admin-api/app/core/quota_policy.py`：
  - 确保 `utcnow()` import 自 shared_constants（已 aware UTC）
  - `points_unlimited` 默认值显式传 `True`
- [x] T020 [P] 写 `tests/test_shared_constants_sync.py`：双服务 quota_policy 对相同输入断言结果 bit-for-bit 相等

## Phase 4: tenant_id 缺省 fail-closed（P1-14 末尾）

- [x] T021 [P] 修改 `services/chat-api/app/core/billing.py`：删 `if tenant_id in ("default", ""): return ...` 短路分支，改为 `raise QuotaExceededError("tenant_id is required", code="tenant_id_required")`
- [x] T022 写回归用例：不带 tenant_id 的请求预期返回 400

## Phase 5: 验收与文档

- [x] T023 跑 `tests/orchestration/` 全量，目标 ≥ 207 passed
- [x] T024 跑 admin-api 全量测试（baseline 816 passed）
- [x] T025 跑 chat-api 全量测试（baseline 2589 passed）
- [x] T026 更新 `specs/INDEX.md`（058 条目 + SDD 路径段）
- [x] T027 更新 `CHANGELOG.md`
