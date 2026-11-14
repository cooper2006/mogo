# 安全公告模板

> 022 FR-27。发布公告时复制本模板，替换所有 `<...>` 占位符。

---

# 安全公告：`<CVE-ID 或 MOGO-YYYY-NNN>` —— `<一句话摘要>`

**公告编号**：MOGO-<YYYY>-<NNN>
**发布日期**：<YYYY-MM-DD>
**严重度**：CRITICAL / HIGH / MEDIUM / LOW
**CVSS 3.1 基础分**：<X.X>
**状态**：已修复 / 修复中 / 已缓解

## 摘要

`<受影响组件>` 存在 `<问题类型>`，可导致 `<影响>`。

## 受影响版本

| 组件 | 首次引入 | 受影响范围 | 已修复于 |
|------|---------|-----------|---------|
| `<组件名>` | `<commit/tag>` | `<版本区间>` | `<commit/tag>` |

**不受影响**：`<版本区间>`

## 影响

`<攻击者可以利用该问题做什么>`

- 前提条件：`<是否需要认证、是否需要特定配置>`
- 影响面：`<数据泄露 / 权限提升 / 拒绝服务 / 远程代码执行>`
- 是否存在已知利用：`<是 / 否 / 不确定>`

## 修复

已修复版本：`<版本>`

升级方式：
```bash
# 容器镜像
docker pull ghcr.io/<owner>/<service>:<version>
# 或
git checkout <tag>
```

## 临时缓解

在升级到修复版本之前：

```bash
<可执行的缓解命令或配置片段>
```

## 时间线

| 事件 | 时间（UTC） |
|------|------------|
| 报告接收 | <YYYY-MM-DD> |
| 分级完成 | <YYYY-MM-DD> |
| 补丁提交 | <YYYY-MM-DD> |
| 补丁发布 | <YYYY-MM-DD> |
| 公告发布 | <YYYY-MM-DD> |

## 致谢

感谢 `<报告者姓名或代号>` 报告此问题。

## 后续

- 完整的漏洞管理流程见 [`docs/security/VULNERABILITY_POLICY.md`](./VULNERABILITY_POLICY.md)
- 残余风险与豁免登记见 [`docs/security/RESIDUAL_RISK.md`](./RESIDUAL_RISK.md)

---

*本公告遵循 [VULNERABILITY_POLICY.md §6](./VULNERABILITY_POLICY.md) 的披露时机要求：
CRITICAL 在补丁发布的同时公开；HIGH 及以下先公告后补丁。*
