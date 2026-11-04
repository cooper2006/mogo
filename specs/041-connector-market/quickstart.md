# Quickstart: 连接器市场 (041)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 连接器市场（041）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把租户级 HTTP/MCP 工具连接升级为连接器市场形态：仓库内种子模板目录→admin-web「从模板创建」向导（选模板→填参数→测试连接→上架）→落既有工具存储与注入路径→自动注册为 018 能力资产。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 提供连接器模板目录（仓库内种子 YAML，每模板一文件、带 `version`），每模板 MUST 含：标识/名称/类别/版本/描述/认证类型/参数 schema/示例参数/测试建议。
- FR-002：系统 MUST 提供市场列表与详情 API（模板元信息），支持按类别筛选与关键词搜索；MUST NOT 在响应中泄露种子中的占位凭证值。
- FR-003：系统 MUST 提供"从模板创建"API：按模板 schema 校验参数 → 映射为既有工具 payload → 经既有创建路径落库（同一存储与结构）。
- FR-004：模板创建的连接器 MUST 与手工创建的**行为一致**：同一存储、同一 test 链路（`tools.py` `/{tool_id}/test`）、同一注入路径（`external_tools.py:947-977` 服务端注入）。
- FR-005：创建向导 MUST 提供「测试连接」步骤并复用既有 test 链路；失败 MUST 返回可读错误，不静默。

关键验收点（Success Criteria）：
- SC-001: 从模板到可用连接器全链路（创建 → 测试 → 挂载 Agent → 调用成功）E2E 通过。
- SC-002: 模板创建的连接器与手工创建行为一致——契约测试断言同一存储结构与同一注入路径，0 分叉。
- SC-003: 034 落地后 DB 无明文凭证；Agent 侧仍只拿服务端注入（现有行为 0 回退）。
- SC-004: 存量连接 0 迁移即出现在「已安装」视图且可正常调用。

## 3. 如何启用

无单独开关；仓库内种子模板目录随服务加载；从模板创建走既有工具存储/注入路径（与手工创建同构），自动注册为 018 `type=connector` 资产。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_connector_market.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
