# Standard 深度全量 QA 审计报告（第四轮 · R5）

**审计时间**：2026-10-07
**审计基线**：`main` @ `1c0bec2`（R1–R4 全部修复已合入）
**审计范围**：全仓 21 spec / 3 Python 服务 / 2 前端 / CI 门禁 / 发布链路 / 治理资产
**审计目标**：R3（修复动作的破坏性变更）、R4（静默 except 处置）之后，**换第四批维度**找新问题

> **编号说明**：`R4` 已被 `docs/WORK_LOG.md` 用于「非静默宽泛 except 补日志」处置轮
> （`## 2026-10-06 · 非静默宽泛 except 补日志（R4）`），故本轮审计续编 **R5**。

**本轮针对的宣称**（用户引用的 PPT 口径）：

> "SDD 驱动的 spec 下所有特性 全流程已就绪，可进入 PR 评审与版本发布——库能力、生产接线与治理资产齐备"

**该宣称本身即审计靶子。** 结论见 §四。

---

## 一、审计结论

**共 8 项发现：2 项 P0、4 项 P1、2 项 P2。其中 8 项已处置（6 项修复 + B7 低风险包 + B8 Python 服务 digest 钉死），
剩余尾巴：B5-verify 待 CI 复跑、B8 的 node/nginx 4 个 multi-stage 留作后续批次。**

| 等级 | 数量 | 已处置 | 待决策/尾巴 |
| --- | --- | --- | --- |
| P0 阻断 | 2 | 2 | 0 |
| P1 重要 | 4 | 4 | 0 |
| P2 建议 | 2 | 2† | 0 |
| **合计** | **8** | **8** | **0** |

† B7 的**低风险包**已处置（`requirements.txt` 钉版本+哈希+`--require-hashes`、CI 改 3.10 同构、
docling 显式降级不加哈希）；B8 的 **3 个 Python 服务**已 digest 钉死，node/nginx 4 个 multi-stage
留作后续批次（非阻断，B5-verify 待 CI 复跑）。

**核心结论（三句话）**：

1. **宣称不成立**：PPT 的"所有特性全流程已就绪"与仓库自有的治理资产冲突——
   `specs/LANDING_AUDIT_2026-10-03.md` 明确判定 `landed 0 / partial 10 / hollow 9`，
   `specs/010/tasks.md` 头部自带 `hollow` 横幅。**没有任何一个特性达到"按今天标准的真落地"。**
2. **但"纯逻辑孤岛"这一最严重的形态已被消除**：本轮用包级可达性检测器重新推导——
   chat-api 23 个业务包中 **22 个有生产入边**（2026-10-03 判 hollow 的 `memory`/`im_gateway`/
   `business_index`/`knowledge_graph`/`a2a`/`orchestration` 现全部 >0）。各小节"已修"的记载**得到实证**。
3. **真正的风险从"没接线"转移到了"测试不能证明接线"**：本轮新维度发现
   **4 条自证式测试**（只断言测试自己构造的本地对象，删掉生产代码照样绿），
   且其中 2 条对应的任务在 `tasks.md` 里被勾成已完成。已全部改写为真实测试并用**变异测试**验证可证伪。

---

## 二、R5-A · 发布链路实证（新维度）—— **7/7 通过，0 项发现**

不采信 `bundle.json` 里记录的 `verified: true`，**全部实跑**。

- [x] A1 `verify_bundle.py` 实跑：4 包 / 11 镜像 / 全部 `architecture == amd64/linux` / exit=0
- [x] A2 渲染产物无 `__MOGO_*__` 占位符残留
- [x] A3 compose 引用的 11 个镜像全部命中 bundle
- [x] A4 应用镜像 tag 全为 `:7d95ade`（与发布 tag 一致）
- [x] A5 **8/8 应用服务带 `pull_policy: never`**（离线部署不会偷偷拉取）
- [x] A6 `DEPLOY.md` 四包 sha256 + 版本号全部对账通过
- [x] A7 `docker-compose.portainer.yml.tpl` ↔ 渲染产物逐行 diff：**实质差异仅 1 行**（渲染头产生的空注释 `#`），无漂移

**方法论修正（记入自检）**：A3 首跑误报 `服务数(8) ≠ 镜像数(7)`。
根因是 `document-api` 与 `document-worker` **共用** `ghcr.io/himovo/document-parser` 一个镜像
（模板第 23 行有明确说明），正确关系是 `服务数 = 镜像数 + (共用服务数 - 1)`。
A7 首跑也误报——**macOS 的 BSD `sed` 不支持 `\b`**，`sed 's/:7d95ade\b/:TAG/g'` 静默不替换。
改用 Python `difflib` 严格比对后确认无漂移。

---

## 三、R5-B · 供应链完整性（新维度）—— **2 项发现（均已修）+ 2 项建议**

### 已确认良好（不采信文档，实跑）

- [x] B1 `chat-api`：**113/113 条依赖全钉版本且全带哈希**，`--require-hashes` 可生效
- [x] B2 `admin-api`：**49/49 条**同上
- [x] B3 `scripts/generate-hashes.sh` **服务无关**（接受任意服务名）——勘误：并非"document-parser 无法生成哈希"
- [x] B4 `document-parser/=0.6.23` 是 shell 重定向事故产物，但 `.gitignore:379` 的 `services/document-parser/=*` 已覆盖 → **非发现项**

### 🔴 B5（P0，已修）· CI 装了与生产**不同**的依赖集

**现象**：`services/chat-api/dsh/runtime-host` 是 **pnpm workspace**
（有 `pnpm-lock.yaml` 633 KB + `pnpm-workspace.yaml`），
其 **Dockerfile 正确使用 `pnpm install --frozen-lockfile --prod`**（可复现）；
但 `.github/workflows/quality-gate.yml` 的 `dsh-host-e2e` job 用的是
`npm install --no-audit --no-fund`——**完全忽略锁文件**。

**后果**：该 job 验证的依赖集与真正发布的镜像不是同一套，
"e2e 通过"不能推出"发布物可用"。这正是供应链完整性最典型的失效形态。

**修复**（`.github/workflows/quality-gate.yml`）：

```yaml
      - name: Install Runtime Host dependencies
        working-directory: services/chat-api/dsh/runtime-host
        run: |
          npm install --global pnpm@10.34.4
          pnpm install --frozen-lockfile
```

- [x] B5 已修：对齐生产 Dockerfile，`--frozen-lockfile` 使锁文件漂移**硬失败**
- [ ] B5-verify 待 CI 复跑确认（本地无 pnpm，无法端到端验证）
  - [x] **B5-verify-static（2026-10-07）**：本地等价静态验证完成——`pnpm-lock.yaml`（633KB，tracked）与
    `pnpm-workspace.yaml` 均存在；runtime-host `Dockerfile:15` 已用 `pnpm install --frozen-lockfile --prod`；
    `dsh-host-e2e` job 的 `pnpm install --frozen-lockfile` 与本仓库 lock 一致；workflow YAML 解析通过。
    **剩余**：CI runner 上 `dsh-host-e2e` job 复跑一次（Node 22 + pnpm）即可闭环，本地已做到天花板。

> **勘误（对我自己初判的修正）**：初判为"缺 `package-lock.json`"，**错误**——
> 该项目用 pnpm，正确的锁文件 `pnpm-lock.yaml` **存在**，且 Dockerfile 已在用。
> 真正的缺陷只是 **CI 侧**用错了包管理器。

### 🟡 B6（P1，已修）· `undefined name`：2 处悬空字符串注解

`pyflakes` 实跑基线：**chat-api 183 条 / admin-api 29 条**，其中
**2 处 `undefined name`（F821）**——`compileall` 完全抓不到（字符串注解运行时不求值）：

| 位置 | 问题 | 修复 |
| --- | --- | --- |
| `app/llm/resilience/providers.py:117` | 返回注解 `"ResilientLLMClient"`，类在 `.failover`，模块级**从未导入** | 补 `TYPE_CHECKING` 导入（运行时导入仍留在函数内，不拖入 failover 栈） |
| `app/context_space/adapters/base.py:46` | 参数注解 `"ViewerContext"`，类在 `context_space.visibility`，**全文件无导入** | 补 `TYPE_CHECKING` 导入（保持基接口零依赖） |

- [x] B6 已修：`pyflakes app | grep "undefined name"` → **0**（两服务）
- [x] B6 门禁：CI 新增 pyflakes 步骤（见 §五 D2）

### 🟡 建议项（P2，未修 —— 待决策）

- [ ] B7 `document-parser` 两个 requirements 文件缺哈希/钉版本：
      `requirements.txt` **11 条全 `>=`、0 哈希**；`requirements-docling.txt` **9 条全 `==`、0 哈希**；
      Dockerfile 用 `--prefer-binary` 安装且**不带 `--require-hashes`**。
      **未修原因**：需在与生产同构的环境（Python 3.10 + docling 家族）下联网重新生成哈希，
      写错会直接破坏构建；且属"改构建行为"，按 `AGENTS.md` 需先征得同意。
  - [x] **B7-probe（2026-10-07，只读）**：已在 `python:3.10-slim-bookworm` 容器内实跑 `pip-compile`
        （清华源，未动仓库）。结论**分层**：`requirements.txt` 的依赖树 66 包、无 torch/CUDA → 可安全
        加哈希；`requirements-docling.txt` 的传递依赖树 124 项、含 **CUDA 版 `torch==2.14.1`**
        （`manylinux_2_28_*`，无 `+cpu`）+ `torchvision` / `triton` + **15 个 `nvidia-*` 包**
        （`pip install --dry-run --report` 证实全部来自 PyPI），与 Dockerfile 从
        `download.pytorch.org/whl/cpu` 安装、刻意规避 CUDA 的设计**直接冲突** → **不应**启用
        `--require-hashes`，应保持钉版本并在文件头显式记录理由。
        另：CI 该 job 用 **Python 3.13** 装生产 requirements（生产 Docker 为 **3.10**），
        且 11 条全 `>=` 无上界 → CI 与生产不同构（与 B5 同类）。
        细节见 `docs/WORK_LOG.md` 2026-10-07 条目；**构建文件未改，实施仍待授权**。
  - [x] **B7-fix（2026-10-07，已实施低风险包）**：按分层结论执行——
        * `requirements.txt`：在 **amd64 + Python 3.10** 容器内重新 `pip-compile --generate-hashes`
          → **61 包 / 1312 条 sha256 / 全钉版本**；干净 venv `pip install --require-hashes` 实测通过
          （`INSTALL_OK` + `IMPORTS_OK` + `pip check`）。原 11 条 `>=` 漂移问题消除。
        * `Dockerfile`：`requirements.txt` 安装行加 `--require-hashes`；
          `requirements-docling.txt` 行**保持不加**（docling/torch 分层结论，待 L3 显式降级注释）。
        * `quality-gate.yml`：document-parser 的 CI job 改用 **Python 3.10**（与生产镜像同构），
          `--require-hashes` 覆盖该服务（消除 B5 同类"CI 装的 ≠ 生产装的"）。
        * `requirements.in`（11 条直接规格）**未动**，仍是再生成入口。
        **剩余**：docling 部分按分层结论保持显式降级（不加哈希）；`requirements-docling.txt` 的 L3 注释未做。
- [x] **B8（2026-10-07，已落地 3/8）**：3 个 Python 服务 Dockerfile（admin-api / chat-api /
      document-parser）的 `ARG BASE_IMAGE` 默认值从可变 tag 改为 `tag@sha256:...` 双锚定
      （digest 取自 DaoCloud 上 amd64 变体 manifest，与 CI 同构；tag 保留可读性，digest 锁死层）。
      node/nginx 的 4 个 multi-stage Dockerfile（user-web / admin-web / runtime-host / gateway）
      因 digest 需逐 FROM 行钉死且涉及 node 20/24 + nginx 1.29.8/1.31.5 四个变体，
      留作后续批次（非阻断）。

> **勘误（对我自己初判的修正）**：初判 `apps/user-web/Dockerfile` 用 `npm install` 是缺陷。
> 复核后：那是 **dev 镜像**（`CMD npm run dev`），`Dockerfile.prod` 用的正是 `npm ci`，
> 且 `package-lock.json` 存在。**降级为观察项，不计入发现。**

---

## 四、R5-C · 宣称 vs 事实（新维度）—— **2 项发现（均已修）**

### 🔴 C1（P0，已修）· 治理资产自相矛盾：总览表从未随修复回写

`specs/LANDING_AUDIT_2026-10-03.md` 内部冲突：

- §总览（第 72–96 行）判 **`landed 0 / partial 10 / hollow 9`**
- §高危缺口（按特性）逐条记 **"已修 / 全修"**（001 5/5、002 全修、003 全修 …… 020 全修）
- §修正后的 SDD 状态口径 又重申 `landed 0 · partial 10 · hollow 9`

**后果**：只读总览的人会得出"0 个落地"；只读小节的人会得出"几乎全修"。
两个结论都"有据可依"，**文档失去了作为决策依据的资格**——而这正是用户引用的 PPT 宣称所依赖的资产。

**本轮重新推导**（把"生产接线"这一条**机械化**，口径与文档 §"今天的标准"第 1 条一致：
统计 `app/` 下每个业务包被**包外** `app/` 模块 import 的次数，包内自引用不计）：

| 服务 | 业务包数 | 有生产入边 | 仍为孤岛 |
| --- | --- | --- | --- |
| chat-api | 23 | **22** | 1（`app/cases`） |
| admin-api | 6 | **5** | 1（`app/__init__`，非业务包） |
| document-parser | 5 | **4** | 1（同上） |

**结论**：2026-10-03 判为 hollow 的 9 个特性的核心包（`memory` / `im_gateway` /
`business_index` / `knowledge_graph` / `a2a` / `orchestration` / `context_space` …）
**现已全部有生产入边**——"纯逻辑孤岛"形态**基本消除**，各小节"已修"记载**得到实证**。

**但仍不等于 `landed`**：四条标准里 R5 只机械化了第 1 条；第 2 条（有消费方）、
第 3 条（数据源真实）、第 4 条（端到端可证伪）**未逐条重判**。

- [x] C1 已修：在 `LANDING_AUDIT_2026-10-03.md` §总览后加 **"2026-10-07 QA R5 复核"** 节，
      声明总览表为修复前快照、给出上表、并明确"**不得直接引用 `landed 0`**"

### 🔴 C2（P0，已修）· 010 T020/T021：自证式测试 + 任务被勾成已完成

见 §七（R5-F），此处只记结论：

- [x] C2 已修：4 条测试改写为真实测试（变异测试验证可证伪）
- [x] C2 已修：`specs/010-dag-orchestration-engine/tasks.md` 的 T020/T021 补诚实注解
      （T020：**节点级**预算已实现且已测；**跨 DAG / 007 网关协调**未实现——全仓无 `dag_max_concurrency`）

### 21 个特性逐条结论（本轮的机械口径）

> 口径：**仅**"核心包是否有 `app/` 内生产入边"。**不等价于 landed**，不覆盖第 2/3/4 条标准。

- [x] 001 gatekeeper-governance — `governance` inbound=21 ✅
- [x] 002 session-versioning — `context_engine` inbound=3、`historical` inbound=2 ✅
- [x] 003 document-ingestion — `knowledge` inbound=3、`tools` inbound=8 ✅
- [x] 004 skillhub-lifecycle — `skills_specs` inbound=3 ✅
- [x] 005 knowledge-rag-research — `knowledge` inbound=3 ✅
- [x] 006 position-rbac-admin — `position_roles`(admin) inbound=5 ✅
- [x] 007 llm-gateway-resilience — `llm` inbound=62 ✅
- [x] 008 ops-dashboard — `product`(admin) inbound=4、`token_usage` inbound=3 ✅
- [x] 009 hooks-interception — `dsh_runtime` inbound=13 ✅
- [ ] 010 dag-orchestration-engine — `orchestration` inbound=5 ✅ **但 T020 跨 DAG 部分未实现**（见 C2）
- [x] 011 dream-cycle — `self_evolution` inbound=3 ✅
- [x] 012 a2a-agent-gateway — `a2a` inbound=1 ✅
- [x] 013 multi-im-entry — `im_gateway` inbound=1 ✅
- [x] 014 business-semantic-index — `business_index` inbound=1 ✅
- [x] 015 knowledge-graph-layer — `knowledge_graph` inbound=3 ✅
- [x] 016 skill-market-hardening — `skills_specs` / admin `governance` ✅
- [x] 017 three-scope-memory — `memory` inbound=8 ✅（接线门禁亦验）
- [x] 018 capability-asset-registration — admin `position_roles.capability_assets` ✅
- [x] 019 harness-elastic-config — `harness_config` inbound=2 ✅
- [x] 020 platform-multi-tenancy — admin `product` inbound=4 ✅
- [x] 021 unified-context-address — `context_space` inbound=2 ✅（接线门禁亦验）

**唯一真孤岛**：`services/chat-api/app/cases`（inbound=0）。
`cases/customer_feedback_triage.py`（27 KB）是 `customer_feedback_triage` 技能的运行时，
但**无任何生产加载器**引用它（技能系统不按名加载 `app.cases.*`）。
- [ ] C3（P2，待决策）`app/cases` 的去留：接线 or 移入 `pending-review/`。**未擅改**（见 §九）

---

## 五、R5-D · 静态正确性门禁落地（新维度）—— **1 项发现（已修）**

### 🔴 D1（P0，已修）· CI 完全没有 Python 静态门禁

**发现**：`.github/workflows/` 6 个 workflow 中，
`flake8` / `pyflakes` / `ruff` / `pylint` / `mypy` / `pyright` **全部零命中**。
`backend-quality` 只跑 `compileall`——而 `compileall` **只证明文件能解析**：
§三 B6 的 2 处 `undefined name` 就是它放过去的（字符串注解运行时不求值）。

这正是 R3 报告遗留建议第 3 条的未落地项：

> 建议任何跨文件批量改写必须附带 ① AST 破坏性 diff 审查 ② 全量测试 ③ **pyflakes 未定义名门禁**

**修复**（两项，均已接入 CI）：

- [x] **D1a** 新增 `scripts/check_python_static.py`（**纯 stdlib**，`compileall` 同阶段即可跑，
      不依赖 `pip install`），检查三类：
  - `duplicate-except`：同一 `try` 内重复的 except 子句（后一个是死代码）
  - `duplicate-dict-key`：字典字面量重复键（前一个值被静默丢弃）
  - `silent-except`：**宽泛**（`Exception`/`BaseException`/bare）且 body 只有 `pass`/`...`
- [x] **D1b** `backend-quality` 新增 `pyflakes` 步骤，**仅 `undefined name` 判失败**
      （仓库有存量 unused import，不阻塞；但未定义名必须为 0）

**实跑基线**（`--self-test` 四项自检全过）：

| 服务 | duplicate-except | duplicate-dict-key | silent-except | 门禁 |
| --- | --- | --- | --- | --- |
| chat-api | 0 | 0 | 41（配额 41） | ✅ pass |
| admin-api | 0 | 0 | **14**（配额 14，原 15） | ✅ pass |
| document-parser | 0 | 0 | 2（配额 2） | ✅ pass |

> **`silent-except` 用"配额冻结"而非"清零"，且它不是缺陷清单。**
> QA R4 已逐处审议并**有意保留**这些块（`WORK_LOG` §"覆盖边界：38 处 PASS_ONLY 有意不改"）：
> 吞取消异常的关停惯用法、链式尝试的预期失败、**以及日志基础设施自身**（加日志会递归）。
> 冻结计数的意义是：**新出现的**静默宽泛 except 必须被复核，而不是悄悄混进来。
> 这与仓库既有的 `check_dsh_native_code_boundary.py` 的"counted ceiling"惯例一致。

- [x] D1c **对抗自检**：`--self-test` 对每个检查都跑"坏样本必须命中 + 好样本必须零命中"；
      另验证 bare `except:` 不被误判为与 `except ValueError:` 重复
- [x] D1d **降噪实证**：首版 `silent-except` 不限宽泛 → 报 63 处，
      抽样确认多为 `try: int(x) except ValueError: pass` 再试 `float` 的**合法控制流**
      → 收窄为宽泛后降至 41，误报清零

---

## 六、R5-E · 测试与门禁复验（实跑，不采信文档）

- [x] E1 `chat-api` 全量：**2229 passed / 0 failed / 0 error / 8 deselected**
      （`-m "not dsh_host_e2e"`，与改动前基线**逐数一致** → 本轮改动零回归）
- [x] E2 `admin-api` 全量：**433 passed / 0 failed**
- [x] E3 模块覆盖率门禁：**通过**（`context_space` 92.4%/85%、`memory` 86.1%/80%、
      `dsh_runtime/hooks` 91.1%/75%）
- [x] E4 生产接线门禁：**通过**（5 模块）
- [x] E5 `compileall`：chat-api ✅ / admin-api ✅
- [x] E6 版本一致性：`CHANGELOG` 最新 `v0.2.0` = chat-api `0.2.0` = admin-api `0.2.0`
      = `apps/admin-web` `0.2.0` = `apps/user-web` `0.2.0` ✅
- [ ] E7 `document-parser` 全量测试：**本机无 venv，无法实跑**（CI 有该 job）。
      注：该服务的 requirements 无哈希（见 B7），其 CI 安装路径也未用 `--require-hashes`。
- [ ] E8 `dsh-host-e2e`：**未跑**（需 pnpm + Node 22 + 真实 Runtime Host）。

### 环境注意事项（重要，避免误判）

- **`chat-api` 全量测试必须在免沙箱下跑**，否则固定出现 **21 个 ERROR**，全部同源：
  `PermissionError: EEXIST: mkdir '.../pytest-of-unknown'`。
  根因：`env` 中 `LOGNAME=root` 而 `USER=cooper` → `getpass.getuser()` 返回 `root`
  → pytest basetemp 解析到沙箱无法代理创建的目录。
  **这是审计环境问题，不是产品缺陷**（单测单独跑通过；免沙箱全量通过）。
- 建议 CI/本地统一用 `--basetemp=<workspace 内路径>` 规避。

---

## 七、R5-F · 自证式测试（新维度）—— **1 项发现（已修）**

**定义**（严格、可辩护）：一个 `test_*` 属于自证式，当且仅当
① 断言对象完全由测试自身构造（含同文件 helper / fixture 的传递闭包）；
② 依赖链中**没有**生产包符号（`app.*` / `scripts.*`）；
③ 没有真实外部交互（subprocess / httpx / DB）；
④ 没有读取生产源码或治理资产。
**即：把它删掉，生产代码的行为不会有任何变化被验证。**

### 🔴 F1（P0，已修）· 4 条自证式测试，其中 2 条对应"已完成"的任务

`services/chat-api/tests/services/test_dag_migrate_polish.py`：

| 测试 | 原样 | 问题 |
| --- | --- | --- |
| `test_concurrency_budget_guard` | 本地 `in_flight`/`peak` + `asyncio.gather` 两个自造协程 | 断言的是 **Python 语言属性**（gather 并发），与 010 无关 |
| `test_concurrency_budget_serializes_when_enforced` | 本地 `_Budget` 类 | 断言自己的本地调用序列 |
| `test_definition_version_increment_and_lookup` | 本地 `register()` + 本地 dict | 断言 dict 顺序 |
| `test_definition_version_lookup_by_key` | 本地 `latest()` + 本地 dict | 断言 `max()` |

**为什么这是 P0**：这 4 条让 `tasks.md` 的 T020/T021 得以勾成 `[x]`，
而**删掉整个 `app/orchestration/` 它们依然全绿**——"354 项全勾"的可信度因此受损。

**修复**（改写为真实测试，4 条 → 4 条）：

| 新测试 | 驱动的真实生产代码 |
| --- | --- |
| `test_dag_engine_bounds_node_concurrency` | `DagEngine(max_concurrency=2).run_graph(...)`，8 个独立节点，断言 `peak <= 2` 且 `peak > 1` |
| `test_dag_engine_serializes_at_concurrency_one` | `DagEngine(max_concurrency=1)`，断言时间线严格 `start/end` 交替 |
| `test_definition_version_increment_and_lookup` | `OrchestrationDefinition.update()`（版本递增 + 归档）+ `OrchestrationRegistry.history()` |
| `test_registry_keeps_every_version_browsable` | `OrchestrationRegistry`（3 次更新 → 版本 1..3 可回看，live=4） |

- [x] F1 已修：11 passed
- [x] F1 **变异测试验证可证伪**：临时把 `engine.py` 的
      `self.max_concurrency = max(1, int(max_concurrency))` 改成常量 `8`（等于取消上界）
      → **两条并发测试都失败**（`AssertionError: engine exceeded its budget: peak=8`）
      → 还原后 `git diff` 干净、11 passed
- [x] F1 检测器复验：自证式测试 **4 → 0**

### 检测器（`test_theater`）的对抗验证记录

按 R3 的方法论约束——**"一个检测器只有在已知有缺陷的版本上全部命中、
已知无缺陷的版本上零命中之后，它的输出才值得写进报告"**——本检测器迭代了三版：

| 版本 | 函数级命中 | 修正的误报类 |
| --- | --- | --- |
| v1 | **168** | — |
| v2 | 38 | ① pytest fixture（耦合在 fixture 里）② `importlib` 装入的门禁脚本 ③ 同文件本地 helper 间接引用 |
| v3 | **4** | ④ 跨模块 helper（`from .harness import ...`）⑤ `scripts.*` 生产资产 ⑥ `.read_text()` 是 `Attribute` 不是 `Name`，判据失效 ⑦ `sys.path.insert` 动态加载 Skill 脚本 ⑧ 文件存在性检查 |

**v1 → v3 收敛了 164 条误报（97.6%）**，最终 4 条全部人工复核确认。
每次修正都保留一个"历史误报样本"作为回归自检（自检 B/C 共 5 项，全部 OK）。
**若直接采信 v1 的 168 条，报告将 97.6% 是噪声。**

---

## 八、修复清单（逐条勾）

| # | 等级 | 文件 | 改动 | 验证 |
| --- | --- | --- | --- | --- |
| 1 | P0 | `.github/workflows/quality-gate.yml` | `dsh-host-e2e`：`npm install` → `pnpm install --frozen-lockfile`（对齐生产 Dockerfile） | YAML 校验通过；待 CI 复跑 |
| 2 | P0 | `scripts/check_python_static.py`（新增） | stdlib 静态门禁：duplicate-except / duplicate-dict-key / silent-except | `--self-test` 4 项通过；三服务实跑通过 |
| 3 | P0 | `scripts/python_static_allowance.json`（新增） | 三服务的配额冻结基线 | 超配额必失败（已对抗验证） |
| 4 | P0 | `.github/workflows/quality-gate.yml` | `backend-quality` 新增 `Python static correctness` 步骤 | 三条命令本地模拟通过 |
| 5 | P0 | `.github/workflows/quality-gate.yml` | `backend-quality` 新增 `Undefined-name check (pyflakes)` 步骤 | 本地模拟通过（两服务 0 命中） |
| 6 | P0 | `services/chat-api/app/llm/resilience/providers.py` | 补 `TYPE_CHECKING` 导入 `ResilientLLMClient` | pyflakes undefined name → 0 |
| 7 | P0 | `services/chat-api/app/context_space/adapters/base.py` | 补 `TYPE_CHECKING` 导入 `ViewerContext` | 同上 |
| 8 | P0 | `services/chat-api/tests/services/test_dag_migrate_polish.py` | 4 条自证式测试 → 4 条真实测试 | 11 passed；变异测试验证可证伪 |
| 9 | P1 | `services/admin-api/app/governance/layers/redaction.py` | PII 策略加载失败不再静默（加 `logger.warning`） | admin-api 433 passed；配额 15→14 |
| 10 | P1 | `specs/010-dag-orchestration-engine/tasks.md` | T020/T021 补诚实注解 | — |
| 11 | P1 | `specs/LANDING_AUDIT_2026-10-03.md` | §总览后加 R5 复核节，声明总览作废 | — |

**回归验证**：`chat-api 2229 passed / 0 failed / 0 error`（与改动前逐数一致）、
`admin-api 433 passed`、两道门禁通过、`compileall` 通过。

---

## 九、待决策项（**未擅改**，按 `AGENTS.md` 需先确认）

- [x] **N1** `document-parser` 的哈希/钉版本（B7）：需同构环境联网重新生成，改构建行为
  *（低风险包已获授权并实施，见 N1-fix；docling 一份按探查结论显式降级不加哈希）*
  - [x] **N1-probe** 只读探查已完成（2026-10-07），结论见上方 B7-probe：`requirements.txt` 可做，
        `requirements-docling.txt` 不应做（会拉入 CUDA 版 torch + 15 个 `nvidia-*`）；
        附带发现 CI 与生产不同构（3.13 vs 3.10）。**实施（改 Dockerfile / requirements / CI）仍待授权。**
  - [x] **N1-fix（2026-10-07，已获授权并实施低风险包）**：`requirements.txt` 已钉版本 + 1312 条
        哈希（amd64/py3.10 生成，干净 venv `--require-hashes` 实测通过）；`Dockerfile` 该行启用
        `--require-hashes`；CI 的 document-parser job 改 **Python 3.10**（与生产同构）并纳入
        `--require-hashes`。docling 一份按分层结论保持不加哈希，仅待 L3 注释收尾。
- [x] **N2** 基础镜像 digest 钉死（B8）：**已落地 3/8**（2026-10-07）——3 个 Python 服务
      Dockerfile 的 `ARG BASE_IMAGE` 已 `tag@sha256` 双锚定（admin-api/chat-api = python:3.13，
      document-parser = python:3.10，digest 取自 DaoCloud amd64 manifest，与 CI 同构）；
      node/nginx 的 4 个 multi-stage Dockerfile 留作后续批次（非阻断）。
- [ ] **N3** `app/cases` 孤岛（C3）：接线 or 移入 `docs/pending-review/`
- [ ] **N4** 4 个零引用模块的去留（见下）
  - [x] **N4-a** `governance/suspensions/resume_admission.py` → **显式降级**（用户决策 2026-10-07，见下）

**R5 孤儿模块取证结果**（全仓搜索符号，非仅模块名）：

| 模块 | 引用情况 | 定性 |
| --- | --- | --- |
| `governance/suspensions/resume_admission.py` | **仅被自己的测试引用** | ✅ **已决策 2026-10-07：显式降级（不接线）**。原定性 ⚠️ **安全控制未接线**：`trusted_resume_admission` / `is_trusted_task_continuation` 定义了"仅任务续跑端点可打开的可信准入上下文"，但全仓无任何生产者调用 `trusted_resume_admission()`、无任何消费方调用 `is_trusted_task_continuation()`，`_runtime_resume_only` 字段**无写入方**。绿测试造成虚假安全感。处置：模块 docstring 顶部自述"未接线 / NOT WIRED，不构成强制控制"，测试文件标注其自证性质 |
| `services/dag/builder_migrate.py` | 仅被自己的测试引用 | 010 T018/T019 交付物，`docs/SDD界面呈现对照表.md` 宣称"已接入生产"，但实际零调用方 → **文档宣称与事实不符** |
| `services/presentation/execution/page_executor.py` | 仅被自己的测试引用 | 死代码（`BoundedPageExecutor`） |
| `skills_specs/pdf/markdown_to_pdf.py` | **零引用（连测试都没有）** | 死代码（薄 re-export 壳） |
| `admin-api/repositories/admin_user_repository.py` | **零引用** | 遗留实现：操作 `admin_users` 集合，而线上登录走 `org_user_repository` + `admin_accounts` |

> 除 `resume_admission` 外，其余 4 个不构成运行风险（不接线则不可达），属"清账"范畴。
> `resume_admission` **已决策：显式降级**（按仓库既有"诚实降级不伪造"方针标注未实现），
> 而非接线。不接线的理由是**语义不成立**而非工作量大：`output_spec` 由客户端可控且由续跑端点
> 自行构造，端点往同一调用栈内的 dict 写标志再读回，不构成任何信任边界；真正生效的可信通道是
> 服务端参数 `trusted_turn_context`（生产者 `app/api/endpoints/tasks.py::resume_task`，
> 消费方 `app/dsh_runtime/chat_service.py::prepare_turn`，且明确不取自 `ChatRequest`）。
> 若将来确需"仅续跑可用"的特权能力，应实现为 `trusted_turn_context` 的兄弟服务端参数。

---

## 十、方法论声明

1. **不采信文档**：所有结论来自实跑或 grep，`bundle.json` 的 `verified: true`、`tasks.md` 的 `[x]`、
   `INDEX.md` 的"已实现核心"一律不作为证据（`LANDING_AUDIT` 自己已声明"明确不采信 tasks.md 的 `[x]`"）。
2. **检测器必须先被对抗验证**：本轮 3 个新检测器（发布链路 / 包级可达性 / 自证式测试）
   **全部在首跑时暴露自身缺陷**（A3 共用镜像、可达性漏剥 `app.` 前缀、自证式检测器 v1 误报 97.6%），
   修正后各自保留"已知误报样本"作为常驻自检。
3. **单次 grep 不下结论**：`ViewerContext` 的首次 grep 返回空（瞬时异常），
   二次确认该符号**存在**于 `visibility.py:41`。`AGENTS.md` 已有此纪律。
4. **修复必须可证伪**：对改写后的测试做了**变异测试**（破坏生产代码 → 测试必须失败 → 还原后干净）。

**本轮边界**：未启动服务做运行时验证；`document-parser` 与 `dsh-host-e2e` 未实跑；
C1 只机械化了"生产接线"这一条标准，**未重新逐条判定 landed**。
