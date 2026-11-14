# 错误码字典 · v1 历史归档（059 T017）

> **本文件是历史归档存根，不是错误码字典，也不会被持续维护。**
> 全仓库错误码 / HTTP 映射 / 响应结构的**唯一权威**是 [`docs/error-codes.md`](./error-codes.md)（Schema v2，2026-11-12 起）。
> 本文件刻意**不复制任何错误码表**——避免重新引入 059 P1-17 要裁撤的「错误码契约双权威」。

## 归档目的

059（fail-closed-cross-service）的 P1-17 指出：`docs/api-specification.md` 与 `docs/error-codes.md`
曾各自承载错误码契约片段，存在双权威漂移风险。T015–T017 的收口动作是：

1. **T015**：`docs/error-codes.md` 升级为 **Schema v2 唯一权威**，补齐
   `tenant_id_required` / `approval.actor_mismatch` / `approval.conflict` 三个码，
   并明确 `fields[]` / `error_detail` / 配额 `429` 的统一响应结构（§5.1）。
2. **T016**：`docs/api-specification.md` §2 加 DEPRECATED 权威指针，停止维护错误码枚举，
   仅保留响应 envelope 结构与安全约束。
3. **T017**（本文件）：为 v1 契约留一份可追溯的归档记录。

## v1 → v2 演进摘要

| 维度 | v1（025 契约硬化，归档） | v2（现行唯一权威） |
|---|---|---|
| 标题口径 | `错误码字典（025 契约硬化 · FR-30/31/11）` | `唯一权威错误码字典 · Schema v2 · 2026-11-12` |
| 权威声明 | 自称唯一权威，但 api-specification.md 仍有重复片段 | 显式声明唯一权威，并在 api-specification.md 加 DEPRECATED 指针 |
| 业务码 | §3 登记 6 个 | §3 增至 9 个（+ `tenant_id_required`、`approval.actor_mismatch`、`approval.conflict`） |
| 429 结构 | 仅 `api.rate_limited` 一行 | §5.1 明确 `Retry-After` + `error_detail.meta` 统一口径 |
| `fields[]` / `error_detail` | §5 列字段名，无结构约束 | §5.1 明确适用边界与键集合 |

## 如何查看完整 v1 内容

v1 的完整字典（含 15 个通用码表与当时的 §3 业务码）**不在此复制**，请通过版本历史取回，避免产生第二份会漂移的副本：

```bash
# 取 v2 升级前的 error-codes.md 快照
git show 8d73513f:docs/error-codes.md
# 或对比本次升级的完整 diff
git log --oneline -- docs/error-codes.md
```

> 8d73513f = 059 文档裁撤落地前的提交基线（含 056–059 首入库与两处确定性修复）。
