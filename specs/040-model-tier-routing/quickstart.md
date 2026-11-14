# Quickstart: 模型档位路由 (040)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 模型档位路由（040）。

---

## 1. 前置

- 相关服务已部署：chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

在 007 静态优先级链之后新增按任务复杂度选档路由：规则法评估器把请求落入 light/mid/high 三档，经 `model_routing.yaml` 的 `tiers` 映射到 031 已配置模型；映射缺失/异常安全回退默认档并告警。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 提供任务复杂度评估**纯函数模块**（输入为调用上下文特征，输出为三档之一），无 IO、可独立单测。
- FR-002：首期评估特征 MUST 至少覆盖：请求长度（字符数）、可用工具数、是否多轮、阶段/意图、显式复杂度声明（`output_spec.complexity`）；历史档位表现 MUST NOT 作为首期输入（留二期）。
- FR-003：评估算法 MUST 为规则法（阈值/加权评分），MUST NOT 调用 LLM 自评复杂度（控制不确定性与成本）。
- FR-004：档位体系 MUST 为三档：`light`（轻量）/ `mid`（主力）/ `high`（旗舰），命名 MUST 与 007 降级链档位词对齐。
- FR-005：档位→模型映射 MUST 由 `model_routing.yaml` 的 `tiers` 段声明，取值 MUST 引用 031 已配置模型；MUST 支持按租户覆盖（`tenants.<tenant_id>.tiers`）。

关键验收点（Success Criteria）：
- SC-001: 评估函数边界单测全覆盖（空/短/长/多工具/多轮/显式声明/异常），档位判定与规则文档一致。
- SC-002: 同一请求改换特征可落入不同档位（短问答 → light、编码多轮 → high），档位分布符合预期。
- SC-003: 档位映射缺失/评估异常时 100% 安全回退且告警可查，0 静默失败。
- SC-004: 007 既有韧性测试套件（`tests/llm/test_resilience.py`、`test_resilience_metering.py`、`test_resilience_wiring.py`）全绿，降级链行为 0 回退。

## 3. 如何启用

由 `model_routing.yaml` 的 `tiers` 段驱动；`enabled:false` 时回退 `settings.OPENAI_MODEL`（既有行为）；档位→模型映射缺失或评估异常时安全回退默认档 `mid` 并告警，绝不静默失败。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/llm/test_model_tier_routing.py services/chat-api/tests/llm/test_resilience.py services/chat-api/tests/llm/test_resilience_metering.py services/chat-api/tests/llm/test_resilience_wiring.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
