# Requirements Quality Checklist: 023 observability-resilience

**Created**: 2026-10-12

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Purpose**: 校验 023（可观测性与韧性加固）spec.md 的需求质量——完整性、清晰度、一致性、边界。这是"需求的单元测试"，**不校验实现是否正确**。

## 完整性（Completeness）

- [x] CHK001 结构化日志字段（ts/level/service/message/trace_id/span_id/tenant_id/user_id）稳定且缺失为 null、日志输出 stdout（FR-1/FR-4）？
- [x] CHK002 日志级别运行时可调（DEBUG/INFO/WARN/ERROR）且无需重启、ERROR 含完整堆栈/请求/租户/用户/下游耗时（FR-2/FR-3）？
- [x] CHK003 /health 存活检查 + /ready 就绪检查（依赖可达性）+ 启动自检失败返回 503（FR-5/FR-6）？
- [x] CHK004 入口生成 W3C trace_id + 跨服务 traceparent 传播 + 异步任务保留父 span 上下文（FR-7/FR-8/FR-10）？
- [x] CHK005 黄金四信号（延迟/流量/错误率/饱和度）+ 业务指标按租户/智能体聚合 + 高基数 label 哈希化（FR-11/FR-12/FR-13）？
- [x] CHK006 SLO 定义（可用性 99.9%、P99<3s、LLM 错误率<1%）+ 错误预算可查 + 违约触发告警（FR-14/FR-15）？
- [x] CHK007 告警分级 P0/P1/P2 + 静默窗口 + 抑制去重 + Runbook 覆盖 5+ 场景 + 排障看板可下钻（FR-16/FR-17/FR-18/FR-19/FR-20）？
- [x] CHK008 熔断器（半开策略/连续失败阈值）+ 超时递减（30s/10s/5s）+ 重试退避抖动 + 资源池隔离 + 背压限流（FR-21 to FR-25）？
- [x] CHK009 MongoDB 自动备份 AES-256 加密 + 保留策略（30d 本地 + 90d 异地）+ 恢复演练 + 跨 AZ 部署 + RTO/RPO ≤ 30min/15min + 灾难恢复预案（FR-26 to FR-32）？

## 一致性（Consistency）

- [x] CHK010 与 001 gatekeeper 关系：本特性负责执行层限流 + 背压，001 负责策略决策，告警可触发 001 自动降权（023↔001）？
- [x] CHK011 与 007 llm-gateway-resilience 关系：退避参数（1.5s/30s/±10%/3 次）对齐，不重复实现 LLM 调用级韧性（023↔007）？
- [x] CHK012 与 008 ops-dashboard 关系：本特性是 008 的数据源（Prometheus 指标、Grafana 面板、告警历史）（023↔008）？
- [x] CHK013 与 010 dag-orchestration 关系：010 节点级重试包裹本特性依赖级重试，追踪链路贯穿 DAG 节点（023↔010）？
- [x] CHK014 与 002/003/004/005/006 关系：业务特性无需感知，入口注入 trace_id 由中间件自动处理（023↔002-006）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK015 不引入商业 APM、不实现多区域灾备、不实现全自动扩缩容、不修改业务代码逻辑（Non-Goals）？
- [x] CHK016 不替换现有日志采集方案（若已有 Loki/ELK 则复用，否则引入 Loki 或 Vector）（Non-Goals）？
- [x] CHK017 熔断/超时/退避/备份频率/RTO/RPO 等默认参数需 /speckit-clarify 定值并与 007 对齐（Clarify 记录）？
- [x] CHK018 8 个 OQ 待定（日志后端/追踪后端/熔断库/备份存储/告警渠道/SLO 目标/RTO RPO/跨 AZ 方式）已在 Clarify 记录中列出（Clarify 记录）？

## Notes

- 本清单为需求质量门禁；US1（结构化日志与健康检查）为首个可独立验证切片，完成后可立即交付。
- 标记 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- 8 个 OQ（OQ-1 至 OQ-8）待定，需 `/speckit-clarify` 消解后方可进入实施。
