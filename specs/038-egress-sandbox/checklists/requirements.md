# Requirements Quality Checklist: 038 egress-sandbox

**Purpose**: 校验 038（出站白名单与沙箱隔离强化）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 工具级条目的绑定键与生命周期是否定义（`scope=tool` 绑 `tool_id`，但**该键取自 `external_tools._id` 还是业务 key**、工具复制/重命名/删除后条目是否跟随，未写）
- [x] CHK002 域名匹配的大小写与 IDN 归一是否定义（后缀匹配是否大小写无关；国际化域名是否 punycode 归一；`*.example.com` 与 `example.com` 是否等价——决策 #1 说后缀匹配但**未说 `*.` 前缀的处理**）
- [x] CHK003 路径前缀的归一化边界是否定义（尾斜杠、查询串是否参与匹配、大小写敏感性、`/api` 是否覆盖 `/apiX`——匹配语义直接决定越权面）
- [x] CHK004 浏览器重定向的 `final_url` 来源与缺失时行为是否定义（FR-004 以 `final_url` 判定；**若浏览器未返回 `final_url`（非 navigate 动作/引擎异常）是否 fail-closed**，未写）
- [x] CHK005 热更新的时效判据是否定义（FR-007 说"保存后下一调用即按新配置求值"；**快照缓存的存在使"下一调用"变模糊**，需要明确可接受的生效延迟上限）

## 清晰度（Clarity）

- [x] CHK006 审计事件与既有工具审计的兼容性是否定义（FR-008 要求复用 `tool.started`/`tool.succeeded` 通道；**新增 `egress.allowed`/`egress.denied` 的字段集与既有事件如何共存**、查询侧是否需同时过滤两类，未写）
- [x] CHK007 MCP 工具的出站目标枚举方式是否定义（MCP 可能由服务端发起多次内部请求，**客户端只能看到 `url`/`endpoint`**；`resolve_tool_outbound_urls` 的枚举边界与"漏网 URL"的处理未写）
- [x] CHK008 平台级条目的租户可见性是否定义（FR-012 说平台级仅平台管理员维护；**租户管理员能否看到平台条目**、列表是否合并展示，未定义）
- [x] CHK009 出站检查超时的量级与归属是否定义（FR-005 说判定超时 fail-closed；**超时上限是多少、是否计入工具自身超时预算**、5s 级上限是否可接受，未给）
- [x] CHK010 与 009 PreToolUse 的执行顺序是否定义（FR-002 说"在真实执行前（009 PreToolUse 求值点同一位置）"；**出站检查在 PreToolUse 之前还是之后**、拒绝时是否仍记 `tool.started`，未写）

## 一致性（Consistency）

- [x] CHK011 IP 字面量拒绝的范围是否与 SSRF 防线一致（FR-006 说"IP 字面量（含回环/内网/链路本地）"；**IPv6、`0.0.0.0`、十进制/八进制变体、`localhost` 域名、DNS rebinding** 是否都在范围内，未穷举）
- [x] CHK012 三层并集与"工具例外"的优先级是否明确（决策 #3 说并集语义；**同一域名同时命中 tool 与 platform 条目时审计记哪个 scope**、是否需优先级，未定义）
- [x] CHK013 CRUD 契约的 PATCH 语义是否定义（FR-011 仿 `hooks.py` 用 `PATCH`；**是部分更新还是全量替换、`scope` 是否允许修改**未写）
- [x] CHK014 与 009 热更新口径的一致性是否声明（FR-007 说"与 009 FR-4 口径一致"；**009 的既有实现是否有缓存/失效机制**、038 是否需要复用同一机制，未核对）
- [x] CHK015 远程沙箱契约预留的验收判据是否定义（FR-010 只说"保留枚举与接口预留，不实现本体"；**如何验证"未实现"**（无进程管理/镜像/远程网络模块）+ `execution_location == "remote_sandbox"` 时的运行期行为，未写）

## Notes

- 条目编号 CHK001–CHK015 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表原文。
- 本特性需求风险集中在**安全边界**（CHK002/CHK003/CHK011）：白名单匹配规则错一位就是绕过或误拦；其次是**可用性**（CHK005/CHK009/CHK013）与**审计可回溯**（CHK006/CHK012）。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

15 条全部达标，均经 `spec.md` 新增的「判定口径补充（R-1~R-15）」消解：

- CHK001（工具级绑定键）→ R-2：`scope="tool"` 按 `tool_id` 过滤，仅对绑定工具生效（未定义工具删除后的清理，属运维动作）。
- CHK002（大小写/IDN/`*.`）→ R-1：双侧 lower + IDNA + 剥离 `*.` 前缀与尾点，`*.example.com` 与 `example.com` 等价。
- CHK003（路径前缀边界）→ R-1：只匹配 `parsed.path`、不含查询串，`/<prefix>` 或 `/<prefix>/…` 语义。
- CHK004（`final_url` 缺失）→ R-10：入口已拦 `target_url`，无 `final_url` 时不做二次判定。
- CHK005（热更新时效）→ R-4：≤2s（`DEFAULT_SNAPSHOT_TTL_SECONDS = 2.0`）或 `invalidate()` 即时。
- CHK006（审计兼容）→ R-7：同集合 `enterprise_tool_audit`，新增三事件与既有事件并存，URL 脱敏。
- CHK007（MCP 目标枚举）→ R-9：`decide_urls` 全量求值、任一拒绝即拒绝；MCP 内部请求不在客户端可见面内（已知边界）。
- CHK008（平台条目可见性）→ R-15：平台条目租户可读不可写。
- CHK009（超时量级）→ R-5：`DEFAULT_EGRESS_TIMEOUT_MS = 5000`，只覆盖评估、不计工具网络耗时。
- CHK010（与 009 顺序）→ R-11：先出站判定后真实请求，拒绝不进入执行阶段。
- CHK011（IP 字面量范围）→ R-3：`ipaddress` 全覆盖 IPv4/IPv6；不承诺 DNS rebinding 防护（已声明）。
- CHK012（scope 优先级）→ R-2：`tool(0) → tenant(1) → platform(2)` 首个命中归因。
- CHK013（PATCH 语义）→ R-8：部分更新，`scope`/`tool_id` 变更需重校租户归属。
- CHK014（与 009 热更新口径）→ R-4：以"≤2s + invalidate"为可测判据，不复用 009 内部机制。
- CHK015（远程沙箱验收判据）→ R-14：枚举保留 + 无实现代码 + `remote_sandbox` 运行期显式拒绝。

**验收证据**：`services/admin-api/tests/test_egress_allowlist.py` 15 passed；`services/chat-api/tests/test_egress_guard.py` 28 passed；实现落点 `services/chat-api/app/enterprise_capabilities/tools/egress_guard.py`、`services/admin-api/app/services/egress_store.py`、`services/admin-api/app/api/routes/egress.py`；接入点 `tools/service.py:583-599`、`browser/service.py:46/141-143`、`browser/engine/action_contracts/_navigate.py`。
