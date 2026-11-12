# Quickstart: 主键/用量/价格/配额单一来源收敛（058）

**Feature**: `specs/058-identity-pricing-quota-consistency/spec.md`

## 背景

三项系统性风险同时存在：
1. **ID 无序**：`uuid.uuid4().hex` 字典序不单调，导致 `_id > last_id` 游标漏数据
2. **用量日志丢账**：队列满或持久化异常时静默丢弃，成本和配额报表缺账不可察觉
3. **常量漂移**：MODEL_PRICES / utcnow() / DEFAULT_TTL_SECONDS 等多处手抄副本，双服务计算结果不一致

## 变更摘要

| 项目 | 变更前 | 变更后 |
|---|---|---|
| ID 生成 | 业务代码直接 `uuid.uuid4().hex` | `from app.core.ids import generate_hex32_id` |
| 用量日志失败 | 静默 drop + logger.exception | 写 dlq 集合 + metric 暴露 + 定时对账回放 |
| MODEL_PRICES | 三份手写副本 | 统一 from `services/common/shared_constants` |
| utcnow() | chat-api naive UTC / admin-api aware UTC | 统一 import shared_constants.utc_now（aware） |
| tenant_id=default | billing 短路跳过校验 | raise QuotaExceededError("tenant_id_required") |

## 快速验证

### ID 单调性

```bash
cd services/chat-api
pytest tests/test_generate_hex32_id.py -v
```

预期：10000 次生成的 ID 字典序严格递增，碰撞率 ≈ 0。

### 用量日志 DLQ

```bash
# 压力测试：向 dispatcher 提交超过队列容量的记录
pytest tests/test_token_usage_dlq.py -v
```

预期：超出的记录写入 `token_usage_dlq` 集合，metrics 计数正确。

### 常量一致性

```bash
pytest tests/test_shared_constants_sync.py -v
```

预期：双服务 quota_policy 对相同输入返回 bit-for-bit 一致的结果。

### UUID hex 扫描

```bash
python scripts/check_uuid_hex_usage.py --full
```

预期：exit 0（所有违规点已替换）。

## 部署注意

**单租户 legacy 部署**：若线上使用空 `tenant_id` 作为默认租户，需在 `.env` 中显式设置：
```
DEFAULT_TENANT_ID=<你的真实租户ID>
```
否则不带 tenant_id 的请求会返回 400。

## 回滚

本特性为纯粹的重构+防护增强，无行为变化（除 billing.py 的 tenant_id 短路移除外）。如需回滚 billing 行为， revert billing.py 相关改动即可。
