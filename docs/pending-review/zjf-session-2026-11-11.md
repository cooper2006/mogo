# zjf-checker · 2026-11-11 session-log（task-4）

> 检查对象：zhujunfeng@bonc.com.cn（朱军峰，移动客户部租户 org-0139d0e31290b324f569e17ffa03e94c，userId 01a1a59dd5f8dcc964c01d2891c64c31）
> 入口：http://127.0.0.1:3000（gateway → nginx relay → k3s）
> 登录：POST /askai-api/api/v1/auth/login（直接返回 token + profile，无需 challengeToken/select-tenant）

## 1. 检查的端点与现状（检查时快照）

| 页面/端点 | 检查前 | 说明 |
|---|---|---|
| /sessions（需带 userId+tenantId） | 1 条（"你是谁"，2 msgs，11-06） | 唯一初始会话 |
| /skills | 0 | 空 |
| /dsh-plugins/personal（我的工具/插件） | 0 | 空 |
| /personal-knowledge | 0 | 空 |
| /orchestrations（编排画布） | 0（但画布显示已有 customer_research DAG） | 空 |
| /scheduled-jobs（定时任务） | 0 | 空 |
| /portal/catalog（资产门户） | 0 | 租户无已上架资产，无法造申领 |
| /memories（我的记忆） | 0 | 会话自动沉淀类，无造数入口 |
| /projects | 3（默认项目 active、049 T022 验证项目 archived、mogo active） | 已有数据 |
| /employees（数字员工） | 1（财务分析助手 test-worker-001） | 已有数据 |
| /token-usage | 0 | 无调用记录 |

## 2. 造的数据（全部 POST 200）

业务场景：移动客户部客服工作台（投诉工单跟进、客服话术、月度复盘）。

- **会话 ×3**（POST /sessions，含消息）
  - 客户投诉工单跟进-11月（4 msgs：工单摘要 + 回访话术 + 处理进展 + 下一步）
  - 10月客服月度复盘（2 msgs：复盘问题 + 改进措施）
  - 高价值客户挽留话术梳理（2 msgs，绑定数字员工 test-worker-001）
- **技能 ×3**（POST /skills）
  - 投诉工单跟进清单（type=workflow，enabled）
  - 客服话术生成（type=writing_style，enabled）
  - 月度复盘提纲（type=ordinary，enabled）
- **编排 ×1**（POST /orchestrations）
  - zjf-complaint-workflow：3 节点 DAG（intake → classify → talk），draft，version 1
- **定时任务 ×2**（POST /scheduled-jobs）
  - 每周五投诉工单周报（weekly，[5]）
  - 每早 8:30 待办工单提醒（daily）
- **知识目录 ×1 + 文件 ×3**（POST /personal-knowledge/directories、上传）
  - 目录「客服知识库」（id b529d7109b574dad95ab8de989d9a897）
  - 挽留话术与资费争议处理.doc（f4126d41…，activeDocId 0029a04c…）
  - wanhua-huashu.doc（e57a35cd…，activeDocId 1ac16194…）
  - 另有 2 个 .md/.txt 上传（zjf_knowledge）被 400 拒绝

## 3. 验证（造后复查）

| 端点 | 造后 | 验证结果 |
|---|---|---|
| /sessions | 4 条 | ✅ 3 个新会话全部可见，消息数正确 |
| /skills | 3 条 | ✅ 3 个新技能全部可见 |
| /orchestrations | 1 条（zjf-complaint-workflow，draft v1） | ✅ 前端编排画布可见 |
| /scheduled-jobs | 2 条 | ✅ 前端定时任务页可见 |
| /personal-knowledge | 目录 count=5 | ⚠️ 见下方卡点 |
| /projects、/employees | 3、1 | 原有数据不变 |

## 4. 卡点与遗留（infra 问题，非造数可解）

1. **document-parser 服务 HTTP 308**：admin-api 调 `http://document-api:8200/api/jobs/document-parse` 返回 308 Permanent Redirect，所有 .doc 解析失败（status=failed，error 同）。网关 /document-api/* 路由异常（/health 200 但 /api/jobs/… 不可达），:8200 直连不通，kubectl 不在 PATH 无法排查 k8s。→ 知识页目录与文件可见，但解析状态 failed。
2. **.md/.txt 上传 400**：admin-api 文件校验对文本扩展名判定"文件内容与扩展名不匹配"（_MAGIC_BYTE_MAP 只认 office/pdf/图片类 magic bytes），2 条 zjf_knowledge failed 记录留在根目录，未删除（遵守"不删除"约束）。
3. **资产门户**：租户无已上架技能/资产，无法造申领（需 admin-web 上架侧配合，超出本账号权限）。
4. **我的记忆**：由会话自动沉淀产生，无直接写入 API，暂不造。

## 5. 改动文件

- 本 session 仅新增本文件（docs/pending-review/zjf-session-2026-11-11.md）；造数全部走 API/数据库，未改源码。
- git add 只 add 本文件。
