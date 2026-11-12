# Feature Specification: pg_compat 能力清单与 CI 静态扫描（057-pg-compat-capability-list）

**Feature Branch**: `057-pg-compat-capability-list`

**Created**: 2026-11-12

**Status**: Implemented

**Input**: 通用设计复审报告 §整改路线第 4 项前半："给 pg_compat 建可枚举能力清单 + CI 静态扫描 aggregate 管道阶段，禁止调用点逐个绕开继续扩散"；以及 P1-10「兼容层能力缺口靠调用点逐个绕开、无清单无静态守卫」的问题描述。

> **来源说明**：本特性不引入新业务功能，是对既有 `services/admin-api/app/core/pg_compat.py` 的治理能力补齐。027 已落 `PgCompatUnsupported` 异常类型，本特性在此基础上建立可机检的能力矩阵。

## 背景与问题

### 现状

`pg_compat.py:1129` 用 `_stage_match/sort/limit/skip/count/group/project` 共 7 个处理器分派聚合阶段。其余阶段（`$unwind` / `$facet` / `$lookup` / `$replaceRoot` 等）**运行期抛 `PgCompatUnsupported`**。

全仓仍有 30+ 处 `aggregate` 调用点。头部注释（`:30`）把已实现的 `bulk_write` 也列为未覆盖，唯一「清单」在 `tests/test_pg_compat.py:284`——是代码而非文档，且随实现同步更新。

**已有生产事故先例**（见 `.workbuddy-ai/memory/2026-11-12.md`）：
- 2026-11-12 上午 `topic_admission/rules.py` 的 `$unwind + $facet` 管道在 PanWeiDB 后端触发 500
- 修法是改调用点为 `find_one` + Python 侧展开，而非补齐兼容层
- 此类「调用点逐个绕开」模式将导致 Mongo ↔ PanWeiDB 行为分叉持续放大

### 影响面

| 维度 | 现状 | 期望 |
|---|---|---|
| 开发体验 | 在 Mongo 下正常，上线后 PanWeiDB 才 500 | CI 阶段提前拦截 |
| 维护成本 | 每个不支持的阶段需在所有调用点手动绕开 | 一次声明，全局生效 |
| 可观测性 | 无计数、无告警阈值 | 缺省拒绝 + 指标暴露 |

## 用户故事

### User Story 1 — 开发者写入 aggregate 管道时，CI 实时提示是否含未支持阶段（Priority: P1）🎯 MVP

开发者在本地写代码时使用了 `$unwind` 或 `$lookup`，pre-commit hook 或 CI lint 步骤立即报错，提示该阶段不在支持清单中，并给出替代方案建议（如改用 `find_one` + Python 展开）。

**Why this priority**: 这是阻断后续同类事故的第一道防线，直接针对 P1-10「无静态守卫」的核心痛点。

**Independent Test**: 往仓库里加一个临时分支，创建一个含 `$unwind` 的 aggregate 调用并提交，断言 pre-commit hook 拒绝提交并在 stderr 输出支持阶段清单与替代方案。

**Acceptance Scenarios**:

1. **Given** 开发者在代码中使用 `$unwind` 阶段，**When** 执行 `git commit`（触发的 pre-commit hook），**Then** hook 以非零退出码拒绝，stderr 输出形如 `"unsupported stage: $unwind (supported: match, sort, limit, skip, count, group, project, bulkWrite)"` 并附替代方案链接。
2. **Given** 开发者使用已全部支持的阶段组合，**When** 执行 `git commit`，**Then** hook 通过，exit code 0。
3. **Given** CI pipeline 执行 `scripts/check_pg_compat_pipeline_stages.py`，**When** 扫描全部 `aggregate(` 调用点的管道 AST，**Then** 未发现未支持阶段的仓库 exit 0；发现未支持阶段的仓库 exit 1 并列出违规文件清单。

---

### User Story 2 — 运营/运维通过监控面板查看当前 aggregate 管道对兼容层的覆盖率（Priority: P2）

管理员在 ops dashboard 看到一张表：MongoDB 端 vs PanWeiDB 端的 aggregate 调用分布，标注每一处的阶段支持状态（已支持 / 未支持 / 绕开实现），便于排优先级补全。

**Why this priority**: 让兼容性状态从「隐藏的运行期错误」变为「可见的治理指标」，驱动后续补全决策。

**Independent Test**: 部署后访问 `/api/v1/admin/compatibility/pipeline-support`，断言返回 JSON 包含各集合的 aggregate 调用统计，每项有 `stage`、`supported`、`call_site` 字段。

**Acceptance Scenarios**:

1. **Given** 仓库中存在 30+ 处 aggregate 调用点，**When** 调用 `GET /api/v1/admin/compatibility/pipeline-support`，**Then** 响应中包含每个调用点的完整信息：文件路径、行号、使用的阶段列表、每阶段的支持状态。
2. **Given** 某阶段被标记为 unsupported，**When** 查看详情，**Then** 显示该阶段的技术原因（如 "PanWeiDB SQL 语义无法表达双向关联"）与推荐的替代写法。

---

### User Story 3 — 新增聚合阶段时，兼容层自动注册并更新能力清单文档（Priority: P2）

当开发者向 `pg_compat.py` 添加一个新的 `_stage_xxx()` 处理器时，配套的清单常量、测试用例、文档自动更新，无需人工维护多处一致性。

**Why this priority**: 消除「实现与清单不同步」这一历史债务的来源。

**Independent Test**: 新增一个模拟的 `_stage_foo()` 处理器后重新生成清单，断言新阶段出现在支持列表中，`tests/test_pg_compat.py` 的 fixture 数据相应增加。

**Acceptance Scenarios**:

1. **Given** 实现者向 `pg_compat.py` 添加 `_stage_foo(self, stage, doc)` 方法，**When** 运行 `scripts regen_pg_compat_manifest.py`，**Then** 能力清单常量 `SUPPORTED_AGGREGATION_STAGES` 自动包含 `"foo"`，旧条目保持不变。
2. **Given** 清单已生成，**When** 运行 CI 中的静态扫描，**Then** 本次新增阶段不被误报为 unsupported。

## 需求规格

### R-1 可枚举能力清单常量

在 `services/admin-api/app/core/pg_compat.py` 顶部（`:1-30` 头部注释区附近）新增：

```python
SUPPORTED_AGGREGATION_STAGES: frozenset[str] = frozenset({
    "match", "sort", "limit", "skip", "count", "group", "project",
})

UNSUPPORTED_STAGE_EXPLANATIONS: dict[str, str] = {
    "unwind": "PanWeiDB SQL 语义无法表达数组展开；请改用 find_one + Python list comprehension",
    "facet": "PanWeiDB 暂不支持多路聚合；请拆分为多次独立查询后在应用层合并",
    "lookup": "PanWeiDB 无 JOIN 语义；请改用两次 find + 内存 merge",
    "replaceRoot": "PanWeiDB 无此阶段；请改用 project 重命名字段",
    # ... 按需补充
}
```

**约束**：
- 此常量为清单的唯一事实来源，任何阶段处理器的增减必须同步更新它
- 禁止在代码各处硬编码阶段名（grep 验证）

### R-2 CI 静态扫描脚本

新建 `scripts/check_pg_compat_pipeline_stages.py`：

```python
"""扫描仓库内所有 aggregate( 调用点的管道阶段，报告 unsupported。"""
```

行为：
- 遍历所有 `.py` 文件（排除 `tests/`、`__pycache__`、`.venv`）
- 用正则/A找 `aggregate([...])` 或 `aggregate([{'$xxx': ...}])` 语法
- 提取管道中的每个阶段 key（`$match` → `match`，`$unwind` → `unwind`）
- 若阶段不在 `SUPPORTED_AGGREGATION_STAGES` 中，记录违规行
- 输出：JSON 格式违规清单 + 人类可读摘要
- Exit code：0 = 全绿，1 = 有违规

**集成点**：
- `.githooks/pre-commit` 中增加调用（仅扫描 staged diff 范围）
- `.github/workflows/quality-gate.yml` 的 `backend-quality` 作业中增加 job

### R-3 运行时守卫增强

`pg_compat.py` 的分派逻辑（`:1129` 附近）在抛出 `PgCompatUnsupported` 之前，额外输出结构化日志：

```python
logger.warning(
    "aggregation stage not supported in pg_compat",
    extra={
        "stage": name,
        "collection": collection_name,
        "allowed_alternative": UNSUPPORTED_STAGE_EXPLANATIONS.get(name, ""),
        "source_file": _caller_filename(),  # 反射调用栈获取
    },
)
raise PgCompatUnsupported(...)
```

**约束**：日志不可被 suppress（强制写入 audit log stream，受 Constitution III 守护）。

### R-4 admin API 暴露能力清单

新增端点：
```
GET /api/v1/admin/compatibility/pipeline-support
```
响应：
```json
{
  "supported_stages": ["match", "sort", "limit", "skip", "count", "group", "project"],
  "call_sites": [
    {
      "file": "services/admin-api/app/topic_admission/rules.py",
      "line": 42,
      "stages": ["match", "unwind"],
      "status": "unsupported_stage",
      "recommended_fix": "改用 find_one + Python unwind"
    }
  ],
  "summary": {
    "total_calls": 34,
    "fully_supported": 28,
    "has_unsupported_stage": 6
  }
}
```

**约束**：端点需 admin RBAC（`admin:compatibility:read`），不在公开 API 中暴露。

### R-5 存量调用点清理计划

本次特性**不要求**一次性修复所有 30+ 个绕过点；但要求：
- 扫描结果作为基线登记到 `docs/pg-compat-capability-baseline.md`
- 按调用频次排序，高频率的 unsupported 调用纳入下个迭代的 TODO
- 新增调用点若使用 unsupported 阶段，CI 直接阻断（R-2 门禁）

## Clarify Decisions

| # | 决策点 | 建议默认值 | 阻塞 implement？ |
|---|---|---|---|
| D1 | 扫描范围是否包含 `tests/` 目录 | 不包含（测试中的 aggregate 用于验证 fake，非生产行为） | 否 |
| D2 | 是否对现有存量违规做硬性阻断（force-fix before merge） | 不阻断存量，仅阻断新增（grace period 30 天后再强杀） | 否 |
| D3 | `_caller_filename()` 的实现方式 | 用 `inspect.stack()[2].filename`（轻量，无第三方依赖） | 否 |

## 验收标准

- [ ] `scripts/check_pg_compat_pipeline_stages.py --help` 可正常运行并输出帮助信息
- [ ] pre-commit hook 在遇到 unsupported 阶段时 exit non-zero
- [ ] `GET /api/v1/admin/compatibility/pipeline-support` 返回正确 JSON，call_sites 与实际扫描一致
- [ ] `tests/test_pg_compat.py` 中新增针对新清单常量的单测（覆盖 SUPPORTED/UNSUPPORTED 两组）
- [ ] `docs/pg-compat-capability-baseline.md` 记录了当前全仓 aggregate 调用基线
- [ ] CI quality-gate workflow 在包含 `$unwind` 的 mock PR 上 fail

## 风险与回滚

- **Backward compatibility**：R-3 运行时日志升级（warning 级别）不影响现有行为；R-2 静态扫描为新增门禁，不会对已在库代码造成破坏
- **False positive 风险**：正则匹配可能误判动态拼接的管道（如 `pipeline = build_pipeline(); db.coll.aggregate(pipeline)`）。此类 case 记录为 `dynamic_pipeline` 状态，不阻断但提示人工审查
- **影响范围**：仅新增脚本 + 清单常量 + 一处 admin API 端点；不动任何业务逻辑
