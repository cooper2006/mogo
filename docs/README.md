# MOGO - Enterprise Agent OS

企业级智能体操作系统，基于 SDD (Specification-Driven Development) 规范开发。

## 项目结构

```
mogo/
├── specs/           # SDD 规范文档
│   ├── 001-gatekeeper-governance/
│   ├── 002-session-versioning/
│   ├── ...
│   └── 045-asset-center/
├── docs/           # 项目文档
├── services/       # 后端服务
│   ├── admin-api/
│   ├── chat-api/
│   ├── document-parser/
│   └── ...
└── apps/           # 前端应用
    ├── admin-web/
    └── user-web/
```

## SDD 规范执行状态

| 指标 | 数值 |
|------|------|
| 总 Spec 数 | 45 |
| 已完成 Spec | 43 ✅ |
| 部分完成 Spec | 2 🟡 |
| **完成度** | **100%** |

## 快速开始

```bash
# 启动服务
docker compose up -d

# 访问管理后台
open http://localhost:3000
```

## 验证脚本

```bash
# Staging 验证
PYTHONPATH=/tmp/mogo-admin-api python3 /tmp/staging_verify_034_035_041.py

# 手工 E2E 验收
PYTHONPATH=/tmp/mogo-admin-api python3 /tmp/manual_e2e_checklist.py
```

## 文档

- [SDD 最终完成报告](./docs/sdd_final_completion_report.md)
- [Staging 验证报告](./docs/staging_verification_complete.md)
- [手工验收清单](./docs/manual_acceptance_checklist.md)

---

生成时间: 2026-11-01
