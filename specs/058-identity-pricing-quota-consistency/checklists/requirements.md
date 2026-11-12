# Requirements Quality Checklist: 058 identity-pricing-quota-consistency

**Purpose**: 校验 058（主键/用量/价格/配额单一来源收敛）spec.md 的需求质量。
**Created**: 2026-11-12
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

## 完整性

- [ ] CHK001 R-1 `generate_hex32_id()` 的时间有序算法在高并发（同一毫秒 > 65536 写入）下的碰撞处理策略（重试次数上限、超限后的 fallback 行为）是否在 spec 中明确
- [ ] CHK002 R-2 dlq 记录的 30 天 TTL 清理机制（T02 D2）——是独立的 purge task 还是复用现有的 audit purge？具体实现未写
- [ ] CHK003 R-3 shared_constants 的部署方式（workspace symlink vs pip install -e）的优缺点分析是否包含在 plan 中

## 清晰度

- [ ] CHK004 billing.py 的 tenant_id 缺省 fail-closed（R-4）对单租户 legacy 部署的影响评估是否充分（需在 CHANGELOG / 部署说明中加醒目标注）
- [ ] CHK005 `check_uuid_hex_usage.py` 的 noqa 豁免语法（`# noqa: UUID_HEX_USAGE`）是否与项目既有 noqa 惯例一致（当前项目用 `# noqa: F401` 等 flake8 风格）

## 一致性

- [ ] CHK006 R-3 中 MODEL_PRICES 三份手写副本的内容核对结果（T004 grep）是否需要在 spec 中记录差异点和最终采纳版本

## 边界与歧义

- [ ] CHK007 id_collision_retry_total metric 的暴露方式（Prometheus counter？log 计数？）未明确

## Notes

- 本特性涉及数据可靠性修复（P1-11 游标漏数据），实施前应先在 staging 环境验证 hex32 ID 的单调性在实际写入负载下成立
