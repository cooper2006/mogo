# Requirements Quality Checklist: 059 fail-closed-cross-service

**Purpose**: 校验 059（跨服务 fail-closed 可机检约束）spec.md 的需求质量。
**Created**: 2026-11-12
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

## 完整性

- [ ] CHK001 D1 豁免审批流程——「CODEOWNERS review」的具体执行机制未描述（是 PR 强制 review 才能加豁免注释，还是事后补审？）
- [ ] CHK002 R-4 中 `docs/api-specification.md` 裁撤 §51-80 后，剩余章节是否有引用这些错误码的地方需要同步更新 **〔2026-11-13 复核：前提不成立〕** 该区间并不存在可裁撤的错误码表（实为 §2 envelope 示例与 QF-234/235 安全规范），实际未删除任何章节，仅在 `:47` 登记 DEPRECATED 权威指针。故「裁撤后需同步更新引用」的问题不再适用；剩余章节仍保留有效 envelope 说明，其错误码语义由 `docs/error-codes.md` 统一。详见 `spec.md` R-3 落地口径更正。
- [ ] CHK003 Phase 2 四处漏洞修复的单测覆盖率——每个修复点是否都有正向（修复后 deny）+ 反向（正常路径不受影响）两类用例

## 清晰度

- [ ] CHK004 im_gateway retry 50ms 引入的额外延迟，在峰值流量下对 p99 的影响估算是否有提及
- [ ] CHK005 topic_admission mode=off 语义变化的影响范围——线上有多少部署实际用了 mode=off？（需在 plan 中加摸排步骤）

## 一致性

- [ ] CHK006 spec 中称「API 契约零变化」，但 R-4 新增了 `/api/v1/admin/compatibility/pipeline-support` 新端点；这属于「新增」而非「变更」，表述应更精确

## 边界与歧义

- [ ] CHK007 fail-open-scan 对 dynamic code generation（如 eval/exec 构造的 return True）无法检测，是否需要注明此局限

## Notes

- 本特性的安全风险在于「修复引入新的 breakage」（把原来放行的路径变成拒绝），必须在 staging 环境全链路验证后再上生产
- CHK005 尤为重要：mode=off 若在生产中有实际用例，硬性改为 deny 会导致业务中断
