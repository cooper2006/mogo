# 025 US2 — 批量语义（T027）与降级空值（T028）扫描报告

- 范围：`services/admin-api/app/api/routes/` 全部路由文件（38 个模块，共 14545 行）
- 任务：`specs/025-api-contract-hardening/tasks.md` Phase 3 — T027（FR-14 / QF-245 / QF-247 / QF-248）、T028（FR-15 / QF-252）
- 结论先行：**admin-api 里真正的"批量端点"只有 3 个**（position-roles 批量分配 + ontologies 两个批量授予）；`knowledge_documents.py` **不含任何批量端点**（任务前提需修正）。3 个批量端点均**缺逐项结果数组 / 整体 status / partial**，且原本**都没有批量上限**——本轮已在入口补上上限校验（T027 最小整改）。降级空值发现 **3 处明确违规**（egress、dashboard 两处）+ 2 处弱信号，本轮**只报告未改**（需 Lead 评审）。

---

## 1. 批量端点扫描

### 1.1 批量端点清单

| 端点 | 方法 + 路径 + 行号 | 接受列表输入 | 上限现状 | 超限行为 | 逐项结果数组 | 整体 `status` | `partial` | 违规判断 | 建议 |
|---|---|---|---|---|---|---|---|---|---|
| 批量分配角色 `bulk_assign_roles` | POST `/position-roles/assignments/bulk` · `position_roles.py:169` | 是（`userIds[]` + `roleIds[]`，均 `min_length=1`） | **原本无**，本轮已补 100 | 原本不截断；现 422（结构化 detail） | 无 → 仅 `{"updated": N}` | 无 | 无（原子 `bulk_write`，失败整体回滚） | 违 FR-14：缺逐项结果 + `status` + `partial` | 上限已修；逐项结果 + `partial` 需 Lead 评审后补 |
| 批量授予（用户级）`grant_user_permissions` | POST `/ontologies/users/{user_id}/permissions` · `ontologies.py:176` | 是（`ontologyIds[]`，`min_length=1`） | **原本无**，本轮已补 100 | 原本不截断；现 422 | 无 → 仅 `{"granted": N, "ontologyIds": [...]}` | 无 | 无（顺序 `upsert_grant`，非原子） | 违 FR-14 | 上限已修；建议批量改 `bulk_write` + 逐项结果 + `partial` |
| 批量授予（主体级）`grant_subject_permissions` | POST `/ontologies/subjects/{subject_type}/{subject_id}/permissions` · `ontologies.py:238` | 是（`ontologyIds[]`） | **原本无**，本轮已补 100 | 原本不截断；现 422 | 无 | 无 | 无 | 违 FR-14 | 同上 |

### 1.2 明确不是批量端点的接口（已排除）

| 端点 | 排除理由 |
|---|---|
| `knowledge_documents.py` 全部 17 个端点 | **无任何端点接收数组输入**；schema 全为单对象（`DocumentUpdatePayload` / `PreviewCallbackPayload` / `ParseCallbackPayload` / `IndexCallbackPayload`），`upload_document` 是单文件 `UploadFile`，无 `/batch` `/bulk` 路径。任务"在 knowledge_documents.py 批量端点入口加上限"的目标位置**不存在** |
| `directory.py:746 POST /invites` | `roleIds` 是**关联角色**（单个邀请链接），非批量处理对象 |
| `governance.py:145 / 167` grant / revoke | 均为**单个** `code`（`PermissionGrantIn` / `PermissionRevokeIn`） |
| `ontologies.py` GET grants / audit / `revoke` | 只读列表 / 单 `ontology_id` 路径参数，非批量写入 |
| 各 `GET .../list` | 只读分页/列表，非批量写入，不在 T027 范围 |

> 附带观察：`knowledge_documents.py:1477` 的 `db[CHUNK_COLLECTION].insert_many(rows, ordered=False)` 是**回调内部**的分片写入（非用户侧批量端点），允许部分写入后仍把文档标为 `parsed`，属内部一致性风险，不在 T027 交付范围，仅记录备查。

---

## 2. T027 最小整改（本轮已实施）

新增可复用的统一上限校验，放 `knowledge_documents.py`（模块级常量 + 纯函数，不改任何成功路径响应结构）：

- `BATCH_LIMIT = 100`（`knowledge_documents.py:56`）
- `validate_batch_size(items, *, field, path, limit=BATCH_LIMIT) -> int`（`knowledge_documents.py:59`）：`count > limit` 时抛 `HTTPException(422, detail={code, message, field, path, limit, count})`，**detail 是结构化 dict**（`code="api.validation_error"`，取自 `app.core.errors.ApiErrorCode`），非裸字符串；空列表不在此拦截；返回条数供复用。
- 挂载点（均加在入口，成功路径返回结构一字未改）：
  - `position_roles.py:173` → `validate_batch_size(payload.userIds, field="userIds", path="/position-roles/assignments/bulk")`
  - `ontologies.py:183` → `validate_batch_size(payload.ontologyIds, field="ontologyIds", path="/ontologies/users/{user_id}/permissions")`
  - `ontologies.py:248` → `validate_batch_size(payload.ontologyIds, field="ontologyIds", path="/ontologies/subjects/{subject_type}/{subject_id}/permissions")`

关键 diff 示意（新增，不改既有行）：

```python
# knowledge_documents.py 顶部
from app.core.errors import ApiErrorCode   # 新增导入
BATCH_LIMIT = 100                          # 模块级常量

def validate_batch_size(items, *, field="items", path="/knowledge/documents", limit=BATCH_LIMIT) -> int:
    count = len(items)
    if count > limit:
        raise HTTPException(status_code=422, detail={
            "code": ApiErrorCode.VALIDATION_ERROR.value,
            "message": f"批量请求数量超过上限：{count} > {limit}",
            "field": field, "path": path, "limit": limit, "count": count,
        })
    return count

# position_roles.py:173 / ontologies.py:183,248  各批量端点入口插入一行
validate_batch_size(payload.userIds, field="userIds", path="/position-roles/assignments/bulk")
```

---

## 3. 降级场景扫描（T028，**只报告未改**）

| 文件:行号 | 场景 | 返回什么 | T028 判断 | 建议 |
|---|---|---|---|---|
| `egress.py:192-195` | `GET /logs` `list_egress_logs`：`get_db()` 抛异常（:192） **或** 返回 `None`（:194） | `{"items": [], "total": 0, "page": ..., "page_size": ...}` | ❌ **违**：用空数组冒充"确实没有日志"，客户端无法区分真空与降级 | 改为 `{"items": null, "total": 0, "degraded": true, ...}` |
| `dashboard.py:936-940` | `_quota_anomalies`：事件集合缺失/不可读 | `rows = []` → `summarize_quota_alerts([])` 空聚合 | ❌ **违**：空聚合结果无 `degraded` 标记 | 改 `null` + `degraded: true` |
| `dashboard.py:633-636` | usage 维度读取失败（:634）或确实无数据（:636） | `empty_usage_section()` → `{calls:0, activeUsers:{}, skillRanking:[], retrievalRanking:[], timeSeries:[]}` | ❌ **违**：空结构冒充"真实 0 使用量"；且 :636 把"无数据"与"降级"混为一谈 | 改 `null` + `degraded: true` |
| `dashboard.py:383-396` | `_approval_pending_count`：缺审批集合 | `continue` 循环 → `return 0`（:396） | ⚠️ 弱：0 计数无降级标记 | 可加 `degraded` 元信息（非空容器，优先级低） |
| `dashboard.py:257-270` | `_percentile_fallback`：`$percentile` 聚合失败 | `return None, None`（:270） | ✅ **合规**（返回 `null`） | 可选：补 `degraded: true` 元信息 |
| `auth.py:1153-1157` | refresh token 签发失败 | `return None` | ✅ **合规**（返回 `null`） | 可选：补 `degraded: true` |
| `portal_admin.py:239-244` | `_grant_ttl_days` 读失败 | `return DEFAULT_GRANT_TTL_DAYS`（标量兜底） | ✅ 合规（非空容器） | 无需改 |
| `setup.py:124-164` | 各探活失败（mongo/redis/storage/http） | `SetupServiceStatus(ok=False, message=str(exc)[:160])` | ✅ **合规**（结构化降级，自带 `ok` 标记） | 无需改 |
| `connector_market.py:243-247` | 治理层能力注册失败 | 仅 `logger.warning`，不影响响应 | ✅ 合规（旁路） | 无需改 |
| `knowledge_documents.py:875, 914, 960, 1014, 1071, 1250, 1477, 1594` | 上传/预览/解析/索引等失败 | 多为 `raise`（HTTPException / re-raise）或把文档标 `*_status=failed` + `*_error` | ✅ 合规（错误传播/失败状态，非空值降级） | 无需改 |
| `egress.py:225` | `_to_log_item` 字段级 `details` 解析失败 | `details = {}` | ⚠️ 弱：字段级兜底，非端点级降级 | 可保持，或加字段级 `degraded` |

**整改建议（需 Lead 评审后决定，本轮未改）**：优先修 `egress.py:192` 与 `dashboard.py:936 / :633` 三处 —— 它们把"后端不可用"伪装成"数据为空"，是 FR-15 / QF-252 明确禁止的误导性空值。统一口径：降级时响应承载字段给 `null` + 顶层 `degraded: true` + `reason`，前端据此渲染"服务降级"态而非"无数据"态。

---

## 4. 测试

新增 `services/admin-api/tests/test_batch_semantics_t027_t028.py`（纯内存，不连 Mongo/Redis）：

- `BATCH_LIMIT == 100` 断言
- `validate_batch_size`：100 放行 / 101 抛 422 且 `detail` 为 dict 含 `code/limit=100/count=101/field/path` / 空列表不拦截 / 自定义 `limit` 生效
- 走真实路由（monkeypatch `OntologyPermissionService.batch_grant` + `get_current_admin_user` 依赖替身）：ontologies 批量授予 100 → 200 且 `granted=100`；101 → 422 且结构化 detail
- T028 合成坏样例判断函数 `is_misleading_empty_fallback` 的 5 个用例（空数组无标记 → True；`null`+`degraded:true` → False）

执行结果：

```text
$ python -m pytest tests/test_batch_semantics_t027_t028.py tests/test_ontology_permission_routes.py tests/test_ontology_permission_service.py tests/test_egress_allowlist.py -q
57 passed
```

新测试 12 个全绿；相关既有测试（ontology 路由/服务、egress）全绿，未受本轮改动影响。

---

## 5. 本轮改动文件清单

| 文件 | 类型 |
|---|---|
| `services/admin-api/app/api/routes/knowledge_documents.py` | 修改：新增 `BATCH_LIMIT` + `validate_batch_size` |
| `services/admin-api/app/api/routes/position_roles.py` | 修改：批量分配入口加上限校验 |
| `services/admin-api/app/api/routes/ontologies.py` | 修改：两个批量授予入口加上限校验 |
| `services/admin-api/tests/test_batch_semantics_t027_t028.py` | 新建：T027/T028 测试 |
| `docs/025-us2-batch-degraded-scan.md` | 新建：本报告 |

未 commit、未 push。