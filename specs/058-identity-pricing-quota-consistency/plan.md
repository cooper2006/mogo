# Plan: 主键/用量/价格/配额单一来源收敛（058-identity-pricing-quota-consistency）

**Input**: `specs/058-identity-pricing-quota-consistency/spec.md`

**Created**: 2026-11-12

## 实施范围

### 新增文件

| 路径 | 用途 |
|---|---|
| `services/common/shared_constants.py` | 跨服务共享常量单一来源（MODEL_PRICES / DEFAULT_TTL_SECONDS / utc_now() 等） |
| `services/chat-api/app/token_usage/dispatcher_dlq.py` | 死信队列处理器（reconcile loop） |
| `scripts/check_uuid_hex_usage.py` | CI 静态扫描脚本（grep uuid.uuid4().hex） |
| `tests/test_shared_constants_sync.py` | 双服务引用一致性断言 |

### 修改文件

| 路径 | 变更内容 |
|---|---|
| `services/admin-api/app/core/ids.py` | 新增 `generate_hex32_id()` 函数（基于时间有序算法） |
| `services/chat-api/app/employees/repository.py` | `uuid.uuid4().hex` → `generate_hex32_id()`（≥2 处） |
| `services/admin-api/app/skill_lifecycle.py` | 同上（≥2 处） |
| `services/admin-api/app/position_roles/repository.py` | 同上 |
| `services/admin-api/app/tenant_registry.py` | 同上 |
| `services/chat-api/app/token_usage/dispatcher.py` | queue full → dlq；persist failed → dlq + metric；新增 reconcile task |
| `services/chat-api/app/core/quota_policy.py` | `utc_now()` 改 import shared_constants；删除 naive UTC 短路 |
| `services/admin-api/app/core/quota_policy.py` | `utc_now()` 改 import shared_constants；对齐 points_unlimited 默认值 |
| `services/chat-api/app/llm/resilience/pricing.py` | MODEL_PRICES 改 from shared_constants import |
| `services/admin-api/app/api/routes/dashboard.py` | 同上 |
| `services/admin-api/app/api/routes/analytics.py` | 同上 |
| `services/chat-api/app/core/billing.py` | 删 tenant_id=default 短路分支，改为 raise QuotaExceededError |
| `.githooks/pre-commit` | 注册 `check_uuid_hex_usage.py --staged` |

### 不修改的文件

- `services/admin-api/app/core/hex32_db.py`（已有 fallback 注入逻辑不动）
- 测试夹具中的 `uuid.uuid4().hex`（允许保留，标记 noqa）
- 迁移脚本（明确豁免）

## 实施步骤

### Phase 1：ID 生成器统一（P1-11）

1. 在 `admin-api/app/core/ids.py` 实现 `generate_hex32_id()`：
   ```python
   def generate_hex32_id() -> str:
       millis = int(time.time() * 1000)
       random_part = secrets.randbelow(0x10000)  # 16-bit
       return f"{millis:016x}{random_part:08x}"  # 32-hex，单调递增
   ```
2. grep 全仓找出所有 `uuid.uuid4().hex` 调用点（排除 tests/、迁移脚本、.venv）
3. 逐一替换为 `from app.core.ids import generate_hex32_id as gid; gid()`
4. 写 `scripts/check_uuid_hex_usage.py`：扫描所有 .py 文件的 `uuid\.uuid4\(\)\.hex` 模式，支持 `--staged` 和 `--full`
5. 注册到 pre-commit hook（`--staged` 优先）

### Phase 2：用量日志失败可观测性（P1-13）

6. 在 `dispatcher.py` 中：
   - 新增 `_try_dlq_append(record, reason)` 方法（写 `token_usage_dlq` 集合）
   - `submit()` 的 QueueFull 分支改为调 dlq append + metric increment
   - `_run()` 的异常分支改为调 dlq append + metric increment + continue（不调 task_done）
   - 成功路径不变
7. 新增 `dispatcher_dlq.py`：`reconcile_token_usage()` 函数
   - 从 dlq 读取积压记录，重放到 `token_usage_logs`
   - 成功则 delete_one(dlq_doc)，失败则保留并重试
   - metric 暴露 `dlq_replayed_total` / `dlq_still_failed_total`
8. 在 `app/main.py` 启动时注册 reconcile 定时器（每 3600s 执行一次）
9. 写单测：queue full → dlq 写入断言；persist error → dlq 写入断言；reconcile → 成功/失败两种路径

### Phase 3：共享常量单一来源（P1-14 前半）

10. 新建 `services/common/shared_constants.py`，搬运：
    - `MODEL_PRICES`（来自 chat-api/pricing.py:16，确认与 admin-api/dashboard.py:40 / analytics.py:24 内容一致后取并集去重）
    - `DEFAULT_PRICE = (0.0, 0.0)`
    - `DEFAULT_TTL_SECONDS = 300.0`
    - `IDLE_TIMEOUT_SECONDS = 1800.0`
    - `utc_now()` 函数（timezone-aware UTC）
    - `points_unlimited_default = True`（对齐 admin 侧默认值）
11. 修改 `chat-api/app/llm/resilience/pricing.py`：删本地定义，改为 import
12. 修改 `admin-api/api/routes/dashboard.py`：同上
13. 修改 `admin-api/api/routes/analytics.py`：同上
14. 修改 `chat-api/app/core/quota_policy.py`：
    - 删本地 `utcnow()` 定义（naive UTC），改用 `from services.common.shared_constants import utc_now`
    - 删 `:398` 的额外短路分支，与 admin 侧对齐
15. 修改 `admin-api/app/core/quota_policy.py`：
    - 确保 `utcnow()` 也 import 自 shared_constants（已 aware UTC）
    - `points_unlimited` 默认值显式传 `True`（消除隐式依赖）
16. 写 `tests/test_shared_constants_sync.py`：同时 import 两个服务的 quota_policy，对同一输入断言结果 bit-for-bit 相等

### Phase 4：tenant_id 缺省 fail-closed（P1-14 末尾）

17. 修改 `chat-api/app/core/billing.py` 第 53、78 行附近的短路分支：
    ```python
    # 原来：if not tenant_id or tenant_id == "default": return None/跳过
    # 改为：
    if not tenant_id or tenant_id == "default":
        raise QuotaExceededError("tenant_id is required", code="tenant_id_required")
    ```
18. 写回归用例：不带 tenant_id 的请求预期返回 400

### Phase 5：回归与文档

19. 跑 `tests/orchestration/` 全量（基准 207 passed）
20. 跑 admin-api / chat-api 全部既有测试
21. 更新 `specs/INDEX.md`（058 条目 + SDD 路径段）
22. 更新 `CHANGELOG.md`

## 依赖关系

```
Phase 1 (ID generator) ──────────────────────────┐
                                                   ├── Phase 5 (regression)
Phase 2 (DLQ & metrics) ────────────────────────┤
                                                   ├── Phase 5
Phase 3 (shared constants) ─────────────────────┤
                                                   ├── Phase 5
Phase 4 (billing fail-closed) ──────────────────┘
```

Phase 1/2/3/4 相互独立，可并行推进；Phase 5 等待全部完成。

## 测试策略

| 测试类型 | 位置 | 覆盖重点 |
|---|---|---|
| 单测 | `tests/test_generate_hex32_id.py` | 单调递增、碰撞率 < 1/65536 |
| 单测 | `tests/test_uuid_hex_usage_scan.py` | check 脚本的正向/反向案例 |
| 单测 | `tests/test_token_usage_dlq.py` | queue full / persist failed / reconcile success / reconcile failed |
| 单测 | `tests/test_shared_constants_sync.py` | 双服务 quota 结果 bit-for-bit 一致 |
| 回归 | `tests/orchestration/` 全量 | 无新增 failure |
| 回归 | admin-api / chat-api 全量 | 无新增 failure |

## 风险与回滚

- **ID 碰撞**：高并发场景下（同一毫秒内 > 65536 条写入），random 部分可能碰撞。缓解：碰撞时重试（最多 3 次），并在 metric 中计数 `id_collision_retry_total`
- **Shared constants 部署**：若 `services/common` 未在两个服务的 requirements.txt 中声明，需同步加依赖。建议 workspace symlink 方式（`pip install -e ../common`）降低耦合
- **Billing 改动影响面**：`billing.py:53,78` 的短路分支目前可能在某些部署中确实需要「default tenant 不限额」行为（如 legacy 单租户部署）。需在变更说明中提示：**单租户环境须在 `.env` 中显式设置 `DEFAULT_TENANT_ID=<真实租户 ID>`，不能留空**
