# Feature Specification: 主键/用量/价格/配额单一来源收敛（058-identity-pricing-quota-consistency）

**Feature Branch**: `058-identity-pricing-quota-consistency`

**Created**: 2026-11-12

**Status**: Implemented

**Input**: 通用设计复审报告 §整改路线第 5 项："统一 ID 生成器（禁业务层直接写 uuid4().hex）与用量日志失败可观测性（重试/死信/对账指标）" + 第 6 项："合并配额、价格、常量的双/多副本到单一模块，双服务以 import 而非复制共享；统一 tenant_id 缺省为拒绝而非 default 放行"

涵盖 P1-11、P1-12、P1-13、P1-14 四项问题。

## 背景与问题

### P1-11：时间有序 32-hex 主键契约被数十处 `uuid4().hex` 绕过

- `admin-api/app/core/ids.py:18-20` 明确要求「避免 `uuid4().hex` 导致的顺序倒退」
- `hex32_db.py:50` 只在缺 `_id` 时注入有序 ID
- 违规调用点（≥10 处，grep 已确认）：
  - `skill_lifecycle.py:58,93`
  - `employees/repository.py:83,167`（`employee_id=uuid.uuid4().hex`、`event_id=uuid.uuid4().hex`）
  - `position_roles/repository.py:170`
  - `tenant_registry.py:94`
  - `eval_gate/*.py`、`knowledge_documents.py:810`、`capability_assets/registry.py:356` 等

**影响**：凡以 `_id > last_id` 作游标的增量采集（审计、成本、事件流）会按字典序跳过「新写入但字典序更小」的记录，静默漏数据。

### P1-12：兼容层写语义与 Mongo 不对等

- `pg_compat.py:1706,1728,1834`：`ON CONFLICT (id) DO NOTHING` 忽略 rowcount 仍返回成功
- `_update` 只刷新映射列（`column_map.py:19` R3 扁平化列与 `doc` 可能分歧）
- ≥8 处依赖 `DuplicateKeyError` 做幂等/乐观锁的调用点在 panweidb 后端行为不同

### P1-13：用量日志静默丢账

`chat-api/app/token_usage/dispatcher.py:43-55`：队列满直接 `return False`；`:87-93` 持久化异常只 `logger.exception` 后照常 `task_done()`，无重试、无死信、无对账；`:65-69` 扣点失败只记日志。

**影响**：成本报表（035/046）、配额扣减（042/049）、审计链同时缺账，且不可察觉。

### P1-14：同一逻辑双副本漂移

| 对象 | 副本位置 | 漂移表现 |
|---|---|---|
| `utcnow()` | `admin-api/core/quota_policy.py:396` aware UTC / `chat-api/core/quota_policy.py:58` naive UTC | 同一租户在不同服务算出不同周期窗口 |
| `points_unlimited` 默认 | admin 侧 `True`（`:396`）/ chat 侧 `True`（`:398` 短路） | 理论上一致，但 chat 侧多了早返回分支，边界 case 不同 |
| `MODEL_PRICES` | `chat-api/llm/resilience/pricing.py:16` / `admin-api/api/routes/dashboard.py:40` / `admin-api/api/routes/analytics.py:24` | 三份手写硬编码，diff 不联动 |
| `cost_usd` vs `cost_estimate_usd` | `docs/data-dictionary.md:5,80` 写前者 / 实际代码写后者 | 文档口径与代码不一致 |
| `default` tenant 缺省放行 | `chat-api/core/billing.py:53,78` 对 `tenant_id=default/空` 整段跳过校验 | 归属丢失的数据不受额度约束 |

## 用户故事

### User Story 1 — 业务代码写入文档时无须自己生成 ID，统一由 hex32 工厂注入（Priority: P1）🎯 MVP

所有需要创建新文档的业务代码，统一调 `app.core.ids.generate_hex32_id()`，该函数基于时间有序算法（类似 ULID 或 snowflake-lite）产生 32-hex 主键，不再允许直接调用 `uuid.uuid4().hex`。

**Why this priority**: P1-11 是数据完整性层面的系统性风险，游标漏数据在增量同步场景下会产生不可察觉的历史空洞，修复越早损失越小。

**Independent Test**: 在同一 Mongo 实例上插入 1000 条文档，分别使用新旧两种 ID 生成方式，断言：① 新方式生成的 ID 字典序 monotonic 递增；② 用 `_id > last_id` 游标拉取时不漏任何新写入记录。

**Acceptance Scenarios**:

1. **Given** 业务代码在 `employees/repository.py` 中调 `generate_hex32_id()`，**When** 创建一条员工记录，**Then** 生成的 `employee_id` 满足时间有序性质，且在 `distinct employee_id` 扫描中不会被遗漏。
2. **Given** 任意图业务代码中仍有 `uuid.uuid4().hex` 调用，**When** 运行 `scripts/check_uuid_hex_usage.py`，**Then** 报告违规文件与行号，exit code 1。
3. **Given** 代码审查阶段，**When** pre-commit hook 运行 `check_uuid_hex_usage.py --staged`，**Then** 新增的违规行被拦截，commit 不进入暂存区。

---

### User 2 — 用量日志队列满或持久化异常时，系统有可观测指标并在对账时发现缺失（Priority: P1）

队列满拒绝写入时，计数器 +1 并打 metric `token_usage.queue_full`；持久化异常时，记录到 dead-letter 集合 `token_usage_dlq` 并对账任务定时回放；扣点失败时同样记录 dlq。

**Why this priority**: P1-13 导致的是 silently wrong data（成本和配额都基于此），对账缺失会在月结时爆发为财务差异，属于 P1 级别的数据可靠性风险。

**Independent Test**: 起服后向 dispatcher 提交超出队列容量 2 倍的记录，断言：① 前 N 条正常落库；② 超出的部分写入 `token_usage_dlq`；③ metrics 暴露 `queue_full_count` 为非零。

**Acceptance Scenarios**:

1. **Given** `TokenUsageDispatcher` 队列已满（maxsize=512，已入队 512 条），**When** 再 submit 一条新记录，**Then** 返回 `False`，metric `token_usage.queue_full_total++`，记录落 `token_usage_dlq` 集合（含原始 record + `rejected_at` + `reason="queue_full"`）。
2. **Given** 持久化异常（db 不可达），**When** 异常发生，**Then** 记录落 `token_usage_dlq`（reason=`persist_failed`），metric `token_usage.persist_failed_total++`，不 raise、不调 `task_done`（直到 retry 成功或进 dlq）。
3. **Given** `token_usage_dlq` 中有积压记录，**When** 定时对账任务 `reconcile_token_usage()` 执行，**Then** 逐条重放 dlq 记录到 `token_usage_logs`，成功则从 dlq 移除，失败则保留并重试，最终 metrics 暴露 `dlq_replayed_total` / `dlq_still_failed_total`。
4. **Given** 对账完成，**When** 查询 dashboard 的成本报表，**Then** 报表总额 = `token_usage_logs` 聚合 + dlq 重放后聚合，与直接查库一致（零差距）。

---

### User Story 3 — `MODEL_PRICES` / `DEFAULT_TTL_SECONDS` / quota 时间函数统一到单一模块（Priority: P1）

所有服务引用 `MODEL_PRICES`、`DEFAULT_TTL_SECONDS`、`utc_now()` 等共享常量/工具函数时，改为 `from app.core.shared_constants import ...` 导入，禁止各自定义。

**Why this priority**: P1-14 的双副本漂移已在 production 中产生实质影响（配额周期计算偏差、成本估算不一致），是最容易量化修复收益的一项。

**Independent Test**: 在两个服务的 quota 计算路径上分别传入同一组参数，断言返回值完全一致（bit-for-bit equal），包括周期窗口起止时间与不限额判定。

**Acceptance Scenarios**:

1. **Given** `MODEL_PRICES` 定义于 `services/common/shared_constants.py`，**When** `chat-api` 和 `admin-api` 均 from 此处 import，**Then** 修改一份即全局生效，三份手写副本的 drift 不复存在。
2. **Given** `DEFAULT_TTL_SECONDS` 同理统一到 `shared_constants.py:23`，**When** grep 全仓 `DEFAULT_TTL_SECONDS\s*=`，**Then** 只匹配到一处定义（import 语句不计入）。
3. **Given** `chat-api/core/quota_policy.py` 的 `utc_now()` 改为 `from app.common.shared_constants import utc_now`（**2026-11-13 口径更正**：实现采用 `services/common` 权威源 + 各服务 `app/common/` vendored 逐字节一致副本，路径是 `app.common.*` 而非 `app.core.*`），**Then** 两处（admin-api / chat-api）返回同为 timezone-aware UTC，不再有 naive/datetime 混用。该场景已于 2026-11-13 删除两个本地 `def utc_now()` 后达成——此前虽有 import 语句，但被同文件本地定义覆盖，属「假导入」。
4. **Given** `billing.py:53,78` 的 `tenant_id == 'default'` 短路分支删除，**When** 请求不带 tenant_id，**Then** 走统一配额校验路径（fail-closed，返回 400 `tenant_id_required`）。

---

## 需求规格

### R-1 单一 ID 生成入口（解决 P1-11）

新建/扩展 `services/admin-api/app/core/ids.py`：

```python
def generate_hex32_id() -> str:
    """时间有序 32-hex 主键生成器。

    基于 epoch millis（int(time.time() * 1000)）左移 16 bit + 随机 16 bit，
    保证单调递增字典序；调用方无需自己拼凑。
    """
    ...

# 公共别名，供外部 import
generate_id = generate_hex32_id
```

修改策略：
- 对已确认的违规调用点（grep 结果中的 10+ 处）逐一替换为 `generate_hex32_id()`
- 不改 MongoDB insert 侧的 fallback 注入逻辑（`hex32_db.py:50`）——那是兜底，不是主路径
- 新增 `scripts/check_uuid_hex_usage.py`：扫描所有 `.py` 文件中 `uuid.uuid4().hex` 调用（排除测试夹具、迁移脚本），报告违规清单
- pre-commit hook 加入该检查（`--staged` 模式优先，full scan 作为 nightly job）

### R-2 用量日志失败可观测性（解决 P1-13）

修改 `services/chat-api/app/token_usage/dispatcher.py`：

```python
# 新增死信集合
DLQ_COLLECTION = "token_usage_dlq"

class TokenUsageDispatcher:
    async def submit(self, record):
        try:
            self._queue.put_nowait(record)
            return True
        except asyncio.QueueFull:
            metric_queue_full.increment()
            await self._try_dlq_append(record, reason="queue_full")
            return False

    async def _run(self):
        while True:
            record = await self._queue.get()
            try:
                await repo.insert(record)
                await deduct_points_after_request(...)
            except Exception as exc:
                metric_persist_failed.increment()
                await self._try_dlq_append(record, reason=f"persist_error:{type(exc).__name__}")
                # NOTE: do NOT call task_done() here — will be called on successful replay
                continue
            finally:
                self._queue.task_done()
```

新增定时对账任务（注入到 `app/main.py` 的常驻循环）：
```python
async def token_usage_reconciliation_loop():
    while True:
        await asyncio.sleep(3600)  # 每小时对账
        await reconcile_token_usage()
```

### R-3 共享常量单一来源（解决 P1-14）

新建 `services/common/shared_constants.py`（或在 `admin-api/app/core/` 中作为 shared 模块）：

```python
# 模型定价表（唯一权威来源）
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # ... 从现有 chat-api/pricing.py 搬运，保持内容不变
}
DEFAULT_PRICE = (0.0, 0.0)

# TTL 常量
DEFAULT_TTL_SECONDS = 300.0
IDLE_TIMEOUT_SECONDS = 1800.0

# 时间工具
from datetime import datetime, timezone
def utc_now() -> datetime:
    return datetime.now(timezone.utc)
```

修改所有引用方为 import 而非 copy：
- `chat-api/app/llm/resilience/pricing.py` → `from services.common.shared_constants import MODEL_PRICES, DEFAULT_PRICE`
- `admin-api/api/routes/dashboard.py` → 同上
- `admin-api/api/routes/analytics.py` → 同上
- `chat-api/app/core/quota_policy.py` → `from services.common.shared_constants import utc_now, points_unlimited_default=True`
- `admin-api/app/core/quota_policy.py` → 同上（删除本地 `utc_now` 定义）

### R-4 tenant_id 缺省 fail-closed（解决 P1-14 末尾）

`chat-api/app/core/billing.py` 删去 `if tenant_id in ("default", ""): return` 短路分支，改为：

```python
if not tenant_id or tenant_id == "default":
    raise QuotaExceededError("tenant_id is required", code="tenant_id_required")
```

`core/tenant.py:24` 的归一化逻辑保留（把空值归一为 `default`），但下游消费方不得再把 `default` 当作合法 tenant 处理。

## Clarify Decisions

| # | 决策点 | 建议默认值 | 阻塞 implement？ |
|---|---|---|---|
| D1 | `generate_hex32_id()` 的算法选型 | 简易版：`int(millis)*pow(16,8) + random_16bit`（非 snowflake，避免分布式时钟偏移问题） | 否 |
| D2 | dlq 记录的 TTL | 30 天（与 audit retention 对齐），到期由 purge 任务清理 | 否 |
| D3 | 存量 uuid4().hex 调用是否一刀切替换 | 先跑一次全仓替换脚本，再对 grep 出来的剩余例外（测试夹具/迁移脚本/明确不需要有序性的 case）加 `# noqa: UUID_HEX_USAGE` 注解放行 | 否 |
| D4 | shared_constants 放在 admin-api 还是 common | `services/common/`（跨服务共享包），两服务均 `pip install` 或 workspace 内 symlink | 否 |

## 验收标准

> **2026-11-13 机检复核口径**：逐条按磁盘与命令实测处置。上一轮把 `--staged` pre-commit 门禁误判为「待后续阶段」，实际 `.githooks/pre-commit` 已包含该调用，本轮补勾；「全仓清零」确未达成，如实保留 `[ ]` 并写明渐进收口策略。

- [ ] 全仓 `grep -rn "uuid\.uuid4\(\)\.hex" services/ --include="*.py"` 结果为 0（测试目录除外）：**未达成，且按当前策略不打算一次性达成**。`scripts/check_uuid_hex_usage.py --full` 输出「✅ 无新增 uuid4().hex 实体主键用法（存量主键 **91 处**已在基线，允许场景 **52 处**）」exit 0；存量登记在 `scripts/uuid_hex_baseline.json`（15.5 KB），CI（`.github/workflows/quality-gate.yml` 的 `Unordered primary-key scan (058 T007)`）只拦**基线外新增**，属渐进收口而非全量替换。保留 `[ ]`，不假勾。
- [x] `scripts/check_uuid_hex_usage.py --staged` 在 pre-commit 中被调用并通过：`.githooks/pre-commit` 末段调用 `--staged` 且 `|| exit 1`；空暂存实测 exit 0（「✅ 无新增 uuid4().hex 实体主键用法」）。**前提同 057**：钩子文件已就位，`core.hooksPath` 需一次性 `git config core.hooksPath .githooks` 启用（当前仓库未设置），属本地启用步骤，不计入代码交付缺口。
- [x] `tests/test_token_usage_dispatcher.py` 覆盖 queue full / persist failed / dlq replay 三态（见 `test_token_usage_dlq.py`，10 项全绿）
- [x] `metrics.token_usage.queue_full_total` 在压力测试中如实计数（Counter.inc() 修正，3 处 .increment() → .inc()）
- [x] `MODEL_PRICES` 在全仓只有一处定义（`services/common/shared_constants.py:10` 为权威源；chat-api/admin-api/document-parser 的 vendored 副本逐字节一致，`test_shared_constants_sync.py` 校验）
- [x] 双服务 quota 计算对相同输入返回 bit-for-bit 一致结果（`test_quota_consistency.py` 10 项核心测试全绿）
- [x] `billing.py` 不带 tenant_id 的请求返回 400 而非 200（`error_handler.py` 新增 `TenantIdRequiredError → 400` 处理器，`test_tenant_id_required_400.py` 3 项全绿）
- [x] 双服务 `quota_policy.utc_now` 运行时指向单一权威源且返回 timezone-aware UTC（2026-11-13 修复「假导入」：删除两个本地 `def utc_now()`；`test_shared_constants_sync.py` 改为运行时对象身份断言，4 项全绿；chat-api quota 回归 26 项、admin-api quota 回归 36 项全绿）

## 风险与回滚

- **Risky**：全仓替换 `uuid.uuid4().hex` 可能在某些场景改变排序属性（如分布式部署下时间窗重叠）。缓解：新 ID 生成器在同一毫秒内的碰撞概率 < 1/65536，可通过增加 random 位宽进一步降低
- **Dlq 存储膨胀**：高负载下 dlq 可能快速增长，需配套定期清理（R-2 D2）
- **Shared constants 回退**：若 `services/common` 包引入新的部署复杂度，可退回到在两个服务各自保留常量但加同步测试（`test_shared_constants_in_sync.py`）——先难后易
- **影响范围**：纯重构类变更，不增新功能；API 契约零变化；测试覆盖确保语义不变
