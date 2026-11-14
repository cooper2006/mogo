# DSH Host e2e 测试持续失败 · 已诊断（未修复）

**登记时间**：2026-11-12 14:12 CST  
**基线 commit**：`f014b5e2` (main)  
**状态**：待处理（影响面窄，非回归引入）

---

## 现象

```
FAILED tests/dsh_runtime/test_runtime_host_e2e.py::test_real_dsh_host_session_replay_cancel_isolation_plugin_and_crash
app/dsh_runtime/errors.py:DshRuntimeError: DSH Runtime Host did not become healthy before the startup deadline
host_manager.py:101
```

与历史登记的 `DshProtocolError` 不符——本轮实际复现的异常是 `DshRuntimeError`（启动超时），不是协议层报错。原登记（`2026-11-12.md` 中的「遗留」小节）把错误类型写反了，本文件予以校正。

## 根因

host 冷启动约 **35s**（含 kernel + plugin 初始化、workspace root mkdir 等），而测试用的默认 `startup_timeout_seconds=20.0`（`host_manager.py:22`）。

实测 timeline（`127.0.0.1:8126` 手动起 host）：

```
 5s NOT_YET
10s NOT_YET
15s NOT_YET
20s NOT_YET
25s NOT_YET
30s NOT_YET
35s HOST_READY resp={"ok":true,"kernel":"dsh","version":"0.2.2-rc.1",...}
40s HOST_READY ...
```

标准输出（启动完成时打印一次）：
```json
{"type":"askai-dsh-runtime-ready","host":"127.0.0.1","port":8126,"kernel":"dsh",
 "kernelVersion":"0.2.2-rc.1","protocolVersion":"askai.dsh-host.v1",
 "instanceId":"probe","pid":35557}
```

stderr 有噪声但不影响功能：
```
[directory-browser] workspace root unavailable: cannot create workspace root /data/dsh-runtime/workspaces: ENOENT: no such file or directory, mkdir '/data'
```

## 环境

- **Node.js**：v22.22.2（PATH 上可查）；备用路径 `/Users/jack/.cache/codex-runtimes/...` 不存在（代码已降级为 PATH-first）
- **vendored deps**：`dsh/runtime-host/node_modules/` 存在且可导入
- **CI workflow**：`.github/workflows/quality-gate.yml:389` 已单独拉起 `dsh-host-e2e` job，用 `--timeout=300`，但 `DshHostConfig.startup_timeout_seconds` 硬编码在 Python 侧未被覆盖，故 CI 同样会在这一步挂掉（ pytest `--timeout` 控制的是单条用例整体超时，不是 manager 内部的健康轮询窗口）

## 文件

| 文件 | 作用 |
|------|------|
| `tests/dsh_runtime/test_runtime_host_e2e.py` | e2e 测试（单条，含 runtime/session/send/replay/cancel/isolation/plugin/crash/resume 全流程） |
| `app/dsh_runtime/host_manager.py:22` | `startup_timeout_seconds=20.0`（默认值） |
| `app/dsh_runtime/host_manager.py:59,82,101` | `_wait_until_ready()`，轮询 `/health` |
| `dsh/runtime-host/src/host-protocol.mjs:2-3` | `ASKAI_DSH_HOST_PROTOCOL_VERSION='askai.dsh-host.v1'`, `ASKAI_DSH_KERNEL_VERSION='0.2.2-rc.1'` |
| `dsh/runtime-host/src/runtime-http-server.mjs:258-266` | `/health` 端点实现 |

## 解决选项

### A. 提高超时（推荐，最小改动）

把 `DshHostConfig.startup_timeout_seconds` 默认值从 `20.0` 提到 `45.0`（给 35s 冷启动留足余量）；或在 e2e fixture 里覆盖成更大的值。代价：单次 e2e 变慢 ~15s，对 CI 总时长影响小。

**风险**：若下次 kernel 升级再慢于 45s，会再次静默翻车。建议同步加一条「测量启动耗时 + 上限守卫」的逻辑（启动完成后 log 一下实际耗时，便于未来感知漂移）。

### B. 异步预热

在 pytest `session` 级 fixture 预启动一个共享 host，e2e 用例复用同一实例，跳过冷启动等待。代价：多实例并发或 teardown 清理逻辑更复杂；host 进程常驻期间占用端口和临时目录。

### C. 改造 health probe

让 host 在 HTTP server 绑定时就报 ready（而不是 kernel + all plugins 完全加载完）。需要 Node 侧改动，可能影响滚动升级语义（LB 误判 ready 后流量打到尚未加载完 plugin 的副本）。

**不推荐**。

## 为何此前没被发现

1. 默认 pytest 命令 `-m "not dsh_host_e2e and not network"` 会把此测试排除（同目录下另外 3 个文件也打上两个 marker，一起被排）
2. CI 的独立 `dsh-host-e2e` job 存在但**之前从未跑通过**（或只在大规格 runner 上偶发通过）
3. 本地开发机性能波动：快机器（SSD + 高频 CPU）可能在 20s 内就绪，慢机器（CI runner / ARM Mac）必定超时

## 连带观察

- `[directory-browser] workspace root unavailable` stderr 噪声说明容器/宿主未挂载 `/data/dsh-runtime/workspaces`。生产部署应在 entrypoint 里 `mkdir -p` 或走 env var 注入挂载点（见 `host.mjs:31-37` 的 args 解析 + `runtime-http-server.mjs:298` 的路由），当前 test 绕过这点是因为走 tmpdir 存储根，但 directory-browsing 根仍是硬编码 `/data/dsh-runtime/workspaces`——**不影响本 e2e 主流程，但会在真实 K8s Pod 缺 volume 时报错**。这是独立的次要项。

## 验收标准

修完之后：

- `pytest tests/dsh_runtime/test_runtime_host_e2e.py -m dsh_host_e2e --timeout=300` 在普通 SSD Mac 上一遍过
- 连续跑 3 次无 flaky timeout
- CI `dsh-host-e2e` job 稳定通过

## 相关登记

- 原始登记（2026-11-12 上午）：`.workbuddy-ai/memory/2026-11-12.md` 「遗留」小节（错误诊断为 `transport.py:455 DshProtocolError`，需以本文件为准）

---

*注：本文件按 `AGENTS.md` 操作规约移入 pending-review，不删除也不修改源码；后续处置时从本文件复制关键信息到对应任务单，完成后划掉本条目。*
