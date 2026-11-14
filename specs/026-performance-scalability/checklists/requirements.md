# Requirements Quality Checklist: 026 performance-scalability

**Created**: 2026-10-12

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Purpose**: 校验 026（Performance & Scalability Hardening）spec.md 的需求质量——完整性、清晰度、一致性、边界。这是"需求的单元测试"，**不校验实现是否正确**。

## 完整性（Completeness）

- [x] CHK001 关键端点 P50/P95/P99 延迟基线覆盖对话/文档解析/鉴权/文件上传/搜索 5 类端点、按端点+方法分类落库是否定义（FR-1）？
- [x] CHK002 吞吐基线按 1/10/50/100 四级并发记录 RPS（对话）与 TPS（文档解析）是否定义（FR-2）？
- [x] CHK003 外部依赖耗时占比按 DB/Redis/LLM/外部 API 四类拆分并汇总到基线是否定义（FR-3）？
- [x] CHK004 performance.yaml 性能预算（P95/包体积等）+ CI 可检查 + 回归判定阈值（如 +20%）是否定义（FR-4/FR-5）？
- [x] CHK005 DB 七项优化（slow_query_log / N+1 / 索引覆盖率 / maxTimeMS 超时 / 连接池 / explain 执行计划 / bulk_write）是否定义（FR-6~FR-12）？
- [x] CHK006 缓存八项机制（热点接入 / TTL·事件·版本戳失效 / 穿透·击穿·雪崩防护 / 命中率监控 / 记忆化 / 容量淘汰）是否定义（FR-13~FR-20）？
- [x] CHK007 前端六项优化（Web Vitals LCP·TTI·CLS / 代码分割 / 压缩+CDN+长缓存 / WebP 图片 / API 优化 / 虚拟列表）是否定义（FR-21~FR-26）？
- [x] CHK008 扩展性六项（水平扩展无状态化 / 限流·熔断·背压 / Prometheus /metrics / 容量模型 / locust+k6 压测 / 瓶颈识别）是否定义（FR-27~FR-32）？
- [x] CHK009 Non-Goals 六项明确排除（不拆微服务 / 不读写分离 / 不自动弹性伸缩 / 不做 LLM 响应缓存 / 不改业务逻辑 / 不引新中间件）是否声明？

## 一致性（Consistency）

- [x] CHK010 与 001 gatekeeper 关系：治理门禁 ↔ 性能度量，QualityForge 51 个 P0/P1 `blocked` 项由 026 基线建立解除，二者不重叠（026↔001）？
- [x] CHK011 与 007 llm-gateway 关系：026 度量 LLM 耗时占比 vs 007 韧性事件（failover/degradation_step）交叉归因，007 写入 token_usage_logs 供 026 消费（026↔007）？
- [x] CHK012 与 008 ops-dashboard 关系：026 基线数据/压测结果/容量模型/命中率指标供 008 驾驶舱消费，008 提供可视化归因（026↔008）？
- [x] CHK013 与 020 platform-multi-tenancy 关系：多租户隔离与 026 连接池/限流配置正交——020 管"谁"能访问、026 管"多快"能访问（026↔020）？
- [x] CHK014 与 025 api-contract-hardening 关系：契约稳定性 vs 性能稳定性两个"稳定性"维度互补（026↔025）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK015 待 `/speckit-clarify` 定值项是否明确标注（OQ-1 P95/包体积/命中率/并发上限阈值；OQ-2 慢查询阈值；OQ-3 压测工具；OQ-4 虚拟列表库；OQ-5 前端包体积预算）？
- [x] CHK016 MongoDB 读写分离首期不启用、仅预留扩展点（US2 Acceptance + Non-Goals 一致声明，索引/查询优化优先）是否明确？
- [x] CHK017 压测工具双选（locust 主 + k6 补充）与覆盖对话/文档解析/搜索/鉴权 4 类场景是否明确（FR-31 + Notes）？
- [x] CHK018 US1 是其他故事前置条件（无基线则无从度量优化收益）、tasks 全部初始 `blocked` 状态是否明确？

## Notes

- 本清单为 026 需求质量门禁；`[x]` 仅代表"需求质量达标"（完整、清晰、一致、边界明确），**不代表实现完成**。
- US1（性能基线与度量）是首个可独立验证切片——基线建立后 QualityForge 51 个 P0/P1 `blocked` 项方可逐步解除，其余故事方可推进。
- OQ-1~OQ-5 阈值需 `/speckit-clarify` 定值后再进入 `/speckit-tasks` 实施；阈值口径在 spec 与 plan 中一致以占位形式呈现，不阻塞需求质量判定。
- 跨特性关系已按双向声明就位（001/007/008/020/025），实施时避免与其他特性重叠或产生口径冲突。
