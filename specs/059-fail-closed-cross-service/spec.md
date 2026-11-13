# Feature Specification: 跨服务 fail-closed 可机检约束（059-fail-closed-cross-service）

**Feature Branch**: `059-fail-closed-cross-service`

**Created**: 2026-11-12

**Status**: Implemented

**Input**: 通用设计复审报告 §整改路线第 7 项："把「异常/未知/未配置一律拒绝」写成跨三服务可机检约束（CI 静态门禁 + 统一缺省常量），并同步修订两份 API 权威文档、补 API-Version 中间件到另两个服务"

涵盖 P1-16、P1-17 两项问题。

## 背景与问题

### P1-16：缺省语义不统一

| 位置 | 实况 | 违反宪法原则 |
|---|---|---|
| `admin-api/governance/risk.py:141-143` | `_canon()` 注释明写「never deny-by-default for unknowns」→ `return "allow"` | 宪法 III（security-first） |
| `admin-api/topic_admission/service.py:17-18,55` | `mode=off` → `allowed=True` | 009 spec R-2 fail-closed |
| `admin-api/ontology_permission/service.py:103,107` | `enforce` 默认 False、`effectiveDefault=allow` | 020 spec「默认 deny」 |
| `chat-api/im_gateway/bindings.py:269-273` | `db is None` / `row is None` 均 `return True` | im_gateway.py:69-71 自认 fail-open |

对照：
- `.specify/memory/constitution.md` 原则 III（Security and Data Protection）
- 009 `spec.md:112-113`「超时/异常/规则解析失败一律 fail_closed」
- 020 spec「一律拒绝，不回退默认租户」

### P1-17：契约双权威且互相冲突

| 文档 | 声明身份 | 实际问题 |
|---|---|---|
| `docs/error-codes.md:3` | 「唯一权威字典」 | `api.*` 小写 15 码、配额 429、`fields[]`/`error_detail` |
| `docs/api-specification.md:51-80` | 未声明但被消费方参考 | `VALIDATION_ERROR` 大写、`details`/`request_id`、配额 402 `PAYMENT_REQUIRED`，且有「当前行为忽略 Accept 头」「QF-225 修复计划」等旧态描述 |
| `specs/INDEX.md:96` | 宣称 025 52/52「错误码统一结构落地」 | 消费方实际仍收到两套不同格式 |
| `docs/api-versioning.md:28` | 称三服务同型 | `ApiVersionMiddleware` 只在 admin-api 注册，chat-api / document-parser 只注册 `LegacyApiRedirectMiddleware` |

## 用户故事

### User Story 1 — 代码审查时，CI 自动检测「unknown 情况回退 allow」的反模式（Priority: P1）🎯 MVP

安全工程师或 reviewer 在 PR 中新增的代码如果出现 `except ...: return True`、`if db is None: allow`、`default = "allow"` 这类 fail-open 反模式，CI lint 立即报错。

**Why this priority**: 这是堵住未来同类缺陷流入生产的最有效手段——P1-16 列举的四处漏洞都是历史上某个开发者在某个 branch 顺手写的缺省放行，每次都是人为疏漏，只有自动化才能根除。

**Independent Test**: 在一个临时分支中写入 `if db is None: return True` 的伪代码并提交 PR，断言 CI 的 fail-open 扫描作业 fail，并输出违规行号和推荐修复。

**Acceptance Scenarios**:

1. **Given** 新增代码中含 `except .*: return True`（无条件放行）模式，**When** 执行 CI `fail-open-scan` job，**Then** job 失败，输出违规文件:行号 + 违反的宪法条款引用。
2. **Given** 新增代码中含显式 fail-closed 的防御性写法（`except ...: logger.error(...); raise` 或 `return False`），**When** 执行同样的 job，**Then** job 通过。
3. **Given** 代码中因历史原因不得不保留的 fail-open 段落（需经架构师审批豁免），**When** 在对应行加上 `# fail-open-exempt: <理由>` 注解，**Then** CI 扫描识别豁免标记并忽略该行。

---

### User Story 2 — 所有治理层（risk / topic_admission / ontology_permission / im_gateway）在「未知/异常/未配置」情况下一律 fail-closed（Priority: P1）

修改四处已知漏洞点及其周边类似模式，确保它们在所有分支都遵循 fail-closed 语义；同时对新增治理点建立「缺省 deny」的代码模板。

**Why this priority**: P1-16 指出的四处在产漏洞虽然目前「不是主路径漏洞」（因为上游已有其他门禁），但它们形成了一致性风险——新增治理点会继续各写各的缺省值，扩大攻击面。

**Independent Test**: 分别构造四个漏洞点对应的测试用例（db 不可达 / 规则未知 / enforce=false / row 不存在），断言每个点都返回 denial 而非授权。

**Acceptance Scenarios**:

1. **Given** `risk.py:_canon()` 收到未知 cell（既不在 allow 也不在 deny 表中），**When** 求值，**Then** 返回 `denied`（原 `allow` 改为 `denied`），并写 warning 日志提示规则表缺少该 cell 的配置。
2. **Given** `admin-api/topic_admission/service.py` 的 `preview()` 的 mode 配置为 `off`，**When** 评估请求，**Then** 返回 `allowed=False`（原 `allowed=True` 改为 `allowed=False`），日志记录 "topic admission disabled → deny by default"。**注**：chat-api 侧 `governance/topic_admission.py` 的 `evaluate()` 因 `mode=off` 为功能开关语义，保留 `return True` 并加 `# fail-open-exempt:` 豁免（详见 R-5）。
3. **Given** `ontology_permission.service.enforce=False`（未启用权限检查），**When** 查询有效权限，**Then** 返回空集（原 `effectiveDefault=allow` 改为 `effectiveDefault=deny`）。
4. **Given** `im_gateway.bindings` 的 db 连接不可用或返回行不存在，**When** 鉴权，**Then** 返回 `allowed=False`（原 `return True` 改为 `return False`），记录 error 日志便于排查。

---

### User Story 3 — 错误码契约与 API 版本中间件在三服务间保持一致（Priority: P2）

删除 `docs/error-codes.md` 与 `docs/api-specification.md` 中的一份，确立唯一权威源；在 chat-api 与 document-parser 中注册 `ApiVersionMiddleware`，使其响应头携带正确的 `API-Version` 字段。

**Why this priority**: P1-17 导致消费方无法可靠地解析错误响应（格式二义性），且 API 版本管理混乱不利于后续大版本升级。虽非安全类风险，但影响开发者体验和契约可测性。

**Independent Test**: 用 curl 分别请求三个服务的同一健康检查端点，断言响应头 `API-Version` 均为 `1.0.0`；调用一个触发 VALIDATION_ERROR 的接口，断言响应体结构与唯一权威字典一致。

**Acceptance Scenarios**:

1. **Given** 消费者请求 admin-api 的一个 422 错误端点，**When** 接收响应体，**Then** 字段结构符合 `docs/error-codes.md` 的定义（小写 `api.validation_error`、含 `fields[]`、含 `error_detail`），不含 `VALIDATION_ERROR` 大写变体。
2. **Given** 消费者请求 chat-api 的同类型错误，**When** 接收响应，**Then** 结构与 admin-api 完全一致（跨服务统一）。
3. **Given** 任一服务的响应包含 `API-Version` 响应头，**When** 解析，**Then** 值为 `1.0.0`（与 `contracts/admin-api.yaml:2` 对齐，废弃 `0.2.8` OpenAPI info.version 的歧义）。

## 需求规格

### R-1 fail-closed 缺省常量统一

在 `services/common/fail_open_guard.py`（新建）定义：

```python
"""Cross-service fail-closed enforcement utilities."""

# 统一的「未知 → 拒绝」语义
DEFAULT_DENY = True       # 原名 DENY_BY_DEFAULT，消除 double-negative 认知负担
DEFAULT_ALLOW = False

# 豁免标记（供静态扫描识别）
FAIL_OPEN_EXEMPT_COMMENT = "fail-open-exempt:"

def enforce_fail_closed(value: bool, context: str = "", exempt_comment: str = "") -> bool:
    """Ensure a decision defaults to denied when indeterminate.
    
    Args:
        value: the computed decision (True=allow, False=deny)
        context: human-readable description of where this was decided
        exempt_comment: if set, marks this invocation as intentionally allow-by-default
    
    Returns:
        The decision, coerced to deny if value is indeterminate (None).
    """
    if value is None:
        import logging
        logging.getLogger(__name__).warning(
            "fail-closed coercion: indeterminate decision at %s → deny", context
        )
        return False
    if exempt_comment and FAIL_OPEN_EXEMPT_COMMENT in exempt_comment:
        return bool(value)
    return bool(value)
```

各治理层在用该方法包裹其「兜底返回 allow」的逻辑：

```python
# risk.py:_canon() 改造示例
def _canon(self, cell: tuple) -> str:
    result = self._lookup(cell)
    return str(enforce_fail_closed(result, context=f"risk._canon({cell})") or "deny"))
```

### R-2 CI fail-open 静态扫描

新建 `scripts/check_fail_open_patterns.py`：

```python
"""Scan for fail-open anti-patterns across the codebase.

Pattern 1: except ... : return True (bare allow in exception handler)
Pattern 2: if db is None: return True / if row is None: return True
Pattern 3: default=\"allow\" or effectiveDefault=\"allow\"
Pattern 4: mode == \"off\" → allowed = True
"""
```

行为：
- 用 ast 模块扫描 Python 源码（比正则更安全，不误报字符串字面量外的内容）
- 识别上述四种模式的变体
- 支持 `# fail-open-exempt: <理由>` 注释豁免
- 输出 JSON 清单 + 人类可读摘要
- Exit code 0 = 全绿，1 = 发现违规

集成至：
- `.githooks/pre-commit`（仅扫 staged diff）
- `.github/workflows/quality-gate.yml` 新增 `fail-open-scan` job

### R-3 错误码权威文档合并

> **落地口径更正（2026-11-13）**：下面的「删除 §51-80」是**规划意图**，实际执行与之不同。复核 `docs/api-specification.md` 发现 **该区间并不存在错误码重复表**（51-80 行实为 §2 的 envelope 示例与 QF-234/QF-235 安全规范），因此**没有裁撤任何章节**——文件仍 361 行 / 14 个 `##` 章节。实际做法是在 `:47` 登记 DEPRECATED 权威指针，声明错误码枚举/HTTP 映射的唯一权威为 `docs/error-codes.md`（Schema v2），并说明为何不误删有效内容。目标「双权威收敛为单一权威」已达成，但动作是**登记指针**而非裁撤。`plan.md` / `quickstart.md` / `tasks.md` 中「替换/裁撤 §51-80」的措辞同为历史规划，以本节口径为准。

- ~~**删除** `docs/api-specification.md` 中 §51-80（错误码部分）~~ → 实际：在 `docs/api-specification.md:47` 登记 DEPRECATED 权威指针，保留全部章节（该区间本就不是错误码表）
- **强化** `docs/error-codes.md`，明确声明其为**唯一权威错误码字典**，并注明 schema version ✅（已落地：Schema v2 声明见 `:1-3`）
- 新增 `docs/error-codes-v2.md` 作为过渡引用（指向 v1 权威版），原 v1 内容移入 archive ✅（文件已存在，为归档存根）
- 在 `specs/025-api-contract-hardening/spec.md` 中追加 R-18：「消费方必须按 error-codes.md 解析响应，不允许假设 `VALIDATION_ERROR` 等历史大写变体仍存在」

### R-4 API-Version 中间件补装

在以下两处注册 `ApiVersionMiddleware`：
- `services/chat-api/app/main.py`：在现有的 `LegacyApiRedirectMiddleware` 注册旁边追加
- `services/document-parser/app/main.py`：同样追加

两处均使用相同的 version string `1.0.0`（与 `contracts/admin-api.yaml:2` 对齐）。`info.version: 0.2.8` 的 OpenAPI 文档字段改为 `1.0.0` 并备注「该字段当前不与运行态对齐，待 025 QF-225 修复计划闭环后统一」。

### R-5 存量已知 fail-open 点的逐处修复

按复审报告证据路径修复四处已知漏洞：

| 文件 | 原态 | 修复后 |
|---|---|---|
| `admin-api/governance/risk.py:141-143` | `return "allow"` for unknown cell | `return "deny"` + warning log |
| `admin-api/topic_admission/service.py:17-18,55` | `mode=off → allowed=True` | `mode=off → allowed=False`（`preview()` 中 `allowed = mode != "off" and ...`） |
| `admin-api/ontology_permission/service.py:103,107` | `effectiveDefault=allow` | `effectiveDefault=deny` |
| `chat-api/im_gateway/bindings.py:269-273` | `db is None/row is None → return True` | `return False` + error log |

**chat-api 侧 topic_admission 的豁免**：`chat-api/app/governance/topic_admission.py:38-39` 的 `evaluate()` 中 `mode=off → return True` 予以保留，并加 `# fail-open-exempt:` 注释豁免。理由：该处 `mode=off` 是管理员**显式关闭准入功能的功能开关**，而非「异常/未知状态的兜底放行」；若改为 deny，「关闭功能」将变成「拒绝全部请求」，与功能开关语义相悖。此豁免经 CODEOWNERS review，由 `check_fail_open_patterns.py` 识别豁免标记后放行，并有 `test_topic_admission_mode_off.py` 覆盖。

每处修复后补单测（回归当前行为 + 断言修复后的 fail-closed 语义）。

## Clarify Decisions

| # | 决策点 | 建议默认值 | 阻塞 implement？ |
|---|---|---|---|
| D1 | fail-open 豁免是否需要架构委员会审批流程 | 否；仅需要 `# fail-open-exempt: <作者>/<理由>` 注释，接受 CODEOWNERS review | 否 |
| D2 | `docs/api-specification.md` 是否整体删除还是仅裁撤错误码章节 | **原决策**：仅裁撤 §51-80 错误码部分，其余保留。**实际落地（2026-11-13 复核）**：该区间并无可裁撤的错误码表（实为 envelope 示例与安全规范），故未删除任何章节，仅在 `:47` 登记 DEPRECATED 权威指针；「其余保留」的决策结论不变 | 否 |
| D3 | `info.version: 0.2.8` 的 OpenAPI 字段是否本轮同步改掉 | 不改（影响面广，需配合开放 API 消费者的协议变更），仅在 error-codes.md 中标注「当前版本号差异系历史遗留，运行时请以 API-Version 响应头为准」 | 否 |
| D4 | `chat-api/governance/topic_admission.py` 的 `mode=off` 是否与 admin-api 侧同步改为 deny | 不改；该处 `mode=off` 为管理员显式关闭准入功能的**功能开关**，非异常/未知状态兜底，改为 deny 会让「关闭功能」变成「拒绝全部请求」，语义相悖；保留 `return True` 并加 `# fail-open-exempt:` 豁免，由 CODEOWNERS review + 单测覆盖 | 否 |

## 验收标准

> **2026-11-13 机检复核口径**：逐条按磁盘与命令实测处置。末项原为条件式（「若有新增 task」），经核实本轮未新增 025 task，属条件不适用，按「原生达标」勾选并写明理由，不作模糊留白。

- [x] `scripts/check_fail_open_patterns.py` 对已知四处漏洞点能检出违规（修复前测试）
- [x] 四处漏洞修复后，对应单测全部通过（包括新增的 fail-closed 断言用例：`test_risk_canon_fail_closed.py`、`test_topic_admission_mode_off.py`、`test_ontology_enforcement.py`、`test_im_gateway_bindings_fail_closed.py`）
- [x] 修复后，`check_fail_open_patterns.py --full` 在 clean main 分支上 exit 0（✅ No fail-open anti-patterns detected.）
- [x] `docs/error-codes.md` 成为唯一错误码权威源（Schema v2 声明见 `:1-3`；`docs/api-specification.md` 不再维护错误码枚举，仅保留响应 envelope 结构说明，并在 `:47` 登记 DEPRECATED 权威指针——**未裁撤章节**，详见 R-3 落地口径更正）
- [x] chat-api 与 document-parser 的健康检查响应头含 `API-Version: 1.0.0`（`test_api_version_header.py` 3 项全绿；三服务均 `add_middleware`，含 admin-api）
- [x] `specs/INDEX.md` 的 025 tasks 勾选状态反映本轮变更（若有新增 task）：**条件不成立**——059 未新增任何 025 task，025 行维持 `52/52`（`specs/INDEX.md:107`），无需同步；059 自身的落地记录以本文件「补充四」段为准。按条件式「无新增即无需动作」判定原生达标，非缺口。

## 风险与回滚

- **回滚风险**：把已配置的 `mode=off` topic-admission 改为 deny-by-default 可能影响已在运行的环境（若线上确实有意关闭准入检查）。需在变更说明中明确：**关闭 = 拒绝，不是放行**；如需临时关闭，应通过 `ALLOW_ALL_MODE=true` 环境变量显式开启（并在日志中高频告警）
- **IM gateway 回退**：`db is None → deny` 在生产中可能导致部分 IM 渠道短暂不可用（如果 db 连接偶发故障）。缓解：加一次短暂的 retry（1 次，50ms）后再 deny，而不是立即拒绝
- **影响范围**：仅改缺省行为（原本就「应该 deny 但误写 allow」的地方），不改变任何正常路径的语义；单测覆盖确保无 regression
