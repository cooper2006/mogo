# `.qualityforge/` —— QualityForge 审计产物的入库边界

本目录曾整体被 `.gitignore` 忽略，导致 022–026 各 spec 引用的审计报告
（`.qualityforge/QUALITYFORGE-REPORT.md`）**在任何克隆里都不存在**，
"回写 QF 状态"这条验收路径无法追踪（023 的 T060/T077、024 的 B010
因此长期标为 blocked）。

2026-10-25 决策：**报告与缺陷台账入库，大体积中间产物继续忽略。**

## 入库 / 不入库

| 文件 | 入库 | 说明 |
|---|---|---|
| `QUALITYFORGE-REPORT.md` | ✅ | 缺陷台账与子域状态回写表，022–026 验收的唯一可追踪落点 |
| `README.md` | ✅ | 本文件，说明入库策略 |
| `audit.json` | ❌ | 审计原始数据（约 1.1 MB），本机运行产物，易与代码脱节 |
| `report.json` | ❌ | 机器可读报告快照，同上 |
| `FIX-HANDOFF.md` | ❌ | 单次修复交接单，随运行过期 |
| 注入脚本等 | ❌ | 审计运行时临时产物 |

`.gitignore` 用 `.qualityforge/*` + 白名单 negation 实现该边界
（整目录排除时 negation 不生效，故不能用 `.qualityforge/`）。

## 维护方式

1. 审计原件缺失或未重跑时，**只维护台账**（`QUALITYFORGE-REPORT.md`）：
   缺陷编号、所属域、覆盖任务号、当前状态。
2. 状态更新以仓库内可核验证据为准：`specs/<特性>/tasks.md` 的 `- [x]`
   勾选、对应测试文件的全绿结果。
3. 重跑 QualityForge 后，把原件的**台账级结论**（而非 audit.json）
   回写进 `QUALITYFORGE-REPORT.md`，并在"变更记录"节注明运行日期与口径。
4. 报告内容与 spec 冲突时，以 spec 为准并在此登记差异，不要反向修改 spec。
