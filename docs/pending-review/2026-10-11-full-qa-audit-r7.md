# Standard 深度全量 QA 审计报告（第七轮 · R7）

**审计时间**：2026-10-11
**审计基线**：`main` @ `b4d8782`
**审计范围**：三 Python 服务全量测试、Python 静态门禁（pyflakes / AST 正确性）、开源发布卫生门禁、密钥卫生、compose 配置、跨服务版本口径
**审计目标**：在 R5（发布链路/供应链/治理资产/自证式测试）与 R6（zip-slip / tenant_id 迁移 / 性能基准）之后，换新维度继续找问题

**本轮针对的宣称**（同 R5，用户再次引用）：

> "SDD 驱动的 spec 下所有特性 全流程已就绪，可进入 PR 评审与版本发布——库能力、生产接线与治理资产齐备"

**该宣称本身即审计靶子。** 结论见 §九。

---

## 一、审计结论

**共 2 项发现：均为 P0，均已修复。另有 1 项口径不一致待用户拍板。**

| 等级 | 数量 | 已处置 | 待决策 |
| --- | --- | --- | --- |
| P0 阻断 | 2 | 2 | 0 |
| P2 观察 | 1 | 0 | 1 |
| **合计** | **3** | **2** | **1** |

**核心结论（三句话）**：

1. **两项发现都是"门禁自身腐化"型**：不是新功能写错，而是**上一轮为防错而建的检查工具，在它上线之后的代码里自己失效了**，且 **2709 项测试一条都没报**。
2. **这恰好构成对"全流程已就绪"宣称最有力的反驳**：一个宣称"门禁齐备"的仓库，同时存在「静态门禁配额为 0 却实跑出 6 处违规」和「开源卫生门禁常量自初始发布起从未更新、导致 CI 长期绿灯」两条事实。
3. **测试全绿 ≠ 代码正确**：本轮 2 项 P0 没有一项能被 2709 项测试发现。重复字典键对 Python 运行时完全不可见；symlink 逃逸与卷数不符在 CI 上因不存在本机 venv 而永不触发。

---

## 二、R7-A · 三服务测试基线与回归（新维度：权威计数复核）

**方法**：不在仓库根目录跑 pytest；**每个服务在各自目录内**跑，输出 JUnit XML 后**解析 XML 取权威计数**（不信摘要行）。

> **环境陷阱（重要，避免误判）**：在仓库根目录跑 `pytest` 会触发 **172 个 collection error**，
> 因为三个服务的 `tests/` 被一起收集、相对导入全部失效。表象像"全线崩"，实为用法错误。
> **纪律**：换环境后第一次跑，先看 collected 数量对不对，再看 passed/failed 摘要——
> collection error 会让 `tail` 输出里完全看不到真实结论。

- [x] A1 **基线**（修复前）：chat-api **2254** / admin-api **433** / document-parser **22** = **2709**，0 失败 0 错误 0 跳过，退出码均为 0
- [x] A2 **回归**（修复后）：chat-api **2254** / admin-api **433** / document-parser **22** = **2709**，0 失败 0 错误 0 跳过，退出码均为 0
- [x] A3 **逐数一致**：修复未改变任何测试计数——**符合预期**（重复字典键对运行时本就无行为差异，见 §三 F1）
- [x] A4 `pyflakes app | grep "undefined name"`：chat-api **0**、admin-api **0** ✅

> 注：R6 评审记录的基线为 2717 项，本轮实测 2709 项。差异来自 `-m "not dsh_host_e2e"` 标记的
> e2e 用例数与 deselected 口径变化，**非测试丢失**（本轮 JUnit 中 `skipped=0`，说明无静默跳过）。

---

## 三、R7-B · 静态正确性门禁首跑（新维度）—— **1 项发现（P0，已修）**

### 🔴 F1（P0，已修）· 6 处重复字典键，前一个值被 Python 静默丢弃

`scripts/check_python_static.py` 的 `duplicate-dict-key` 检查（**冻结配额基线 = 0**）
在 chat-api 上**首次报出 6 处违规**：

| 文件 | 行 | 重复键 | 病灶性质 |
| --- | --- | --- | --- |
| `app/api/endpoints/auth.py` | 165-166 | `"tenantId"` | 登录响应体，连写两遍相同表达式 |
| `app/api/endpoints/auth.py` | 398-399 | `"tenantId"` | 企业租户列表项，连写两遍 |
| `app/api/endpoints/auth.py` | 835-836 | `"tenantId"` | 组织信息响应体，连写两遍 |
| `app/services/end_user_tenant_access.py` | 56-57 | `"tenantId"` | 终端用户上下文响应体 |
| `app/services/end_user_tenant_access.py` | 118 | `"tenant_id": 1` | **MongoDB 投影字段**重复声明 |
| `app/token_usage/push.py` | 43-44 | `"tenantId"` | **远端用量上报 payload**，`record.tenant_id or record.tenant_id` 自我 or 废表达式 |

**为什么是 P0**：

1. **测试完全看不见**。Python 字典字面量重复键不报错，前一个值被静默丢弃，
   运行时行为与"只写一遍"完全相同。**2709 项测试不可能发现它**。
2. **形态高度一致**——6 处全部围绕 `tenantId` / `tenant_id`，与 R6 的 `tenant_id` 迁移改造同源，
   高度疑似**同一批机械重命名/批量改写时留下的残渣**。这类批量改写正是 R3 报告建议
   "必须附 AST 破坏性 diff 审查"的场景，而当时的审查显然没覆盖重复键。
3. **其中 2 处跨服务契约面**：`push.py` 的 payload 会被 admin-api 侧消费，
   `end_user_tenant_access.py:118` 是 Mongo 投影——都是"错了会静默丢字段"的位置。

**修复**：6 处全部清理，各保留单份正确键值。

- [x] F1 已修：`duplicate-dict-key` **6 → 0**
- [x] F1 回归：三服务全量 **2709 / 0 失败**，与基线逐数一致
- [x] F1 门禁复跑：chat-api `duplicate-dict-key=0/0, duplicate-except=0/0, silent-except=41/41` ✅

**三服务静态门禁最终基线（实跑）**：

| 服务 | duplicate-dict-key | duplicate-except | silent-except | 门禁 |
| --- | --- | --- | --- | --- |
| chat-api | 0 / 0 | 0 / 0 | 41 / 41 | ✅ pass |
| admin-api | 0 / 0 | 0 / 0 | 14 / 14 | ✅ pass |
| document-parser | 0 / 0 | 0 / 0 | 2 / 2 | ✅ pass |

> `silent-except` 为**配额冻结**而非缺陷清单，R4 已逐处审议并有意保留，本轮未触碰。

---

## 四、R7-C · 开源发布卫生门禁（新维度）—— **1 项发现（P0，已修）**

### 🔴 F2（P0，已修）· 门禁常量自初始发布起从未更新 + venv 目录未被忽略

`scripts/check_open_source_hygiene.py` 首跑 **failed，11 条失败**，追下去是**两个独立根因**：

#### F2-a（9 条）· `.venv312` 未被 `.gitignore` 覆盖，被当作待发布产物

**现象**：9 条 `symlink escapes repository`：
`services/{admin-api,chat-api,document-parser}/.venv312/bin/{python,python3,python3.12}`

**根因**：`.gitignore` 的 Environments 段只写了 `.venv`、`venv/`、`.venv/`（以及重复的 `venv/` `.venv/`），
**没有任何规则覆盖带版本号后缀的 `.venv312`**。而门禁的 `publication_files()` 取
`git ls-files --cached --others --exclude-standard`，即**所有未被忽略的文件**都会被当作可能进入发布的产物扫描，
于是本机随手建的 venv 直接让发布门禁挂掉。

**为何严重**：这类缺陷 **CI 上永远复现不出来**——CI runner 没有 `.venv312` 目录，
所以门禁长期绿灯，而任何开发者在本机执行该门禁都会拿到红色。
**门禁的实际效果与宣称相反：它只在本机生效，而本机不是发布环境。**

**修复**：`.gitignore` Environments 段的 `.venv` 改为 `.venv*`，并加注释说明原因。

- [x] F2-a 已修
- [x] F2-a 验证：`git check-ignore -v` 对三个服务的 `.venv312/bin/python` 均命中 **`.gitignore:162:.venv*`**
- [x] F2-a 验证：`git ls-files services/chat-api/.venv312` 为空（从未被 track）

> 顺带说明：`services/document-parser/=0.6.23` 这个 shell 重定向事故产物
> 已被 `services/document-parser/=*` 覆盖，**非发现项**（R5 已勘误）。

#### F2-b（1 条）· 卷数常量过期，门禁处于"永久红灯"或"被绕过"二选一

**现象**：`Compose must define exactly 8 MOVO-prefixed physical volumes; found 11`

**根因（用 `git log -S` 追溯，非猜测）**：

```
git log -S "dsh-runtime-data-1" -- docker-compose.yml
  → fddc97a feat(compose): M1 存储卷按副本隔离（消除 R-01 跨副本踩踏）

git log -S "EXPECTED_MOVO_VOLUMES = 8" -- scripts/check_open_source_hygiene.py
  → 82e4d20 Initial MOVO Community Edition release
```

提交 `fddc97a` **有意**新增 3 个 per-replica 存储卷 `dsh-runtime-data-1/2/3`
（每副本独立卷，防止两个副本同时写同一份 kernel 状态 JSONL）。
而门禁常量 `EXPECTED_MOVO_VOLUMES = 8` **自初始发布 `82e4d20` 起从未更新过**。

**定性：门禁过期，不是 compose 错。** 不修 compose（那会撤销 M1 的跨副本隔离修复），
只同步门禁常量。

**修复**：`EXPECTED_MOVO_VOLUMES = 8 → 11`，并加注释指明 3 个增量卷的来源提交与"何时需再改"的提示。

- [x] F2-b 已修
- [x] F2 总验证：`check_open_source_hygiene.py` → **`Open-source hygiene check passed.`**
- [x] F2 回归：`docker compose config -q` 三变体（默认 / `-f docker-compose.build.yml` / `--profile single-host`）全部解析通过

---

## 五、R7-D · 密钥卫生（新维度）—— **0 项发现**

全仓扫描形如 `(api_key|secret|password|passwd|token)\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}["']` 的字面量，
命中 **2 处，逐处查证**：

- [x] D1 `services/admin-api/app/core/config.py:121` 的 `"dev-secret-change-me-in-production"`
      → **非缺陷**。仅在 `app_env ∈ {local, development}` **且未显式配置**时兜底；
      紧邻注释明确写「MUST NOT be used in shared/staging or production, where it would allow forging admin tokens」；
      生产分支走 `_secrets_mod.token_urlsafe(64)` 自动生成并连续两条 `logger.warning` 提示改用持久化密钥。
      **逻辑正确、告警到位，不动。**
- [x] D2 `services/chat-api/tests/services/test_local_file_secret.py` 的 `"operator-provided-secret"`
      → **非缺陷**。测试夹具的输入值，非泄露凭据。

---

## 六、修复清单（逐条勾）

| # | 等级 | 文件 | 改动 | 验证 |
| --- | --- | --- | --- | --- |
| 1 | P0 | `services/chat-api/app/api/endpoints/auth.py` | 删 3 处重复 `"tenantId"` 键（165/398/835 行附近） | 门禁 6→0；全量 2254 逐数一致 |
| 2 | P0 | `services/chat-api/app/services/end_user_tenant_access.py` | 删 1 处重复 `"tenantId"`（响应体）+ 1 处重复 `"tenant_id": 1`（Mongo 投影） | 同上 |
| 3 | P0 | `services/chat-api/app/token_usage/push.py` | 删 `record.tenant_id or record.tenant_id` 自我 or 废表达式，保留单份 `"tenantId"` | 同上 |
| 4 | P0 | `.gitignore` | Environments 段 `.venv` → `.venv*`（覆盖 `.venv312` 等带版本后缀的 venv），加原因注释 | `git check-ignore` 三服务均命中 `:162` |
| 5 | P0 | `scripts/check_open_source_hygiene.py` | `EXPECTED_MOVO_VOLUMES` 8 → 11，注释标注来源提交 `fddc97a` | 卫生门禁 passed；compose 三变体 config 通过 |

**回归验证**：三服务 **2709 / 0 失败 0 错误 0 跳过**（与修复前逐数一致）；
静态门禁三服务全过；pyflakes undefined name = 0；开源卫生门禁 passed；compose 三变体解析通过。

**改动面自查**（遵守 `AGENTS.md` 并行会话纪律）：

- [x] 只暂存/改动本轮确认的 5 个文件，未使用 `git add -A`
- [x] 工作区另有他轮在途改动（`docs/WORK_LOG.md`、`scripts/export_base_images.sh`、
      `services/chat-api/Dockerfile`、`docs/regression-arm-orbstack-2026-10-11.md`、
      `docs/pending-review/2026-10-10-stale-base-image-archives.md` 及 3 个未跟踪文件），
      **本轮未回滚、未覆盖、未格式化**

---

## 七、待决策项（**未擅改**）

- [x] **N1（已解决 2026-10-11）· FastAPI 暴露版本与仓库版本口径不一致** —— 连带 §十一 N1-fix（用户拍板：统一到 `0.2.0` 并记 CHANGELOG）—— 详见文末「十一、N1 后续」章节

  | 位置 | 版本 |
  | --- | --- |
  | `services/chat-api/app/main.py:40` `version="0.1.0"` | 0.1.0 |
  | `services/admin-api/app/main.py:48` `version="0.1.0"` | 0.1.0 |
  | `services/document-parser/app/main.py:13` `version="0.1.0"` | 0.1.0 |
  | `services/{chat,admin}-api/pyproject.toml:3` `version` | 0.2.0 |
  | `apps/admin-web/package.json` / `apps/user-web/package.json` | 0.2.0 |
  | `CHANGELOG.md` 最新已发布节 | `## v0.2.0 - 2026-10-03` |

  **影响面**：仅 OpenAPI 文档 `/openapi.json` 的 `info.version` 字段，不影响任何业务逻辑或接口契约。
  全仓测试无任何用例断言该字段（已 grep 确认，测试中的 `0.1.0` 均为 DSH kernel 版本 `0.1.0-rc.x`，无关）。

  **为何不擅改**：修改会让三个服务的 `/openapi.json` 版本从 0.1.0 跳到 0.2.0，
  属**对外可见行为变更**（下游若按 version 做兼容性判断会受影响），按 `AGENTS.md` 需先征得同意。


---

## 八、本轮边界（诚实声明）

- [ ] **未实跑** `dsh-host-e2e`（需 pnpm + Node 22 + 真实 Runtime Host 运行时）
- [ ] **未做运行时/端到端验证**（未启服务，未跑 compose 栈，未做 HTTP 路由探针）
- [ ] **未重新逐条判定 `landed`**：R5 已机械化的仅「核心包是否有生产入边」一条标准，
      第 2 条（有消费方）/ 第 3 条（数据源真实）/ 第 4 条（端到端可证伪）**仍未逐条重判**
- [ ] **未复审 R5/R6 的待决尾巴**（`app/cases` 孤岛去留、4 个零引用模块清账、
      node/nginx 4 个 multi-stage digest 钉死、docling 层显式降级注释）
- [ ] 未审计前端（`apps/admin-web`、`apps/user-web`）typecheck / lint / 构建产物
- [ ] 未审计 21 个 spec 的 `tasks.md` 勾选真实性（R5 已查 010 T020/T021，其余 20 个未逐条查）

---

## 九、对"全流程已就绪"宣称的判定

**判定：部分成立，但不构成放行依据。**

**支持宣称的实证（本轮实跑）**：

- [x] 三服务 2709 项测试 0 失败 0 错误，退出码全 0
- [x] Python 静态门禁三服务全过（重复 except / 重复字典键 / 静默宽泛 except 均有冻结基线）
- [x] pyflakes 未定义名 = 0
- [x] 开源发布卫生门禁 passed（阻断路径、.env 文件、symlink 逃逸、体积前缀）
- [x] compose 默认 / 构建 / single-host 三变体解析通过
- [x] 无真实硬编码凭据泄露
- [x] 密钥兜底与告警逻辑正确

**反对宣称的实证**：

- [x] **门禁自身在两处失效**：静态门禁配额为 0 却实跑出 6 处违规；卫生门禁卷数常量自初始发布起从未更新
- [x] **上述两项都逃过了 2709 项全绿测试**——"测试通过"在本仓库不构成质量证据
- [x] **CI 与本机行为分叉**：F2-a 类缺陷（未忽略目录）**只在开发者本机触发、CI 永远绿灯**，
      意味着该门禁在真实发布路径上从未被有效执行过
- [x] 21 个 spec 的 `landed` 判定仅有 1/4 条标准被机械化，`specs/LANDING_AUDIT_2026-10-03.md`
      的 `landed 0 / partial 10 / hollow 9` 总览至今仍是唯一的完整判定，且其小节与总览自相矛盾（见 R5-C1）
- [x] N1 版本口径不一致未解决

**放行前建议至少完成**：

1. 用户拍板 N1（版本口径）
2. 启动 compose 栈做一次运行时/路由级验证（本轮全为静态与单元层）
3. 补齐 R5/R6 的待决尾巴（N3/N4 与 4 个 multi-stage digest）
4. 对剩余 20 个 spec 做 `tasks.md` 勾选真实性抽查

---

## 十、方法论声明

1. **不采信文档**：所有结论来自实跑、grep 或 `git log -S` 追溯。
   `tasks.md` 的 `[x]`、`CHANGELOG` 的版本节、`LANDING_AUDIT` 的总览一律不作为证据。
2. **权威计数只认 JUnit XML**：不信 `tail` 摘要行，不信 pytest 退出码单点，
   解析 XML 取 `tests/failures/errors/skipped` 四元组。
3. **跨服务必须进各自目录跑**：根目录跑会产生 172 个 collection error，
   **先看 collected 数量再看结论**，否则一次用法错误会被误报成全线崩盘。
4. **门禁常量过期用 `git log -S` 追溯，不靠推测**：F2-b 正是靠 `-S "dsh-runtime-data-1"`
   与 `-S "EXPECTED_MOVO_VOLUMES = 8"` 两条命令才定位到真根因（compose 正确、门禁过期），
   避免误改 compose 撤销 M1 跨副本隔离修复。
5. **修复后必须回归且逐数比对**：本轮两次全量（修复前 2709 / 修复后 2709）逐数一致，
   是"改动确实无行为影响"的证据，而非"应该没问题"的猜测。
6. **发现即取证，不擅改对外可见行为**：N1 涉及 `/openapi.json` 对外版本号，
   按 `AGENTS.md` 记入待决策而非自行修改。

---

## 十一、N1 后续（2026-10-11 用户拍板：统一到 `0.2.0` 并记 CHANGELOG）

### N1-fix · 三个服务的对外 API 版本对齐 `0.2.0`

| 位置 | 改前 | 改后 |
| --- | --- | --- |
| `services/chat-api/app/main.py:43` | `0.1.0` | **`0.2.0`** |
| `services/admin-api/app/main.py:51` | `0.1.0` | **`0.2.0`** |
| `services/document-parser/app/main.py:16` | `0.1.0` | **`0.2.0`** |

三处各加注释，明确该字段是 `/openapi.json` 的 `info.version`、属**对外可见契约**，
需与 `pyproject.toml` / CHANGELOG 保持同步（防止下次又悄悄漂回 0.1.0）。

- [x] N1-fix：三处 `FastAPI(version=...)` 已改
- [x] N1-fix：`CHANGELOG.md` 的 `## Unreleased` → `### Changed` 顶部新增一条，
      记明对齐动作、影响面（下游按 version 做兼容性判断的场景）
- [x] N1-fix：版本口径复核，三处均为 `0.2.0`
- [x] N1-fix：静态门禁三服务复跑全过（41/41、14/14、2/2）

### 🔴 G1（审计过程中附带发现并已修）· 抖动测试用例

**与 N1 无关，是回归时暴露的独立缺陷。**

- [x] G1 现象：chat-api 全量回归退出码 1，
      `tests/dsh_runtime/test_credential_lease.py::test_transient_refresh_failure_does_not_end_the_lease`
      断言 `len(calls) >= 2`，实测只有 1 次。**测试总数仍是 2254 与基线一致** → 排除 collection 问题。
- [x] G1 取证：单文件连跑 20 次 → **19 过 1 失败**（约 5% 抖动率），确认是可复现的时序敏感用例，而非环境偶发。
- [x] G1 根因（100 次采样量 tick 间隔，p50=51.6ms / max=61.7ms）：测试用
      `await asyncio.sleep(0.13)` 等第二次 tick（名义 t=0.100s），**余量仅约 28ms**；
      叠加 `logger.exception` 的 traceback 格式化耗时，第二次 tick 会被推出窗口。
      采样中 `failures=0` 的对照组反而出现 1 次只拿到 1 次调用，进一步排除
      「瞬时失败终止了租约」这一假设 —— **生产代码 `_run` 的 `while True` + `refresh_now`
      捕获 `Exception` 后只记日志不退出循环，逻辑本身正确**。
- [x] G1 修复：**不改生产代码**，把测试从「等固定墙钟窗口」改为「等信号」——
      `_Refresher` 加 `asyncio.Event` 在第二次调用时 set，测试用
      `asyncio.wait_for(..., timeout=5)` 等待它真正要断言的那个 tick；
      并给第二个测试补上 `refresher.calls == ["session-b"] * len(...)` 断言
      （原断言只查次数，漏了一半强度）。
- [x] G1 验证：修复后单文件连跑 **20/20 全过**；chat-api 全量 **2254 / 0 失败**，与基线逐数一致。

### O1（用户拍板后已处置 2026-10-11）· `version-consistency` 覆盖范围扩大

**背景**：该 job（`.github/workflows/quality-gate.yml`）原先只校验 4 个清单文件
（`chat-api`/`admin-api` 的 `pyproject.toml` + 两个前端 `package.json`），
**恰恰不包含三个 `main.py`**——这正是 N1「版本滞后」能长期存活的根因：
该字段根本不在门禁视野里。用户拍板「这个需改」。

**改动**（`.github/workflows/quality-gate.yml`）：

- [x] O1：job 头部注释改写，说明校验范围从「清单文件」扩到「清单文件 **+** FastAPI app 对象」，
      并写明 R7 发现的漂移正因这三个文件在门禁视野外
- [x] O1：新增 `check_fastapi()` 函数 + 三条调用，校验数 **4 → 7**
- [x] O1：提取锚定 `sed -n '/FastAPI(/,/)/p'`，只取 `FastAPI(...)` 调用块内的
      `version="..."`，避免误抓同文件其他 `"version"` 字面量
      （`/health` 响应体硬编码的 `0.1.0`、MCP `clientInfo`、`dsh_session_versioning`
      路由名、索引创建里的 `"version": 1`）
- [x] O1：**提取失败也判失败**（找不到 `FastAPI(` 或抓不到版本号 → `::error` + `failed=1`），
      不做「抓不到就当过了」

**验证（三条均实跑，非采信文档）**：

- [x] YAML 可解析：5 个 job 完好，`version-consistency` 3 个 step 结构正确（pyyaml 实跑）
- [x] 正向本地等价模拟：`expected=0.2.0`，7 条全部 `ok`，`failed=0` → exit 0
- [x] **对抗验证（关键）**：把 `chat-api/app/main.py` 拷到临时目录改坏为 `0.1.0`，
      门禁逻辑检出 `expected=0.2.0 actual=0.1.0` → `NEGATIVE-CONTROL-PASS`。
      **不验这条就无法排除「新门禁压根不生效却自以为修好了」**

> **诚实边界**：本次改的是 CI workflow，**本地没有任何东西能证明它在 GitHub runner 上
> 真的按预期执行**。已证明的只有：YAML 可解析、shell 逻辑在等价环境正确、
> 真有违规时会失败。**最终确认需等下一次 push 后 `version-consistency` job 实跑。**

### O2（用户拍板后已处置 2026-10-11）· 两处对外版本字面量

**背景**：O1 修复时发现两处版本字面量在 `FastAPI(...)` 块外，新门禁覆盖不到。
二者都是对外响应/协议字段，其中 MCP `clientInfo` 的 version 语义存疑
（「MCP 客户端实现版本」还是「MOVO 服务版本」）。**用户拍板：确认语义后修复。**

**语义查证（不跳过，逐项 grep）**：

| 字面量 | 语义证据 | 结论 |
| --- | --- | --- |
| `/health` 响应体 `"version": "0.1.0"` | FastAPI 实例的 `app.version` 属性由 `FastAPI(version=...)` 构造时写入（实测 fastapi 0.141.1，`FastAPI(version='9.9.9').version == '9.9.9'`），即二者本就该是同一个值 | **该字段就是服务版本**，与 `FastAPI(version=)` 同源 → 应对齐 |
| MCP `clientInfo.version` | 文件头 `MCP_PROTOCOL_VERSION = "2025-06-18"`（协议版本）与 `clientInfo.version` 相邻但语义不同；全三服务 grep `serverInfo` / initialize 响应侧 **零命中** → MOVO 在这套代码里**只作 MCP client** | 语义是「MCP client implementation version」，且唯一标识 MOVO 客户端实现 → 应对齐发布版本（否则远端 server 管理员排障时看到的是过期的 0.1.0） |

> 附证：两处 `0.1.0` 均自初始发布 `82e4d20` 引入后**从未更新**；全仓无任何测试、前端、
> 部署脚本或 contracts 消费这两个字段 → 修复无破坏面，但也正因无人消费，漂移无人发现。

**修复（三处，均不留重复字面量）**：

| 位置 | 改前 | 改后 |
| --- | --- | --- |
| `services/chat-api/app/main.py:453` `/health` 响应体 | `"version": "0.1.0"`（第二份硬编码） | `"version": app.version`（**单一来源**，与 CI 门禁钉死的是同一个值） |
| `services/chat-api/app/services/mcp_streamable_http.py` 新增常量 | — | `MCP_CLIENT_VERSION = "0.2.0"`，附注释说明语义（client implementation version ≠ protocol version） |
| 同文件 `clientInfo` | `{"name": "MOVO", "version": "0.1.0"}` | `{"name": "MOVO", "version": MCP_CLIENT_VERSION}` |

**为什么 `/health` 用 `app.version` 而非本服务版本常量**：仓内既无集中版本常量
（`__version__` / `APP_VERSION` / settings 均无），且运行时容器内 `pyproject.toml`
不一定可读（Docker 镜像只 COPY `app/`）。而 `app.version` 是 FastAPI 实例自带的、
与 CI `version-consistency` 门禁钉死的 `FastAPI(version=...)` 完全同源的唯一值。
**不引入 `import app.main` 的延迟导入**：该模块会被 `external_tools.py` 导入、
而 `external_tools` 又被 `main.py` 引用（第 121/158 行），延迟导入会构成环；
且叶子服务模块 import 主 app 模块在全仓无先例。故 `/health` 直接用同文件内的
`app.version`（零依赖、零新环）。

- [x] O2 处置：语义已确认（前者=服务版本；后者=MOVO client 实现版本，MOVO 全程只作 client）
- [x] O2 处置：`/health` 与 `clientInfo` 不再有重复硬编码字面量
- [x] O2 验证：TestClient 实跑 `GET /health` → 200，`health.version = 0.2.0`
- [x] O2 验证：`MCP_CLIENT_VERSION=0.2.0` 与 `MCP_PROTOCOL_VERSION=2025-06-18` 不相等（两语义未混用），且握手 payload 源码引用新常量（`inspect.getsource` 证实）
- [x] O2 验证：静态门禁三服务全过；CI 版本提取正向模拟三条 `ok`（`app.version` 未干扰 `FastAPI(...)` 块提取）
- [x] O2 回归：chat-api 全量 **2254 / 0 失败 0 错误**，与基线逐数一致

### 遗留观察（未擅改，需用户另行拍板）

- [ ] **O3 · `/health` 与 `clientInfo` 仍不受门禁保护**：`/health` 现在取 `app.version`，
  天然随 CI 门禁钉死的值走，不会再漂；但 `MCP_CLIENT_VERSION` 是一个**新常量**，
  与 `FastAPI(version=)` 仍是两份值，将来仍可能只改一处。是否要在
  `version-consistency` 门禁里加一条 `MCP_CLIENT_VERSION` 检查（或把它改为从
  `app.version` 派生），**待用户拍板**。

### N1 收尾后的最终回归计数

| 服务 | tests | failures | errors | skipped |
| --- | --- | --- | --- | --- |
| chat-api | 2254 | 0 | 0 | 0 |
| admin-api | 433 | 0 | 0 | 0 |
| document-parser | 22 | 0 | 0 | 0 |
| **合计** | **2709** | **0** | **0** | **0** |
