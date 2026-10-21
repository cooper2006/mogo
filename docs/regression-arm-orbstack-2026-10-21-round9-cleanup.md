# OrbStack 准生产环境回归 · Round 9 遗留清理（2026-10-21）

> 非独立回归轮次：专项清零 Round 8 报告 §九 的全部三项遗留待办。基线沿用 Round 8（admin-api 1008 / chat-api 2590 / document-parser 26 / deploy 189+7 skipped / 门禁全 exit 0 / pip-audit 0 条）。
> 产出提交：`2628084`（pyflakes F821 清零）+ `b460487`（CI pnpm 对齐 + execution-v3 免 NODE_PATH）。

---

## 一、结论

**三项遗留全部关闭**：

1. **pyflakes 存量提示**——甄别后发现 quality-gate 只阻断 `undefined name`（F821），全仓库真实缺陷仅 **3 处**，已全部修复并从**变换源头**根治其中 1 处（复发型缺陷）。其余 263 条为 unused import / f-string / shadow 类风格提示，CI 注释明示不阻断、单独跟踪，不在本轮范围。
2. **`test:execution-v3` 需 NODE_PATH**——真根因比 Round 8 记录的更严重：`tests/_dom_setup.ts` **硬编码了旧 checkout 的绝对路径** `/Users/cooper/Github/mogo/...`（提交 `437aa5a` 引入，已在 HEAD 里），任何别的机器/路径都解析不到 jsdom。已改为规范写法并显式声明 devDependencies。
3. **CI 用 `npm ci` 但无 package-lock.json**——两个 job（`runtime-guard.yml` web-build-guard、`dsh-migration-step1.yml` web-contracts）统一改走 pnpm。不回补 package-lock.json：仓库锁文件早在 `ccd94a6`（QF-012）归档废弃，双锁必然漂移。

## 二、F821 三处修复

| 位置 | 缺陷 | 修法 |
| --- | --- | --- |
| `services/admin-api/app/security/audit_events.py:325` | 审计保留期低于合规下限（<180 天）的告警分支用 `logger`，模块从未定义 → 运维一旦配低保留期即 NameError | 补 `logging.getLogger(__name__)`，对齐同目录 gatekeeper/kms/mfa_gate 惯例 |
| `services/chat-api/app/dsh_runtime/turn_runner.py:61` | 形参注解 `"TurnBackpressure | None"` 引用未导入符号；`from __future__ import annotations` 下运行时不求值不炸，但 `get_type_hints`/`get_signature` 求值即 NameError | 补直接导入（`turn_backpressure` 无循环依赖；gateway/application 已有同款先例） |
| `services/document-parser/app/core/pg_compat.py:2003` | `list_indexes` 返回注解残留 `AsyncIterator`——**根因在变换脚本** `scripts/pg/sync_pg_compat.py` 的 `to_sync()`：把 `async def`→`def`、导入行 `AsyncIterator`→`Iterator`，却漏改注解里的 `-> AsyncIterator[`，**每次再生成都会复发** | 在 `to_sync()` 源头补 `text.replace("-> AsyncIterator[", "-> Iterator[")` 后重新生成同步副本 |

## 三、web 流水线与 execution-v3

- **CI 改 pnpm**：两 job 用 `pnpm/action-setup@v6` + `version: "10.14.0"` + `cache: pnpm` + `cache-dependency-path: apps/*/pnpm-lock.yaml`，安装统一 `pnpm install --frozen-lockfile`（沿用同仓库 runtime-boundary-guard 既有写法）。
- **`_dom_setup.ts`**：删 `createRequire` + 绝对路径，直接 `import { JSDOM } from 'jsdom'`。
- **`package.json`**：devDependencies 显式加 `jsdom@26.1.0`（与 fabric 的 optionalDependency 同版本，锁文件零漂移，仅 optional 标记转常规）；`test:execution-v3` 的 esbuild 产物从 `/tmp` 挪进 `node_modules/.tmp/`（已 gitignore）——**ESM 外部模块解析锚定在产物所在目录**，产物在 `/tmp` 时即使装了 jsdom 也找不到。

## 四、验证矩阵

| 项 | 结果 |
| --- | --- |
| pyflakes `undefined name`（三服务） | **0**（修复前 3）✅ |
| `python -m compileall`（CI 同款） | exit 0 ✅ |
| `scripts/pg/sync_pg_compat.py` 再生成 + parity 守卫 | 一致 / **14 passed** ✅ |
| deploy 守卫 | **189 passed, 7 skipped** ✅ |
| 容器内三服务全量（新代码） | admin-api **1008** / chat-api **2590 + 8 deselected** / document-parser **26**，0 失败 ✅ |
| `pnpm install --frozen-lockfile` | user-web / admin-web 均 exit 0 ✅ |
| user-web CI 全序列 | test:code-platform ✅ / test:execution-v3 ✅（**免 NODE_PATH**）/ typecheck ✅ / build ✅ |
| admin-web | frozen install ✅ / build ✅（5.85s） |
| `check_dsh_upgrade_contract.py` / `check_open_source_hygiene.py` | exit 0 ✅ |
| 两个 workflow YAML | `yaml.safe_load` 解析通过 ✅ |

## 五、提交

| 提交 | 内容 |
| --- | --- |
| `2628084` | `fix(quality): 清零三服务 pyflakes F821 未定义名（Round 8 遗留待办）` —— 4 文件（`scripts/pg/sync_pg_compat.py`、`audit_events.py`、`turn_runner.py`、document-parser `pg_compat.py`） |
| `b460487` | `fix(ci,tests): web 流水线改走 pnpm 权威锁；execution-v3 免 NODE_PATH 直跑（Round 8 遗留待办）` —— 5 文件（两个 workflow、`package.json`、`pnpm-lock.yaml`、`_dom_setup.ts`） |

均已推送 `origin/main`。Round 8 §九 待办表至此全部关闭；Round 8 §十 的其余建议（端到端守卫、workflow 编排稳定性等）留待后续轮次。
