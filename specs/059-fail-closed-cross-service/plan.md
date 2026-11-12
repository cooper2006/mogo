# Plan: 跨服务 fail-closed 可机检约束（059-fail-closed-cross-service）

**Input**: `specs/059-fail-closed-cross-service/spec.md`

**Created**: 2026-11-12

## 实施范围

### 新增文件

| 路径 | 用途 |
|---|---|
| `services/common/fail_open_guard.py` | 跨服务 fail-closed 工具函数（enforce_fail_closed / 豁免标记识别） |
| `scripts/check_fail_open_patterns.py` | CI 静态扫描脚本（ast 级 fail-open 反模式检测） |
| `docs/error-codes-v2.md` | 新格式错误码权威文档（承接 v1 的 deprecated 内容） |
| `services/admin-api/tests/test_fail_open_guard.py` | guard 函数单测 |
| `services/chat-api/tests/test_im_gateway_fail_closed.py` | im_gateway 修复验证 |

### 修改文件（已知漏洞点逐处修复）

| 路径 | 变更内容 |
|---|---|
| `services/admin-api/app/governance/risk.py:141-143` | `_canon()` unknown cell 由 `return "allow"` → `return "deny"` + warning log |
| `services/admin-api/app/topic_admission/service.py:17-18,55` | `mode=off` 由 `allowed=True` → `allowed=False` |
| `services/admin-api/app/ontology_permission/service.py:103,107` | `effectiveDefault="allow"` → `effectiveDefault="deny"` |
| `services/chat-api/app/im_gateway/bindings.py:269-273` | `db is None / row is None` 由 `return True` → `return False` + error log |
| `services/chat-api/app/main.py` | 注册 `ApiVersionMiddleware`（version=`1.0.0`） |
| `services/document-parser/app/main.py` | 同上 |
| `docs/api-specification.md:51-80` | 裁撤错误码章节（其余内容保留），顶部加 deprecated 注释指向 `error-codes-v2.md` |
| `docs/error-codes.md` | 顶部增加「唯一权威」声明 + schema version + 跨服务统一说明 |

### 不修改的文件

- `specs/025-api-contract-hardening/spec.md`（本特性只在其 checklist 追加 R-18，不改 spec 本体）
- OpenAPI `info.version: 0.2.8`（本轮暂不动，留待 QF-225 单独处理）

## 实施步骤

### Phase 1：统一 fail-closed 工具函数

1. 新建 `services/common/fail_open_guard.py`：
   ```python
   FAIL_OPEN_EXEMPT_MARKER = "fail-open-exempt:"
   
   def enforce_fail_closed(value: bool | None, context: str = "") -> bool:
       """Unknown/None → False (deny). Known True → True (allow)."""
       if value is None:
           logger.warning("fail-closed coercion at %s: None → deny", context)
           return False
       return bool(value)
   
   def parse_exempt_comment(line: str) -> str | None:
       """Return exempt reason if line contains the marker, else None."""
       for comment in _find_comments(line):
           if FAIL_OPEN_EXEMPT_MARKER in comment:
               return comment.split(FAIL_OPEN_EXEMPT_MARKER, 1)[1].strip()
       return None
   ```
2. 写单测：None→False、True→True、False→False、exempt marker 识别

### Phase 2：四处已知漏洞逐处修复

3. **risk.py:_canon()**（`:141-143`）：
   - 原：`return "allow"` for unknown cell
   - 新：`return enforce_fail_closed(None, context="risk._canon").and_return("deny")` + `logger.warning(...)`
   - 补单测：unknown cell → denied
4. **topic_admission/service.py**（`:17-18,55`）：
   - 原：`mode=off → allowed=True`
   - 新：`mode=off → allowed=enforce_fail_closed(False, context="topic_admission.mode_off")`
   - 补单测：mode=off → denied
5. **ontology_permission/service.py**（`:103,107`）：
   - 原：`effectiveDefault="allow"` when enforce=False
   - 新：`effectiveDefault="deny"`（无论 enforce 开关）
   - 补单测：enforce=False → empty permission set（即 deny-all）
6. **im_gateway/bindings.py**（`:269-273`）：
   - 原：`db is None or row is None → return True`
   - 新：加一次短暂 retry（1 次，50ms），仍 None → `return False` + error log
   - 补单测：mock db=None → denied；mock row=None → denied

### Phase 3：CI 静态扫描

7. 新建 `scripts/check_fail_open_patterns.py`：
   - 用 ast 模块遍历 Python AST
   - Pattern 1：`ExceptHandler` body 中含 `Return(value=Constant(value=True))`（无条件放行）
   - Pattern 2：`If(test=Compare(..., eq, Name(id='None')), body=[Return(...)])` 且返回值是 True
   - Pattern 3：字符串字面量 `default="allow"` / `effectiveDefault="allow"`
   - Pattern 4：`mode == "off"` 分支中赋值 `allowed = True`
   - 支持 `# fail-open-exempt:` 注释豁免
   - 输出 JSON 清单
8. 集成到 `.githooks/pre-commit`（`--staged` 模式）
9. 集成到 `.github/workflows/quality-gate.yml`（`fail-open-scan` job）
10. 本地跑一遍全仓扫描，确认 clean main 分支 exit 0

### Phase 4：错误码文档合并 + API-Version 中间件

11. 修改 `docs/error-codes.md`：
    - 顶部加声明：`# 唯一权威错误码字典 · Schema v2 · 2026-11-12`
    - 补充缺失的错误码（`approval.actor_mismatch`、`approval.conflict`、`tenant_id_required`）
    - 明确列出 `fields[]`、`error_detail`、配额 429 的统一结构
12. 修改 `docs/api-specification.md` 第 51-80 行：替换为指向 error-codes.md 的链接 + deprecated 说明
13. 新建 `docs/error-codes-v2.md`：承载 v1 内容（历史归档，不再维护）
14. 在 `chat-api/app/main.py` 注册 `ApiVersionMiddleware(version="1.0.0")`
15. 在 `document-parser/app/main.py` 注册同样中间件
16. 写契约测试：三服务健康检查端点均返回 `API-Version: 1.0.0` 响应头

### Phase 5：验收与文档

17. 跑 admin-api 全量测试（baseline 816 passed）
18. 跑 chat-api 全量测试（baseline 2589 passed）
19. 跑 document-parser 全量测试
20. 更新 `specs/INDEX.md`（059 条目 + SDD 路径段）
21. 更新 `CHANGELOG.md`

## 依赖关系

```
Phase 1 (guard utils) ──→ Phase 2 (fix 4 known vulns) ──→ Phase 5 (acceptance)
                                            ↓
Phase 3 (CI scan) ──────────────────────────┘（可与 Phase 2 并行）
                                            ↓
Phase 4 (docs + middleware) ────────────────┘
```

Phase 2（四处修复）相互独立，可并行推进；Phase 3（CI 扫描）独立于 Phase 2（先建扫描器再验证 clean）；Phase 4 可与 Phase 2/3 并行。

## 测试策略

| 测试类型 | 位置 | 覆盖重点 |
|---|---|---|
| 单测 | `tests/test_fail_open_guard.py` | enforce_fail_closed 三种输入、exempt 标记识别 |
| 单测 | `tests/test_risk_canon_fail_closed.py` | unknown cell → denied |
| 单测 | `tests/test_topic_admission_mode_off.py` | mode=off → denied |
| 单测 | `tests/test_ontology_enforcement.py` | enforce=False → deny-all |
| 单测 | `tests/test_im_gateway_bindings_fail_closed.py` | db=None / row=None → denied |
| CI 冒烟 | 提交含 `except: return True` 的 mock PR | `fail-open-scan` job fail |
| 契约测试 | 三服务 `/healthz` 响应头 | `API-Version: 1.0.0` 一致 |
| 回归 | 三个服务全部既有测试 | 无新增 failure |

## 风险与回滚

- **IM gateway retry 引入延迟**：给 db=None 的场景加了 50ms retry，会增加单次鉴权耗时。缓解：retry 只在 `db is None` 时触发（其他分支直接 deny），平均影响极小
- **topic_admission mode=off 语义变化**：线上若有意将 mode 设为 off 以「关闭检查」，本次改为 deny-by-default 会破坏该用法。需在部署说明中明确：**mode=off 的含义从「关闭检查（放行）」改为「启用 fail-closed 默认拒绝」**；如需临时全放行，用环境变量 `BYPASS_TOPIC_ADMISSION=true`（需经 CODEOWNERS 审批，高频写入审计日志）
- **ontology_permission enforce=False**：历史上「未配置权限系统」的部署可能依赖此默认 allow 行为。修复后需此类部署手动配置 `ONTOLOGY_PERMISSION_ENFORCE=true` 并保持 deny-all 语义（或配置白名单）
- **回滚难度**：四处修复均为「deny 替代 allow」方向，回滚只需要还原代码 + 重新部署；无数据迁移风险
