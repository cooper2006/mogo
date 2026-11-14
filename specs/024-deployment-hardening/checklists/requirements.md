# Requirements Quality Checklist: 024 deployment-hardening

**Created**: 2026-10-12

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Purpose**: 校验 024（部署与发布加固）spec.md 的需求质量——完整性、清晰度、一致性、边界。这是"需求的单元测试"，**不校验实现是否正确**。

## 完整性（Completeness）

- [x] CHK001 US1 容器安全基线是否要求全部 6 个服务（chat-api / admin-api / document-parser / gateway / admin-web / user-web）定义非特权用户并切换 USER、`read_only: true`、`cap_drop: [ALL]` + `no-new-privileges: true`（FR-001/004/005）？
- [x] CHK002 运行镜像是否基于最小化基础镜像（`slim-bookworm`，明确不追求 distroless）、且建立分层数与总体积基线并超阈告警（FR-002/003）？
- [x] CHK003 基础设施是否全部由代码定义（compose + `deploy/`）、配置清单是否含键名/用途/必填/来源/默认/范围/codeRef 七字段、部署是否拒绝未登记必填键并指出键名（FR-006/007/011）？
- [x] CHK004 密钥是否强制走 `deployment-secrets` 卷或外部源（仓库仅 `.env.example`）、配置变更是否可审计（操作者/时间/旧→新/受影响）且可回滚、漂移检测是否覆盖手工 `docker exec` 改卷（FR-008/009/010）？
- [x] CHK005 US2 是否要求制品具备 digest 与流水线一致、三项元数据齐全（版本+SHA+构建时间）、完整性校验、环境差异仅存配置层、缺失配置启动失败指明键名、dry-run 计划 diff、一键安装验证、晋级记录八项（FR-012~019）？
- [x] CHK006 灰度是否定义 `1%→10%→50%→100%` 四档 + 每档观察窗口与校验点、灰度期新旧版本在同一维度（错误率/延迟/吞吐）并排对比、自动回滚条件明确（触发指标 + 阈值 + 观察时长）且在预发环境实际验证过（FR-020/021/022）？
- [x] CHK007 回滚是否要求真实环境演练（禁 mock 替代）、数据变更与代码回滚兼容性有明确结论（可回滚 / 不可逆兜底）、耗时 ≤ 约定目标且有实测记录、回滚后关键指标恢复基线并留校验记录（FR-023/024/025/026）？
- [x] CHK008 特性开关是否登记属主/默认值/到期日期/清理计划四项 + 到期告警 + 属主离职转移流程、数据库变更先于代码发布 + 扩展-收缩三版本兼容 + 迁移幂等且不阻塞线上、发布检查单覆盖配置与依赖差异且每项强制执行人与结论（FR-027~033）？
- [x] CHK009 US5 是否成体系覆盖备份自动执行 + 加密与密钥异地 + 保留策略 + 恢复业务校验、跨区切换（MongoDB 副本集 + Redis RPO 声明）+ 切换权限收敛 + 一致性校验脚本、DR 预案与数据丢失/区域不可用两类演练、证书清单 + 外部拨测、值班表零空档 + 告警升级、水位分级告警 + 容量模型与扩容触发点（FR-034~052）？

## 一致性（Consistency）

- [x] CHK010 与 001 gatekeeper-governance 关系：配置变更审计、发布检查单结论、演练记录是否单向写入既有 `system_audit`，不新建平行审计存储（spec Assumptions / plan 跨特性关系表）？
- [x] CHK011 与 007 llm-gateway-resilience 关系：自动回滚触发条件（重试率/超时率/5xx）与灰度期新旧版本指标对比是否单向复用 007 已定义口径，不重复定义（FR-021/022）？
- [x] CHK012 与 022 security-hardening 边界：022 覆盖应用层安全（认证/授权/输入/数据）、024 覆盖部署层安全（容器/镜像/基础设施），密钥不入库以 022 约定为准，两者交界不重叠？
- [x] CHK013 与 008 ops-dashboard 关系：水位监控与分级告警（FR-049）、证书状态（FR-046）可否作为 008 驾驶舱数据源，但 024 不依赖 008 落地？
- [x] CHK014 对既有 `pass` 实践的处置：QF-811~815（制品与可追溯性）与 QF-837（备份可恢复）是"加固为强制门禁"而非重写；`docs/release-checklist` 是自托管扩展而非替换，是否已在 Non-Goals 与 plan Assumptions 双向声明（024↔既有）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK015 Non-Goals 是否写清六项排除：不引入 K8s、不做多区域 active-active、不做自动扩缩容、不强制 Vault 依赖、不追求 distroless、不全量服务灰度（基础设施与 dsh-runtime 不参与）？
- [x] CHK016 Edge Cases 十二项是否全部落回 FR 或 Assumptions：root-owned 卷用 init 容器 chown 而非回退 root、基础镜像切 distroless 退化、nginx 双重反代的灰度作用域、drop 列不可逆与迁移幂等、加密密钥异地、无副本集 RTO 如实声明、ACME 客户自有证书退化、开关无人清理的属主转移、检查单全套勾选糊弄、mock 演练不计入 RTO/RPO、read_only 下的 tmpfs 大小限定、非 root 写卷不放开根文件系统？
- [x] CHK017 Clarify 记录（Assumptions）是否明确：部署形态不变（13 服务/10 卷）、`mogo backup` 不重写、mock 结果不计入实测、首期单区 RTO 取决于备份恢复时长、nginx 灰度作用域限业务服务、TLS 手工放置退化为阈值告警 + 手工更换 runbook、001/007 复用不重复、41 项 blocked 是"基础设施未建立"而非"验证失败"？

## Notes

- 本清单为需求质量门禁；42 个缺陷中 41 项 `blocked` 表示"基础设施尚未建立"，本特性的验收主要看基础设施存在且可验证。
- 标记 `[x]` 仅代表"需求质量达标"（完整、清晰、一致、边界明确），**不代表实现完成**；tasks.md 中 119 项任务仍需逐项推进。
- 本特性的首个可独立验证切片为 US1（部署安全基线）——修复 QF-818 fail（唯一实证缺陷）并建立 `baseline-check.sh` 可复现验证，是后续 US2~US5 的底座。
