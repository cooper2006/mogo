# Implementation Plan: Security Hardening

**Branch**: `022-security-hardening` | **Date**: 2026-10-11 | **Spec**: [specs/022-security-hardening/spec.md](./spec.md)

**Input**: Feature specification from `specs/022-security-hardening/spec.md`

## Summary

QualityForge 审计发现 96 个 P0/P1 安全缺陷，分布在认证、授权、输入、数据、供应链 5 个子域。本特性为**缺口新特性**（非回溯固化），目标是建立生产级安全基线。

实施策略：
- **US1 口令与 MFA**：在 admin-api/chat-api 登录链路强制弱口令策略 + MFA 强制 + TOTP 防重放
- **US2 令牌与会话**：收敛 access token TTL 至 ≤ 1h，打通 refresh 链路，服务间独立凭证
- **US3 授权与权限最小化**：4 个 Dockerfile 非 root，gatekeeper 服务身份最小权限
- **US4 输入安全**：SSO 令牌 POST 换票、GET 无副作用、CORS 白名单
- **US5 数据安全**：HTTPS 强制、敏感字段加密、日志脱敏、审计留痕
- **US6 供应链**：依赖漏洞扫描阻断、构建权限分离、提交钩子阻止密钥

## Technical Context

**Language/Version**: Python 3.13（services/admin-api、services/chat-api、services/document-parser 沿用现有技术栈）；TypeScript（services/admin-web、services/user-web）

**Primary Dependencies**:
- FastAPI（后端框架，沿用）
- MongoDB（存储，沿用）
- `python-jose` / `PyJWT`（JWT 处理，沿用）
- `pyotp`（TOTP，沿用）
- `cryptography`（加密，新增依赖用于敏感字段加密）
- `pip-audit`（依赖漏洞扫描，新增 CI 工具）
- `osv-scanner`（OSV 数据库漏洞扫描，可选）
- Vault / KMS（可选集成，接口预留）

**Storage**: 沿用现有 MongoDB（不新增存储引擎）。新增集合：
- `mfa_used_steps`（TOTP used_step 持久化）
- `mfa_lockouts`（MFA 限流记录）
- `password_reset_tokens`（一次性临时凭据）
- `service_tokens`（服务间独立凭证）
- `data_map`（数据地图，个人信息字段标注）
- `audit_events`（审计事件，防篡改 + 分离存储）

**Testing**: pytest + httpx（后端沿用）；Vitest/Jest（前端沿用）；安全扫描工具（`pip-audit`、`pnpm audit`、`semgrep`）

**Target Platform**: Linux 自托管 Docker Compose（mogo 交付形态），Windows 安装形态通过同一镜像

**Project Type**: 多服务安全加固（横跨 backend + frontend + infrastructure）

**Performance Goals**:
- 登录链路（含 MFA 校验）p95 < 200ms（不含外部通道）
- 令牌校验 p95 < 5ms（本地 JWT 验证）
- 审计落库异步，不阻塞主流程
- CORS 预检响应 < 50ms

**Constraints**:
- 不改变现有认证架构（JWT + refresh token）
- 不引入外部 IDS/WAF
- 首期 KMS 用环境变量，Vault 为可选集成
- MFA 邮件通道未接入时降级为审计事件
- 容器非 root 改造不影响现有数据卷挂载路径（使用 `/app` 工作目录）

**Scale/Scope**:
- 5 个子域，29 条 FR
- 6 个用户故事
- 涉及 5 个服务（3 backend + 2 frontend）+ 4 个 Dockerfile + Docker Compose + CI/CD 流水线

## Constitution Check

| 原则 | 检查结果 |
|---|---|
| I. Specification-First | 通过：spec.md 已完成，本 plan 为规格产物 |
| II. Enterprise Production Readiness | 通过：生产级安全基线，P0/P1 缺陷清零 |
| III. Security and Data Protection | 通过：fail-closed；密钥不进仓库；审计全量 |
| IV. Cross-Platform and i18n | 通过：跨后端/前端/基础设施；中文 UI 文案不受影响 |
| V. Observability and Simplicity | 通过：审计事件结构化；声明式配置；环境变量驱动 |

## Project Structure

### Documentation (this feature)

```text
specs/022-security-hardening/
├── spec.md              # 特性规格（本目录）
├── plan.md              # 本文件
├── tasks.md             # 任务拆分
└── quickstart.md        # 启用与验证步骤
```

### Source Code (repository root)

```text
services/
├── admin-api/
│   ├── app/
│   │   ├── security/                         # 新增模块：安全基座
│   │   │   ├── __init__.py
│   │   │   ├── password_policy.py            # FR-1：弱口令策略
│   │   │   ├── mfa_policy.py                 # FR-2/3/4/5：MFA 强制/限流/防重放/通知
│   │   │   ├── kms.py                        # FR-19：KMS 集成接口（Vault 可选）
│   │   │   ├── encryption.py                 # FR-19：敏感字段加密（cryptography）
│   │   │   └── redaction.py                  # FR-20/21：日志脱敏/响应裁剪
│   │   ├── api/routes/
│   │   │   ├── auth.py                       # 修改：MFA 强制/重置强制改密/refresh 链路
│   │   │   ├── sso.py                        # 修改：FR-14 SSO 令牌 POST 换票
│   │   │   └── ...（FR-15 GET 无副作用端点改造）
│   │   ├── middleware/
│   │   │   ├── cors.py                       # 修改：FR-16 CORS 白名单
│   │   │   └── timeout.py                    # 新增：FR-9 空闲/绝对超时
│   │   └── deps.py                           # 修改：FR-11 服务身份校验
│   └── Dockerfile                            # 修改：FR-12 非 root
├── chat-api/
│   ├── app/
│   │   ├── security/                         # 同 admin-api 结构
│   │   ├── api/routes/auth.py                # 修改：FR-7 access token TTL
│   │   └── deps.py                           # 修改：FR-11 服务身份校验
│   └── Dockerfile                            # 修改：FR-12 非 root
├── document-parser/
│   ├── app/security/                         # 同上
│   └── Dockerfile                            # 修改：FR-12 非 root
├── admin-web/
│   ├── Dockerfile                            # 修改：FR-12 非 root
│   └── src/config/cors.ts                    # 新增：前端 CORS 配置（如适用）
└── user-web/
    └── (同 admin-web)

deploy/
├── docker-compose.yml                         # 修改：FR-12/13 安全上下文
└── nginx/
    └── nginx.conf                            # 新增：FR-17 HTTPS 强制/301 跳转

.github/workflows/
├── ci-security.yml                           # 新增：FR-25/26/28 安全 CI
└── release.yml                               # 修改：FR-27 不可变版本

data/
├── kms_keys/                                 # 新增：KMS 集成接口（首期环境变量）
│   └── README.md                             # KMS 集成说明
└── data-map.md                               # 新增：FR-24 数据地图
```

## Key Integration Points

1. **登录入口**：`admin-api/app/api/routes/auth.py` 与 `chat-api/app/api/routes/auth.py` 在登录链路中调用 `password_policy.validate()` + `mfa_policy.enforce()`
2. **令牌刷新**：`admin-api/app/api/routes/auth.py::/auth/refresh` 打通链路，实现一次性轮换（当前死代码）
3. **服务身份**：`admin-api/app/deps.py` 与 `chat-api/app/deps.py` 在 `get_authenticated_*` 中增加服务身份校验（token + tenantId/userId 双因子）
4. **gatekeeper 集成**：001 gatekeeper 的 `gatekeeper.evaluate()` 在服务身份路径中调用，做权限最小化校验
5. **Docker 非 root**：4 个 Dockerfile 新增 `USER appuser` 指令 + Docker Compose `user: "10001:10001"` + `security_opt`
6. **审计落点**：复用 001 gatekeeper 的审计体系（`gate_events`），扩展为 `audit_events` 集合（防篡改 + 分离存储）

## Open Questions（已 clarify 消解）

- OQ-1（MFA 通知）：**邮件/短信通道未接入时降级为审计事件**，`/auth/mfa/disable` 包含通知触发点，通道可用时发通知。
- OQ-2（KMS）：**首期环境变量 + KMS 集成接口预留**（`KMSProvider` 抽象），Vault 为可选集成。
- OQ-3（HTTPS）：**TLS 终结在反向代理层**（nginx/traefik），应用层通过 `SECURE_PROXY_SSL_HEADER` 感知。
- OQ-4（服务间加密）：**首期内网隔离 + 独立凭证**，mTLS 为可选增强。
- OQ-5（CORS 白名单）：**环境变量配置**（`CORS_ORIGINS`），默认空，生产按租户配置。

## 实施顺序

1. **US1（口令与 MFA）** — 登录链路加固，独立可测
2. **US2（令牌与会话）** — 令牌生命周期，依赖 US1 的登录链路
3. **US3（授权与权限最小化）** — Docker 非 root + 服务身份最小权限
4. **US4（输入安全）** — SSO/GET/CORS 加固，可独立并行
5. **US5（数据安全与加密）** — HTTPS/加密/日志脱敏/审计，依赖 US1-4
6. **US6（供应链安全）** — CI/CD 安全，依赖 US3（容器非 root）

## 与现有特性关系

- **001 gatekeeper-governance**：022 的 FR-11（服务身份最小化）建立在 001 的权限码模型之上；022 加固后的事件 100% 过 001 审计
- **006 position-rbac-admin**：006 的岗位角色是 022 FR-11（服务身份最小权限）的预设组基础
- **017 three-scope-memory**：017 的 scope 可见性是 022 FR-11（跨租户越权拒绝）的语义基础
- **020 platform-multi-tenancy**：020 的租户隔离是 022 FR-11（tenantId 一致性校验）的基础

## 下一步

按 SDD 路径：
1. `/speckit-checklist`（需求质量门禁）
2. `/speckit-tasks`（本文件已包含任务拆分）
3. `/speckit-analyze`（一致性检查）
4. `/speckit-implement`
5. `/speckit-converge`
