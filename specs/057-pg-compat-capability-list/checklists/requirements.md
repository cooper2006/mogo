# Requirements Quality Checklist: 057 pg-compat-capability-list

**Purpose**: 校验 057（pg_compat 能力清单与 CI 静态扫描）spec.md 的需求质量。
**Created**: 2026-11-12
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

## 完整性

- [ ] CHK001 R-2 静态扫描脚本的管道提取逻辑是否能正确处理嵌套 aggregate（如 `$facet` 内嵌子管道）
- [ ] CHK002 R-4 Admin API 端点的响应 JSON schema 是否在 spec 中明确定义（call_sites 每项的字段集合、status 枚举值）
- [ ] CHK003 R-5 存量绕过点的「30 天宽限期 + 强杀」策略是否有明确的到期自动执行机制（cron job？手动触发？）

## 清晰度

- [ ] CHK004 D1 中「tests/ 目录不扫描」的理由是否充分——测试中的 aggregate 用于验证 fake db 行为，确实不需要检查兼容性
- [ ] CHK005 D2 的「阻断新增不阻断存量」策略在 pre-commit 和 CI 中的分别行为是否说清（pre-commit 扫 staged diff → 阻断新增；CI full scan → 仅报告存量但不 fail）

## 一致性

- [ ] CHK006 R-3 运行时 warning log 的 structured field `source_file` 通过 `inspect.stack()[2].filename` 获取，在多层的代理/装饰器场景下行号可能偏移，是否需要修正偏移量

## 边界与歧义

- [ ] CHK007 `dynamic_pipeline`（动态拼接的管道变量）的处理策略：标记但不阻断是否会在 CI 中产生噪音告警，影响真正需要关注的违规发现

## Notes

- 本特性属于治理能力增强，风险评估较低；主要关注点是扫描误报率和存量清理的执行节奏
