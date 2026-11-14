# Requirements Quality Checklist: 021 unified-context-address

**Created**: 2026-10-05

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Purpose**: 校验 021（统一上下文地址空间）spec.md 的需求质量——完整性、清晰度、一致性、边界。这是"需求的单元测试"，**不校验实现是否正确**。

## 完整性（Completeness）

- [x] CHK001 四类地址 scheme 是否定义且未知根报错（FR-1）？
- [x] CHK002 per-type tier 适配器接口是否定义（FR-2）？
- [x] CHK003 渐进加载"默认只 L0+L1"是否定义（FR-3）？
- [x] CHK004 委托式可见性是否明确"不建统一权限模型"（FR-4）？
- [x] CHK005 检索轨迹落观测日志（非审计）+ 绑定 session/turn + 抽样审计是否定义（FR-5）？
- [x] CHK006 会话三重角色（消费/生产/归档）是否定义且与 002/009 对齐（FR-6/FR-9）？
- [x] CHK007 首期 tenant=memory、其余按节奏接入是否定义（FR-7）？
- [x] CHK008 不新建统一存储、复用各后端库是否声明（FR-8/Non-Goals）？

## 一致性（Consistency）

- [x] CHK009 与 017 关系：消费 017 memory 地址与适配器，017 为首个 tenant（spec 跨特性）？
- [x] CHK010 与 005/014/015 关系：resource 三类根复用 citation/source_ref 锚点？
- [x] CHK011 与 004/018 关系：skill 两类根复用元数据/契约？
- [x] CHK012 与 002/009 关系：会话消费+生产+归档，SessionEnd 触发分层沉淀？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK013 非记忆类 L0/L1 不调 LLM、复用既有字段是否明确（避免成本失控）？
- [x] CHK014 越权面不新增（委托各后端，地址层无独立权限码）是否声明？
- [x] CHK015 轨迹含元数据脱敏策略是否指向 001 PII（FR-5）？

## Notes

- 本清单为需求质量门禁；首期 tenant=memory 已可在 017 优化后独立验证。
- 标记 `[x]` 仅代表"需求质量达标"，不代表实现完成。
