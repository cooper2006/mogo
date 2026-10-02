# Quickstart: 平台化多租户（020）

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [contracts/tenants.md](./contracts/tenants.md)

本文件说明如何**启用并验证**平台化多租户。

---

## 1. 前置

- MongoDB 可用（引导流程只要求这一项）
- admin-api 服务已启动
- 其余服务（Redis / 向量库 / 文档处理 / 对话服务）不可用时**不影响**引导与创建租户，仅在健康页显示为告警

---

## 2. 全新部署：创建平台管理员

1. 启动后访问系统，自动进入引导流程
2. 步骤 1 查看服务健康；MongoDB 必绿，其余服务异常可继续
3. 步骤 2 填写平台管理员账号（例如 `platform`）
4. 完成后登录，进入平台控制台 —— 此时**租户列表为空**

也可在无界面场景下通过环境配置预置：

```bash
export ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD='<strong-password>'
```

启动时自动 ensure，幂等。

---

## 3. 创建租户

平台控制台 → 新建租户，**只填三项**：

```
企业名称      示例科技有限公司
管理员账号    admin
管理员密码    **********
```

其余（初始员工、大模型、联网搜索、配额）全部折叠可留空。提交即创建成功，返回租户标识。

在代码中调用同一入口：

```python
from app.services.tenant_provisioning import provision_tenant

result = await provision_tenant(
    org_name="示例科技有限公司",
    admin_username="admin",
    admin_password="...",
    created_by="platform-admin",
)
print(result.main_id)
```

不传 `model` / `external_search` / `quota` / `employee` 时，对应配置全部跳过，配额默认为不限额。

---

## 4. 登录与切换租户

```bash
# 指定租户
curl -X POST /api/auth/login \
  -d '{"username":"admin","password":"...","mainId":"acme-9f3c..."}'

# 不指定且账号属于多个租户 → 返回 candidates + challengeToken
# 再调 POST /api/auth/login/select-tenant 选择进入
```

---

## 5. 生命周期操作

```bash
# 列表（仅生命周期字段，不含业务指标）
GET  /api/platform/tenants?status=active&keyword=示例

# 归档（账号禁止登录，不计入授权数）
DELETE /api/platform/tenants/{main_id}  -d '{"reason":"合同终止"}'

# 恢复
POST /api/platform/tenants/{main_id}/restore

# 彻底清理（必须先归档；需输入企业名确认）
POST /api/platform/tenants/{main_id}/purge -d '{"confirmName":"示例科技有限公司"}'
GET  /api/platform/tenants/{main_id}/purge-status

# 重置租户管理员密码（不强制首次改密）
POST /api/platform/tenants/{main_id}/admin/reset-password -d '{"newPassword":"..."}'
```

---

## 6. 存量部署升级（必读）

> 未执行本节，升级后将**无法进入平台控制台**。

1. 升级前配置平台管理员凭据：

   ```bash
   export ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD='<strong-password>'
   ```

2. 启动服务。`bootstrap_platform_admin()` 自动补建平台管理员；`tenants` 集合按既有账号幂等回填，既有企业数据零丢失。
3. 验证：租户列表中出现既有企业；既有租户管理员可正常登录。

若未配置凭据，系统状态会返回 `platformAdminMissing: true` 作为告警。

---

## 7. 验证清单

- [ ] 仅填 3 个字段即可创建租户，且向量库/文档处理不可用时仍能创建
- [ ] 新租户成员可正常使用，不被额度拦截
- [ ] 平台改成员上限后**实际生效**：设上限 N（已有 ≥N 名成员）时新建成员被 403 拦下，且仪表盘展示的上限同步为 N
- [ ] 租户 A 无法读取租户 B 的任何数据
- [ ] 账号属于两个租户时，登录出现选择步骤
- [ ] 归档后该租户账号登录被拒；恢复后数据完整
- [ ] 未归档租户请求彻底清理被拒（409）
- [ ] 清理完成后数据库记录 / 向量 / 磁盘文件残留均为 0，仅剩墓碑

  > **口径**：下列为**有意豁免**，不计入「残留」——
  > ① `system_audit_logs`（按 `main_id` 存，但记的是平台管理员对租户的操作，是 SC-007 要保留的溯源，删它等于销毁证据）；
  > ② 租户注册表 `tenants` 本身（转为 `status=purged` 墓碑，不删行）；
  > ③ OSS / 对象存储里的知识库对象（bucket 自有生命周期策略，清理只覆盖本地磁盘）；
  > ④ 无租户键且无业务价值的瞬时集合（`end_user_login_challenges` 5 分钟 TTL、`presence_heartbeats`、`session_presence_state`）。
  > `session_shares` **不在**豁免内：它没有租户键，但经 `chat_sessions` 反查级联删除（否则租户的分享 token 永久残留且无法归属撤销）。
- [ ] 全部生命周期操作均有审计记录
- [ ] 既有部署升级后既有企业存在且数据完整
