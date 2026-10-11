# Security Policy

Please do not disclose suspected vulnerabilities in public issues. Use GitHub's
private vulnerability reporting feature for this repository. If that feature is
not available, email `support@himovo.com` before sharing details. Include the
affected commit or release, impact, reproduction steps and any suggested
mitigation, but never include real credentials or customer data.

Self-hosted operators are responsible for TLS termination, network access
controls, backups, and rotating every credential used by their deployment.
Never reuse values from example environment files in production. The Docker
Compose bootstrap generates deployment-specific application secrets and keeps
them in a persistent Docker volume.

Security fixes are provided for the current release line. Older releases may
require upgrading before a fix can be applied.

## 1. 修复时限基线 (Fix Time Baseline)

**QF-681**: 按严重级别定义修复时限。

| 严重级别 | 修复时限 | 响应时限 |
|----------|----------|----------|
| **Critical** | 7 天 | 24 小时 |
| **High** | 30 天 | 72 小时 |
| **Medium** | 90 天 | 14 天 |
| **Low** | 180 天 | 30 天 |

修复时限从漏洞报告确认之日起计算。如无法在时限内修复，需在发布记录中注明延期理由和新的预计修复日期。

## 2. 残余风险豁免 (Residual Risk Waivers)

**QF-682**: 残余风险必须有书面豁免与到期日。

建立漏洞豁免台账，每条豁免必须包含：

| 字段 | 说明 |
|------|------|
| 条目 ID | 唯一标识（如 `WVR-2026-001`） |
| 漏洞描述 | 漏洞类型和影响范围 |
| 豁免理由 | 为何接受此风险 |
| 补偿措施 | 已实施的缓解措施 |
| 到期日 | 豁免有效期（最长 180 天） |
| 批准人 | 批准豁免的人员 |

### 示例豁免

```markdown
| ID | 漏洞 | 理由 | 补偿措施 | 到期日 | 批准人 |
|----|------|------|----------|--------|--------|
| WVR-2026-001 | docling 无哈希 | 上游暂未提供 | 镜像签名验证 | 2027-04-11 | - |
```

## 3. 漏洞响应窗口 (Vulnerability Response Window)

**QF-702**: 定义响应窗口与协调披露时限。

| 严重级别 | 初始响应 | 修复版本 | 协调披露 |
|----------|----------|----------|----------|
| **Critical** | 24 小时 | 7 天 | 修复发布后 7 天 |
| **High** | 72 小时 | 30 天 | 修复发布后 14 天 |
| **Medium** | 14 天 | 90 天 | 修复发布后 30 天 |
| **Low** | 30 天 | 180 天 | 修复发布后 90 天 |

**协调披露 (Coordinated Disclosure)**: 漏洞报告者在修复版本发布后 90 天内保持保密。MOGO 团队在发布修复版本后公开披露漏洞详情。

## 4. 安全公告 (Security Advisories)

**QF-703**: 安全公告标明受影响与修复版本。

所有安全公告必须包含：

- **受影响范围**: 受影响的版本范围
- **修复版本**: 包含修复的最低版本
- **CVSS 评分**: 严重级别评估
- **缓解措施**: 临时缓解方案（如适用）

安全公告列表：[GitHub Security Advisories](https://github.com/cooper2006/mogo/security/advisories)

## 5. 依赖漏洞扫描 (Dependency Vulnerability Scanning)

**QF-679**: 流水线对依赖做漏洞扫描且高危阻断。

```bash
# 运行依赖漏洞扫描
pip-audit -r requirements.txt --ignore-vuln <known-issue-id>

# 阻断高危漏洞
if pip-audit -r requirements.txt --format json | jq -e '.vulns | length > 0 and all(.severity == "high" or .severity == "critical")' > /dev/null; then
  echo "::error::High or critical vulnerabilities found"
  exit 1
fi
```
