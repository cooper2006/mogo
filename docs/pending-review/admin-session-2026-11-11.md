# admin 检查与造数 session-log（2026-11-11）

租户：移动客户部（org-0139d0e31290b324f569e17ffa03e94c），账号 admin。
方式：tabbit 不可用，全程 curl 调 admin-api（http://127.0.0.1:3000/admin-api/api/v1）。
token：重新登录获取（challengeToken → select-tenant），存 /tmp/admin_token_fresh.txt。

## 一、端点检查结果

| 端点 | 初始状态 |
|------|---------|
| dashboard/overview | 200；有 billing/health/metrics/assets；health=warning「工具未完成测试」（存量问题，非本轮）；24h 指标为 0（正常，当天无调用） |
| directory/users | 9 人 |
| directory/departments/tree | 根「移动客服部」+ 9 个省客服部，多数 0 人 |
| position-roles | 1 个（全能力管理员 full_access_admin） |
| employees（数字员工） | 1 个（财务分析助手 test-worker-001，存量测试数据） |
| skills | 6 个（zck-data-access、voice-label-tagging、preset-qa-answering、ontology-query、juejin-scenario-routing、customer-voice-mining） |
| tools | 5 个（mesc_data_access、ecs_db_*） |
| analytics/token-usage | 2 条（11-06 的调用记录） |
| system-audit/logs | 20 条 |
| knowledge/documents | 0 条（空） |
| dsh-plugins | 0 条（无公开安装来源，不造） |
| ontologies | 0 条（路由只有 sync/permissions/audit，无 create API，跳过） |

## 二、造数清单（全部走 admin-api POST，无源码改动）

### 1. 部门 5 个（POST /directory/departments，201）
- 投诉工单组 01a1c9f04439f5eb179026195092ee76（parent 10000 总部客服部）
- 质检组 01a1c9f05ee2c692a11cbea466e0cb82（parent 10000）
- 知识库运营组 01a1c9f05f06cda0bce8f05f2350f16c（parent 10000）
- 培训组 01a1c9f05f2c54910f49dedb4ef03479（parent 10000）
- 热线接听组 01a1c9f05f4b2f9190affb2f3b37f0e8（parent 12300 广东省客服部）

备注：造数过程中 shell 函数变量捕获失败导致重复创建了一批部门，已用 DELETE /directory/departments/{id} 清掉 5 个本轮误建的重复项（投诉工单组 01a1c9f00e9f...、质检组 01a1c9f00ee7...、知识库运营组 01a1c9f00f2b...、培训组 01a1c9f00f71...、热线接听组 01a1c9f00fb6...，均为本轮新建记录，非存量数据），部门树已复核无重复。

### 2. 员工 6 人（POST /directory/users，201）
均挂 full_access_admin 角色，source=local，初始密码 Mogo@2026!Dev：
- 张明 zhangming 13800001001 → 投诉工单组（id 01a1c9f1e241ce59...）
- 王芳 wangfang 13800001002 → 投诉工单组（id 01a1c9f1e28c14ca...）
- 刘伟 liuwei 13800001003 → 质检组（id 01a1c9f1e2d9dae4...）
- 陈雪 chenxue 13800001004 → 知识库运营组（id 01a1c9f1e32c4392...）
- 黄磊 huanglei 13800001005 → 培训组（id 01a1c9f1e37c02e1...）
- 周婷 zhouting 13800001006 → 热线接听组（id 01a1c9f1e3ce6982...）

### 3. 数字员工 3 个（POST /employees，201）
- 客服答疑助手 abea0bc82aa4433d9cc7d5b4af3b795d（memory_scope=department，基于知识库应答 5G/套餐/投诉场景）
- 投诉工单总结助手 63a73a6798fa44d29230c85618f454e8（memory_scope=project，工单摘要+风险标注）
- 月度运营复盘助手 b986faace0124fb5a5958b8faafada2d（memory_scope=department，KPI 汇总复盘）
说明：skillIds 引用现有 6 个 skill 时 422「包含不存在或未启用的企业 Skill」（skills 集合 enabled 字段校验不一致，存量数据问题，不擅改），故 skillAccessMode=all、skillIds 留空。

### 4. 知识文档 3 篇（POST /knowledge/documents multipart，201）
- kpi_sla.md 50d0c3d1e0ab...（客服 KPI/SLA 指标表：一线/工单组/质检组）
- faq_md_complaints.md 5135941e7b96...（投诉工单处理 FAQ）
- faq_md_5g.md e7dad9b7e777...（5G 套餐资费 FAQ）
踩坑：QF-416 魔数校验对 md 只取前 16 字节做 UTF-8 解码，中文标题在多字节边界截断会 400「文件内容与扩展名不匹配」；在文件头插入一行纯 ASCII 注释（<!-- doc: generated 2026-11-11 -->）即可通过。文件本体存 /tmp/，未落项目目录。
注意：kpi_sla.md 上传成功但 status=failed（解析管线问题，未深查）。

## 三、验证结果（造数后复查）
- knowledge/documents：total=3（3 篇新文档可见）
- employees：items=4（存量 1 + 新建 3）
- directory/users：total=15（9 + 6）
- departments/tree：15 个部门；总部客服部 users=8，投诉工单组 2、质检/知识库运营/培训各 1；广东省客服部 2（热线接听组 1）
- dashboard/overview：assets.users.total=15、departments=15；models 7 active；skills 6 enabled

## 四、未做/遗留
- ontologies 0 条：无 create API，无法造数
- dsh-plugins 0 条：需真实插件包（install/upload），不造假数据
- kpi_sla.md status=failed：知识解析管线问题，超出本轮范围
- dashboard health warning「工具未完成测试」：存量 tools 未走 /tools/{id}/test，非本轮引入
