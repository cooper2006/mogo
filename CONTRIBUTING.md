# Contributing to MOVO

Contributions should be focused, modular, and covered by tests appropriate to
the change. Do not commit environment files, credentials, generated build
caches, uploaded documents, avatars, logs, or other runtime data.

By intentionally submitting a contribution, you agree to the contribution
terms in LICENSE, including use of the contribution in MOVO commercial products
and services. Do not submit code or assets that you do not have the right to
license under those terms.

## 分支模型 (Branching Model)

本仓库采用**受保护的主分支 + PR 单主干**模型（QF-878）：

| 分支 | 用途 | 生命周期 |
| --- | --- | --- |
| `main` | 唯一发布分支，始终可构建 | 长期存在，受保护，禁止直接推送 |
| `feat/<topic>` | 新功能开发 | 合并 PR 后 squash 或 merge commit，PR 关闭 |
| `fix/<topic>` | 缺陷修复 | 同上 |
| `docs/<topic>` | 文档变更 | 同上 |
| `refactor/<topic>` | 重构（无行为变更） | 同上 |
| `dependabot/*` | Dependabot 自动更新 | 由机器人创建，人工审核后合并 |

**禁止**：向 `main` 直接推送（GitHub 分支保护强制拒绝）。所有变更必须通过
Pull Request，至少一名他人评审通过 + 全部必需状态检查（Quality Gate）通过。

**命名约定**：小写 + 连字符，前缀（`feat/` `fix/` `docs/` `refactor/`）后跟
简短主题。例：`fix/document-parser-ocr-crash`。

## 优先级与严重级判定 (Priority & Severity Criteria)

报告缺陷或评审 PR 时按下列标尺定级（QF-890）：

### 优先级 (Priority)
| 级别 | 判定依据 |
| --- | --- |
| **P0** | 阻断交付：数据损坏、安全漏洞、核心流程不可用、构建或测试失败。必须在合并前修复。 |
| **P1** | 严重：主要功能降级、明显数据质量问题、CI 缺失关键检查。应在本轮迭代内修复。 |
| **P2** | 一般：影响体验、文档缺失、非关键告警。可在后续迭代处理。 |
| **P3** | 轻微：风格、命名、局部优化。可长期保留为技术债。 |

### 严重级 (Severity)
| 级别 | 判定依据 |
| --- | --- |
| **critical** | 数据丢失/损坏、凭证泄露、生产不可用 |
| **high** | 绕过权限、关键路径不可用、性能数量级劣化 |
| **medium** | 功能降级、非关键告警、文档与实际不一致 |
| **low** | 风格问题、局部优化、非阻塞建议 |
| **info** | 补充信息、设计讨论 |

### 一致性要求
- 缺陷定级须附判定依据（影响面 / 数据风险 / 有无绕过方式）。
- PR 描述中须标注是否引入 P0/P1 变更（触发额外的评审要求）。
- 优先级与严重级变更须在 issue/PR 评论中记录理由。

## 支持矩阵 (Supported Runtime Matrix)

声明的支持运行时与测试矩阵单点对齐（QF-886 / QF-895）：

| 组件 | 声明版本 | 定义位置 |
| --- | --- | --- |
| Python（后端三服务） | `^3.13` | `services/*/pyproject.toml` |
| Node.js（前端 + Runtime Host） | `22` | `.github/workflows/quality-gate.yml` `actions/setup-node` |
| pnpm | `10.14.0` | `.github/workflows/quality-gate.yml` `pnpm/action-setup` |
| Docker | Compose v2 | `docker-compose.yml` |

**单一来源原则**：运行时版本只在 `services/*/pyproject.toml` 与
`.github/workflows/quality-gate.yml` 各声明一次；Dockerfile 与 CI 矩阵
引用同一 ARG / setup-python 参数，禁止本地副本。

## 提交与评审流程

1. 从 `main` 拉出特性分支：`git checkout -b feat/<topic> main`
2. 提交前本地检查：
   ```bash
   python3 scripts/check_open_source_hygiene.py
   python -m compileall -q services/chat-api/app services/admin-api/app services/document-parser/app
   cd apps/user-web && pnpm install --frozen-lockfile && pnpm build && pnpm lint
   cd ../admin-web && pnpm install --frozen-lockfile && pnpm build && pnpm lint
   ```
3. 打开 PR，填写模板：描述用户可见行为、迁移影响、验证结果、配置变更。
4. **必需状态检查**：Quality Gate（`quality-gate.yml`）所有 job 通过。
5. **评审**：至少一名他人评审通过；P0/P1 变更需两名评审。
6. 合并后 squash 或 merge commit，删除源分支。

## 提交前检查

```bash
python3 scripts/check_open_source_hygiene.py
python -m compileall -q services/chat-api/app services/admin-api/app services/document-parser/app
cd apps/user-web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm build && pnpm lint
cd ../admin-web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm build && pnpm lint
```

Describe the user-visible behavior, migration impact, verification performed,
and any configuration changes. Keep new capabilities in focused modules rather
than extending already-large endpoint or UI files.

Use the pull request template and explicitly identify changes to public APIs,
stored data, environment variables, deployment topology or licensing. Security
vulnerabilities must follow SECURITY.md and must not be filed publicly.

## 包管理器

本仓库统一使用 **pnpm**（10.14.0）作为前端包管理器。CI 使用
`pnpm install --frozen-lockfile` 强制锁文件一致。

- 禁止提交 `package-lock.json`（npm 锁文件）—— 历史残留已归档至
  `docs/pending-review/stale-lockfiles-2026-10-11/`。
- 新增依赖请使用 `pnpm add` / `pnpm add -D`。
- 升级依赖请使用 `pnpm update` 或 `pnpm outdated` 检查。

## 许可证

本仓库采用 **Apache-2.0** 许可证，见根目录 `LICENSE`。

所有包元数据（`apps/*/package.json` 与 `services/*/pyproject.toml`）均声明
`license = "Apache-2.0"`，与根 `LICENSE` 保持一致（QF-912 / QF-019）。
