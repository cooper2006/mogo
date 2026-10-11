# Code Review · R7 改动集

**审查时间**：2026-10-11
**审查对象**：R7 审计中落地的全部代码改动（非他轮在途改动）
**审查方法**：逐文件读 diff + 实地可证伪核对（卷数、git 跟踪、gate 变量、测试复跑）
**审查结论**：无阻断级问题；2 个低危待跟进项（其一即已记录的 O3）

---

## 一、审查范围（纪律边界）

仅审查本轮 R7 改动集，未触碰工作树中其他会话的在途改动（如 `services/chat-api/Dockerfile`、`scripts/export_base_images.sh`、`docs/regression-arm-orbstack-2026-10-11.md`、`docs/pending-review/2026-10-10-stale-base-image-archives.md`、`docs/pr-review-2026-10-10-r05*.md` 等）。

R7 改动集文件清单（13 tracked + 1 新建报告）：

| 文件 | 改动 | 对应发现 |
| --- | --- | --- |
| `.github/workflows/quality-gate.yml` | 新增 `check_fastapi()` + 3 条调用 | O1 |
| `.gitignore` | `.venv` → `.venv*` | F2 |
| `scripts/check_open_source_hygiene.py` | `EXPECTED_MOVO_VOLUMES` 8 → 11 | F2 |
| `services/admin-api/app/main.py` | `version="0.1.0"` → `0.2.0"` | N1 |
| `services/document-parser/app/main.py` | 同上 | N1 |
| `services/chat-api/app/main.py` | `version="0.2.0"` + `/health` 取 `app.version` | N1 + O2 |
| `services/chat-api/app/services/mcp_streamable_http.py` | 新增 `MCP_CLIENT_VERSION` 常量 | O2 |
| `services/chat-api/app/api/endpoints/auth.py` | 删 3 处重复 `tenantId` 键 | F1 |
| `services/chat-api/app/services/end_user_tenant_access.py` | 删 2 处重复键（dict + Mongo 投影） | F1 |
| `services/chat-api/app/token_usage/push.py` | 删 1 处重复 `tenantId` 键 | F1 |
| `services/chat-api/tests/dsh_runtime/test_credential_lease.py` | 信号等待替代固定 sleep | G1 |
| `CHANGELOG.md` / `docs/WORK_LOG.md` | 记录 | 全部 |

---

## 二、逐件审查

### N1 · 三服务 `FastAPI(version=)` 0.1.0 → 0.2.0
- ✅ **正确**。三处均对齐发布版本，注释点明这是 `/openapi.json` 的对外契约而非私有字符串。
- ✅ 已验证：`check_fastapi` 实跑 3 条 `ok`；负控能抓漂移（详见 WORK_LOG O1 节）。

### O2 · `/health` 取 `app.version` + 新增 `MCP_CLIENT_VERSION`
- ✅ `/health` 改用 `app.version` 是正确决策：单一来源、零新环、避开循环导入（不引入 `import app.main`）。已验证 TestClient `GET /health` → 200 且 `health.version == 0.2.0`。
- ✅ `MCP_CLIENT_VERSION = "0.2.0"` 语义注释清楚（client implementation version ≠ protocol version）。
- ✅ **O3（已处置 2026-10-11）**：`version-consistency` 门禁新增 `check_mcp_client_version`，把 `MCP_CLIENT_VERSION` 与 CHANGELOG 版本钉死（共用 `expected`）。`mcp_streamable_http.py` 注释已改为准确表述（gate 现在检查该常量，非"声称"）。决策选"加门禁检查"而非"从 `app.version` 派生"——后者反向 import 会成环（O2 已确认）。

### O1 · `quality-gate.yml` 新增 `check_fastapi()`
- ✅ 结构正确：`expected` 取自 CHANGELOG step 输出；`failed=0` 初始化；三处 `failed=1` 兜底；**提取为空也判失败**（fail-safe，不会假绿）。
- ✅ 负控已验证：把 `main.py` 改坏为 `0.1.0` 能被检出。
- ✅ **O1 加固（已处置 2026-10-11）**：`sed -n '/FastAPI(/,/)/p'` 已替换为 awk **括号深度追踪**（`extract_fastapi_version`）。本地验证：在 `version=` 之后插入 `middleware=[Depends(...), Auth()]` 含嵌套 `)`，提取仍正确不截断；删除 `FastAPI(` 则提取为空 → fail-safe 判失败。YAML 可解析、抽取 run 块 `bash -n` 通过。

### F1 · 6 处重复字典键
- ✅ 全部为「复制粘贴连写同一键」，删前删后值完全相同，运行时零差异。已验证三服务 JUnit 权威计数 **2709 逐项逐数一致**。
- 备注：`push.py` 删掉的是 `"tenantId": record.tenant_id or record.tenant_id`（冗余 `or`，等价于 `record.tenant_id`）——属「不同形态」的重复，删得对。
- 备注：`end_user_tenant_access.py` 投影 `{"tenant_id":1,"tenant_id":1,"status":1}` → 去重后 Mongo 投影结果不变，更干净。

### F2 · 开源卫生门禁
- ✅ `EXPECTED_MOVO_VOLUMES=11` **实地核对成立**：`docker-compose.yml` 中 movo 前缀物理卷恰为 11 个（8 基础：`deployment-secrets`/`mongo-data`/`redis-data`/`weaviate-data`/`dsh-runtime-data`/`askai-storage`/`knowledge-storage`/`admin-static` + 3 副本：`dsh-runtime-data-1/2/3`）。不是拍脑袋常数。
- ✅ `.venv` → `.venv*` **实地确认生效**：`git ls-files | grep venv` 无命中（从未跟踪），`git check-ignore services/document-parser/.venv312` 命中（现被忽略）。F2 之前门禁失败的根因被真正消除，非自欺。

### G1 · 抖动测试修复（`test_credential_lease.py`）
- ✅ 这是唯一改了测试**行为**的改动。把 `await asyncio.sleep(0.13)` 固定窗口换成：`_Refresher` 在第二次调用 `set()` 一个 `asyncio.Event` → 测试 `await asyncio.wait_for(second_call.wait(), timeout=5)` → `finally` 里 `lease.stop()`。本质正确：测的是「等到第 N 次调用」而非「赌多久」。第二个测试补 `refresher.calls == ["session-b"]*len(calls)` 断言，收紧会话身份校验。
- ✅ **复跑确认**：该文件 2 个用例，连跑 3 次均退出码 0；机制上确定性，不再依赖墙钟抖动与 suite 负载。

---

## 三、审查结论

| 等级 | 数量 | 说明 |
| --- | --- | --- |
| 阻断 | 0 | 无 |
| 低危 / 待跟进 | 0 | O3 与 O1 加固均已于 2026-10-11 处置（加 `check_mcp_client_version` + awk 深度追踪提取） |

**放行建议**：本轮 R7 改动集 + O3/O1 加固均可进入提交；无阻断问题。
**诚实边界（沿用）**：CI workflow 改动本地无法证明在 GitHub runner 上生效，最终确认需等下次 push 后 `version-consistency` job 实跑。

> **诚实边界（沿用 R7 纪律）**：CI workflow 改动本地无法证明在 GitHub runner 生效，最终确认需等下次 push 后 `version-consistency` job 实跑；「测试全绿 / 本地模拟通过」不构成放行依据。
