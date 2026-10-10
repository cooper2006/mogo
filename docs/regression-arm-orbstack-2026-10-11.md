# OrbStack ARM 准生产环境回归测试报告

- **日期**：2026-10-11（测试窗口 00:00–00:10 CST；修复与复验至 00:45 CST）
- **环境**：OrbStack 2.2.3，Docker Server `linux/arm64`，镜像 tag `dd8ed63`
- **目标**：以 OrbStack 中的 arm64 栈作为 ARM 准生产环境，对当前工作区状态做全链路回归
- **结论**：**架构层面通过（ARM 无回归）**。回归共暴露 **7 项时间相关潜伏缺陷（R1）**与
  **4 项部署/数据缺陷（D1–D4）**，均与 ARM 无关；**其中 R1、D1、D2、D3 均已修复并复验**
  （D4 为本机 OrbStack 环境问题，非代码缺陷）。三服务全量回归 **2695 项测试 0 失败**。

---

## 一、回归范围与方法

| Phase | 内容 | 方法 |
| --- | --- | --- |
| A | 容器栈健康 + 网关路由 | `docker compose ps`、逐路由 HTTP 探针 |
| B | 三服务 pytest 全量 | 各服务 `.venv312`（Python 3.12.15）+ JUnit XML 权威计数 |
| C | ARM 架构专项 | 镜像 `Architecture`、容器 `uname -m`、Playwright、基础镜像归档 |
| D | 端到端 + 隔离 + 韧性 | 真实路由鉴权、Mongo 跨租户审计、粘性哈希、副本 k8s 式故障注入 |
| E | 部署配置审查 | LB 配置、`mogo` CLI 解析刷新逻辑 |

**基线纪律**：开工前后 `git status --porcelain` 一致，本轮**未产生任何源码改动**，纯只读验证。

---

## 二、Phase C：ARM 架构专项 —— 通过

这是本次"ARM 准生产"的核心命题，全部通过：

| 检查项 | 结果 |
| --- | --- |
| 7 个应用镜像架构 | 全部 `arm64/linux`（admin-api / admin-web / chat-api / document-parser / dsh-runtime-host / gateway / user-web） |
| 15 个运行容器 `uname -m` | 全部 `aarch64`，**无一个走 QEMU emulation** |
| chat-api 内 Playwright | `/ms-playwright` 含 `chromium-1194`、`chromium_headless_shell-1194`、`ffmpeg-1011`，`uname -m`=`aarch64` |
| 基础镜像归档 arm64 | `export_base_images.sh verify` → 4/4 `[ok] linux/arm64` |
| 基础镜像归档 amd64 | 4/4 `[ok] linux/amd64`（架构目录分离有效，未互相覆盖） |

**在途改动验证（Dockerfile）**：`services/chat-api/Dockerfile:54` 新增的 `ARG INSTALL_PLAYWRIGHT_AT_BUILD=false` 声明，使 `:103` 的 `RUN` 块能读取该变量，消除 `set -u` 下的 `parameter not set` 构建中止。**该修复在 ARM 上实证有效**——镜像内确实存在 chromium，证明构建分支真实执行。

---

## 三、Phase B：测试套件 —— 发现并修复 7 项时间相关潜伏缺陷（R1）

> R1 已修复并复验，详见 3.2 末的"修复与复验"。

### 3.1 权威计数

| 服务 | tests | failures | 说明 |
| --- | --- | --- | --- |
| chat-api | 2260 | 0 | 排除 2 项时间缺陷后 |
| admin-api | 433 | 0 | `TZ=UTC` 下 |
| document-parser | 22 | 0 | 全绿 |

### 3.2 缺陷 R1（P1）：UTC vs 本地日期分歧 → 每日 00:00–08:00 必现失败

**现象**：chat-api 2 项 + admin-api 5 项失败。

```
chat-api:  tests/services/test_skill_quality_report.py::{test_report_skill_call_accumulates_additively,
                                                          test_report_skill_call_is_tenant_and_day_partitioned}
admin-api: tests/test_quality_metrics.py::{test_sustained_low_quality_marks_shared_bit,
                                           test_evaluate_all_scores_every_key}
           tests/test_skill_monitoring.py::{test_monitor_day_granularity_series,
                                            test_monitor_hour_granularity_approximate,
                                            test_monitor_skill_key_filter}
```

**根因**：实现侧按 **UTC** 分桶，测试侧按 **本地日期** 断言：

| 侧 | 代码 | 时区 |
| --- | --- | --- |
| chat-api 实现 | `app/services/skill_quality_report.py:_today()` → `datetime.now(timezone.utc).date()` | UTC |
| admin-api 实现 | `skill_market/quality_metrics.py:74`、`skill_market/skill_monitoring.py:42,114,130` → `datetime.now(timezone.utc).date()` | UTC |
| 两侧测试 | `date.today().isoformat()` | 本地 CST (UTC+8) |

北京时间 00:00–08:00 期间，UTC 日期仍为前一日，本地日期已翻页 → 断言必然失败。

**证据链（决定性）**：

```
本地时区：chat-api 2 failed / 4 passed    admin-api 5 failed
TZ=UTC  ：chat-api 6 passed               admin-api tests=433 failures=0
```

失败信息与推断完全吻合：

```
test_monitor_day_granularity_series: assert 2 == 3
  len([{'time': '2026-10-09', ...}, {'time': '2026-10-10', ...}])   ← 缺 2026-10-11
test_report_skill_call_is_tenant_and_day_partitioned:
  assert ('t1', '2026-10-11') in {('t1','2020-01-01'),('t1','2026-10-10'),('t2','2026-10-10')}
```

**为何早先一次全绿**：首次运行于 23:5x（本地与 UTC 同为 10-10），跨过午夜后复跑即失败。**同一份代码两次结果不同**，正是典型的日期时间炸弹特征。

**影响**：CI 若在 00:00–08:00 CST 触发即红；与 ARM、与本次代码改动均无关。

**修复与复验（已完成）**：

遵从"改测试、勿改实现"（UTC 分桶是正确设计）。在 3 个测试文件中各引入 `_utc_today()`
助手（`datetime.now(timezone.utc).date()`，与实现的 `_today()` 同源），替换 7 处缺陷锚点：

| 文件 | 修复的锚点 |
| --- | --- |
| `test_quality_metrics.py` | `_seed_low_days()` + 4 处 `timedelta` 种子锚点 |
| `test_skill_monitoring.py` | `_seed_metrics()`、hour 粒度、`skill_key_filter`（原表现为 `assert 40 == 80`） |
| `test_skill_quality_report.py` | 3 处断言 |

**刻意未改**：`test_skill_monitoring.py` 中 FR-2 的 `_seed_audit_events` 与两处 `drilldown`
仍用 `date.today()` —— 它们把日期**作为参数显式传入**实现（`day=day`），不依赖隐式时钟锚点；
已实测两种时区下均通过（3/3），故按最小改动纪律保留。

**复验证据**：
- **双向时区**：本地 CST 与 `TZ=UTC` 下相关测试全部 failures=0（这是本缺陷的关键判据）。
- admin-api **433/0**、chat-api **2262/0**、document-parser **22/0**，合计 **2717 项 0 失败**。
- chat-api 修复前为 2260 项（2 项未跑完），修复后 2262 项全过 —— 印证修复真实生效。
- 生产代码零改动。

### 3.3 环境一致性提醒

三服务 venv 均为 `.venv312`（Python 3.12.15），故套件在本地与 CI 的 Python 版本一致，**不存在版本导致的差异**。此项已排除，可确信 R1 是唯一根因。

---

## 四、Phase D：端到端与韧性 —— 通过

| 验证项 | 结果 |
| --- | --- |
| 网关路由 | `/`、`/admin/`、`/healthz`、`/admin-api/api/setup/status`、`/askai-api/health`、`/askai-api/ready`、`/dsh/health` 均 200 |
| 鉴权强制 | `/admin-api/api/{platform/tenants,skills,tools}` 未认证一律 **401**，无端点泄漏 |
| 租户隔离 | `chat_messages` 18 条全属 BONC、0 条缺失 `tenant_id`；BOND 数据 0 条混入 |
| 隔离不变量 | `knowledge_documents` / `chunks` / `skills` / `end_users` 均严格单租户归属 |
| 粘性哈希 | 同一 `X-Isolation-Key` 连续 3 次全部命中 `192.168.107.7`(host-3)，key 正确解析 |
| 故障注入 | `stop dsh-runtime-host-1` 后服务持续 **200**，LB 正确绕行；`start` 后 3s 内自愈 |
| 降级上报 | 副本下线时 `/health` 如实只报存活实例，不虚假报全绿 |
| 重试兜底 | LB 日志实证 `proxy_next_upstream` 生效：`.9` 连接被拒后自动重试 `.7` 成功 |

---

## 五、Phase E：部署配置疑点 —— 均已修复

> 本节原记 3 项疑点（D1–D3）+ 1 项环境缺陷（D4）。除 D4 属本机环境问题外，D1–D3 均已修复并复验，
> 下附根因、修法与验证证据。详细改动见 `docs/WORK_LOG.md` 同日条目。

### 5.1 D1（P2，已修复）：`dsh-runtime-host-lb` 上游 DNS 陈旧

**根因**：`deploy/docker/dsh-runtime-lb.conf` 的 `upstream` 用服务名，nginx 仅启动时解析一次；
`mogo` 的 `refresh_gateway_resolution()` 只 restart **gateway**，未覆盖该 LB。

**实证**：LB 曾向 `192.168.107.9:8101` 请求被拒（`connect() failed 111`），该 IP 现属 **document-worker**
（副本重建后 IP 被复用）。

**修法选型（实测排除两个错误方案）**：
- 加 `resolver` 指令 —— ❌ 无效：nginx 对静态 `upstream { server <域名>; }` 不做运行时重解析，
  域名不可解析时直接 `[emerg] host not found` 退出。
- 变量式 `proxy_pass http://$host` —— ❌ 有严重副作用：**绕过 upstream 块，丢失
  `hash $dsh_sticky_key consistent` 会话粘性**，反而破坏 DSH 多副本核心不变量。
- ✅ **采用 `nginx -s reload`**：既重解析 upstream 又保留粘性，且**平滑不中断连接**
  （LB 承载 `proxy_read_timeout 3600s` 的 SSE 长连接，restart 会切断活跃会话）。

**修复**：`mogo` 新增 `refresh_dsh_lb_resolution()`，由 `refresh_gateway_resolution()` 调用；
best-effort 容错（失败仅告警不中断部署）；`i18n.sh` 补中英文案；LB 配置补注释防止被"优化"回变量式。

**验证**：构造别名从 ta 漂移到 tb 的场景 —— reload **前**返回 `OLD`（陈旧 IP），reload **后**
返回 `NEW`（已修复），直接证明机制有效。端到端 `./mogo up` 跑通，**gateway 走 restart**
（StartedAt 刷新）而 **LB `RestartCount=0` 且 StartedAt 不变**，证明是零重启平滑重载；
reload 后同一 `X-Isolation-Key` 连续多次稳定命中同一副本，粘性完好。

### 5.2 D2（P3，已修复）：第 4 个 DSH 副本空转（部署拓扑冲突）

**根因**：`dsh-runtime-host` 既是 YAML 锚点 `&dsh-runtime-host`（供 3 副本 `<<:` 继承），
又是**独立服务**；整个 compose 文件**无任何 `profiles`**，导致单副本拓扑与多副本池**同时无条件启用**。

**实证**：LB upstream 只列 `-1/-2/-3`，其 IP（`.3`）不在其中；chat-api 的 `DSH_RUNTIME_HOST_URL`
指向 **LB** 且 `DSH_RUNTIME_HOSTS_URL` 为空 → 该副本零流量，却占 **76.53 MiB** + 独立数据卷。
设计文档明确写「`dsh-runtime-host` **加** 2 个副本 + sticky LB」，即池本应**取代**单副本 —— 实现与意图不符。

**修法（含一次实测踩坑）**：先把 `profiles` 放进锚点 → **YAML 合并键把它复制给了全部副本**，
整个池被一起禁用（Compose 报 "depends on undefined service"）。修正为把共享设置提取到顶层扩展字段
`x-dsh-runtime-host-template`（沿用仓库既有的 `x-python-healthcheck` 惯例），`profiles` 只置于单副本服务自身。
同时把 `chat-api` 的 `depends_on` 由 `dsh-runtime-host` 改为实际调用的 `dsh-runtime-host-lb`。

**验证**：三种配置（默认 / `docker-compose.build.yml` 变体 / `--profile single-host`）`config` 均通过；
默认栈恰为 3 副本 + LB；`./mogo up` 跑通；移除遗留空转容器后全栈 healthy、路由全 200；
数据卷保留（`docker compose rm` 未加 `-v`）。

> 说明：Compose profile 是**叠加**语义（无 profile 的服务总会启动），故 `single-host` 是"额外增加"
> 而非"替换"；已在配置注释中如实说明并给出真正单副本运行的完整命令，未将其伪装成开关。

### 5.3 D3（P3，已修复）：`setup-test-*` 孤儿数据（资源泄漏）

**根因（两处叠加漏洞）**：
1. `setup_model.py` 的 `finally: if instance_id:` —— `create_instance` 抛异常时 `instance_id` 仍为 `""`，
   清理**整段跳过**；
2. `delete_instance` 只按 `_id` 删 `admin_model_instances` **一行**，不碰 `organizations` /
   配额表 / 用量日志 —— 而探针会让这些集合产生该租户的行。

**额外发现（更深一层）**：`setup_cleanup.py` 的租户 ID 正则 `^[a-z0-9]+-[0-9a-f]{24}$` 只允许
**单段 slug**，因此**既拒绝** `setup-test-*` 探针租户，**也拒绝合法租户** ——
`tenant_provisioning._slug()` 会把非字母数字替换成 `-`，org 名含空格时生成 `my-test-org-<hex>`，
属长期存在的误判。已放宽为 `^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{24}$`，并逐例实测仍拒绝
`default` / `__platform__` / 前导连字符 / 下划线（安全性未削弱）。

同时补入 `token_usage_logs` 到 `SETUP_SCOPED_COLLECTIONS`（`tenant_purge.py:112` 早已视其为租户级，
此处遗漏正是 3 条日志残留的原因），并让 `finally` 无论 `instance_id` 是否为空都执行全量清扫。

**存量清理**：新增 `scripts/cleanup_setup_test_tenants.sh`（幂等、**默认 dry-run**、严格锚定
`^setup-test-[0-9a-f]{24}$`）。

**验证**：dry-run 正确报 9 行 → `--apply` 后孤儿归零（organizations / org_quota_policies /
user_quota_policies / token_usage_logs 全为 0），而真实租户数据**逐项不变**
（organizations 2、chat_messages 18、skills 1、knowledge_documents 5、tenants 2），零误伤。

### 5.4 D4（环境问题，非代码缺陷）：virtiofs 挂载在长时运行容器中失效

排查 D1 时发现运行 29h 的 LB 容器内 `/etc/nginx/nginx.conf` **不可见**（`mount` 表显示 virtiofs
已挂载，但 `cat` / `nginx -t` 报 No such file），导致 `nginx -s reload` **静默失败**。

**对照实验排除配置错误**：用**同样挂载方式**启新容器 → 文件可见（5219B）且 `nginx -t` 通过；
对比 gateway 挂载到 `conf.d/default.conf` 则一直正常。重建 LB 后恢复正常。
**结论**：OrbStack virtiofs 挂载在长时运行容器中失效，属**本机环境问题**。

这也正是 D1 的新逻辑设计为 best-effort + 告警的原因 —— 该告警可让运维者发现此类静默失败。

---

## 六、遗留风险与未覆盖面

- **LLM 依赖未验证**：本次为离线环境，未调用真实 LLM 网关，对话推理链路未做端到端验证（需 API key）。
- **性能/韧性基准未复跑**：`tests/benchmarks/` 三项基准本轮未执行（属专项基准，非回归范畴）。
- **未验证容器重建可复现性**：回归阶段为遵守"不产生改动"约束未执行 `./mogo build` 全量重建；
  修复阶段亦未重建（D1/D2 的验证以配置校验 + 真实重载/重排 + 端到端 `./mogo up` 完成）。
- **BOND 为空租户**：跨租户"数据不可见"验证受限于 BOND 无数据；已用"BONC 数据中 0 条混入 BOND"作为不变量替代验证。
- **D2 的 `single-host` 拓扑未实跑**：仅做配置校验（`config --quiet`），未实际以该 profile 启动全栈；
  其命令已在配置注释中给出，但未经端到端演练。
- **D4 属环境问题，代码侧仅缓解**：`nginx -s reload` 在 virtiofs 挂载失效时会静默失败，现仅通过
  best-effort 告警暴露；根因在 OrbStack 侧，未（也无法）在代码内彻底规避。

---

## 七、判定

| 维度 | 判定 |
| --- | --- |
| ARM 架构正确性 | **通过**——全栈原生 arm64，无 emulation，Playwright 可用 |
| 部署栈可用性 | **通过**——14 容器健康（DSH 恰为 3 副本 + LB），路由/鉴权/隔离/韧性全部达标 |
| 应用层测试 | **通过**——2695 项 0 失败（chat-api 2262 / admin-api 433），双向时区均通过 |
| R1 跨午夜时间炸弹（P1） | **已修复并复验**——改测试锚点为 UTC，生产代码零改动 |
| D1 LB 上游 DNS 陈旧（P2） | **已修复并复验**——`nginx -s reload` 平滑重解析，保留粘性 |
| D2 空转 DSH 副本（P3） | **已修复并复验**——单副本拓扑 profile 化，默认栈回归 3 副本 + LB |
| D3 `setup-test-*` 孤儿数据（P3） | **已修复并复验**——堵住两处泄漏 + 清理存量 9 行，真实数据零误伤 |
| D4 virtiofs 挂载失效 | **环境问题，非代码缺陷**——对照实验确认，重建容器即恢复 |

**总体判定**：OrbStack ARM 环境**可作为准生产使用**。本次回归**未发现 ARM 特有缺陷**，也未发现
在途改动引入的回归；所暴露的 7 项测试缺陷（R1）与 3 项部署/数据缺陷（D1–D3）**已全部修复并复验**，
CI 同款检查（`check_compose_image_modes`、断言变异 9/9 捕获、三种 compose 配置校验）全部通过。

**遗留（非阻断）**：D4 属本机 OrbStack virtiofs 环境问题，代码侧已通过 best-effort 告警使其可见；
真实 LLM 网关与 `tests/benchmarks/` 专项基准不在本次回归范围（见第六节）。
