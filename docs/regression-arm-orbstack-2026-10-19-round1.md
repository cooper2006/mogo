# OrbStack ARM 准生产环境回归测试报告（ADR-5 第一轮）

- **日期**：2026-10-19 10:33–11:35 CST
- **环境**：OrbStack，Docker Server 29.4.0 | aarch64/linux，镜像 tag `3f4e6b6`（HEAD `3f4e6b6`）
- **回归对象**：ADR-5「以 OrbStack 为准生产环境进行多轮回归」的第一轮基线采集、两个决策点闭环，以及 D1 缺陷根治与受控验证
- **本报告相对上轮（10-12）的区别**：
  - TLS 方向经用户拍板**保持关闭**（`MOGO_TLS=0`），故 443 为死映射端口，正确探针为 `http://127.0.0.1:3000`（3000→80）。
  - chat-api 运行版本由 `0.2.1` **对齐到 `0.2.3`**（rebuild 本地镜像，未走远端 registry）。
- **结论**：**基线可用；发现并根治 1 个真实韧性缺陷（D1：gateway 无 resolver，upstream 重启即击穿，已根治 + 受控验证）**；其余路由/鉴权/健康链路全绿。

---

## 一、结论摘要

| 维度 | 判定 |
| --- | --- |
| 全服务健康 | **通过** —— 11 个 mogo 容器 + 独立 `panweidb` 全部 `Up (healthy)` |
| 路由 / 鉴权冒烟（经网关） | **通过** —— /healthz、/admin/、/admin-api/、/askai-api/、/api/ 全部 200/401 正常 |
| chat-api 版本对齐 | **已完成** —— 运行自报 `0.2.3`（重建前 `0.2.1`，与 manifest/CHANGELOG 一致） |
| TLS 基线 | **关闭（用户决策）** —— 仅 80 监听，443 空闲端口 |
| 韧性缺陷 D1（gateway 无 resolver） | **已根治 + 受控验证** —— upstream 换 IP 后网关无需重启即自愈（见第三节） |

**总体**：环境已恢复并可作为 ADR-5 准生产回归靶场；D1 已在全部三个活动网关配置中根治，并经「强制换 IP + 不重启网关」受控验证通过。

---

## 二、环境基线

- 镜像 tag 全部 `3f4e6b6`（HEAD 短哈希）。`panweidb` 为独立容器（不在 mogo compose 项目内），image `panweidb:3.2.0`，由 OrbStack 转发到宿主 `5432`。
- 三崩溃服务（admin-api/chat-api/document-api）恢复链路：开工时因 `panweidb` 的 DB 进程未起（`gs_ctl` 未运行，`db: NOT ready`），而 `.env` 设 `MOGO_DATA_BACKEND=PanWeiDB` 使其启动必须连 PG，连不上 → `PoolTimeout` 无限重启。**账号/密码均正常**（`.env` 的 24 字符密码能连 `boncuser`；脚本 `panweidb_up.sh:42` 硬编码 `APP_PW='1qaz!QAZ'` 反而 `login denied`——DB 口令后被改过，与脚本默认分叉）。`bash scripts/pg/panweidb_up.sh` 拉起进程后 `docker compose restart admin-api chat-api document-api` 即恢复 `Up (healthy)`。
- **本轮部署变更（已执行，可逆，仅本地容器）**：
  1. `MOGO_VERSION=3f4e6b6 docker compose -f docker-compose.yml -f docker-compose.build.yml build chat-api` → 新镜像 `ghcr.io/himovo/chat-api:3f4e6b6`（约 32s，缓存命中；仅含 R8 遗留的两个版本号改动 `0.2.1→0.2.3`，无功能变更）。
  2. `MOGO_VERSION=3f4e6b6 docker compose up -d --no-deps --pull=never chat-api` 替换容器（第一次不带 `--pull=never` 因 registry 废弃链路 `denied` 失败，已用本地镜像重建）。
  3. `docker compose restart gateway` 两次（rebuild 前、rebuild 后各一次），使 nginx 重新解析 chat-api 新 IP。

---

## 三、韧性缺陷 D1：gateway 缺 `resolver`，upstream 重启即击穿（真实，已根治 + 受控验证）

### 3.1 现象
- 恢复阶段 `docker compose restart chat-api` 后，经网关访问 `/askai-api/health` 与 `/api/auth/me` **稳定 502**（重试多次均 502），但容器内直连 `chat-api:8000/health` 正常（200）。
- nginx 错误日志：`connect() failed (111: Connection refused) ... upstream: "http://192.168.97.4:8000/health"`。
- 而 gateway 内 `getent hosts chat-api` 此刻解析为 `192.168.97.5`。

### 3.2 根因
- `gateway` 的 `default.conf`（`deploy/docker/nginx.conf`）**无 `resolver` 指令**，所有 `proxy_pass http://<service>:<port>` 在 **nginx 启动瞬间**被解析成固定 IP 并缓存，此后**永不重解析**。
- `docker compose restart chat-api` 使 chat-api 获得新 IP（`.4`→`.5`），nginx 仍向旧 `.4` 转发 → 502，直到 `docker compose restart gateway` 让 nginx 重新解析才恢复。

### 3.3 影响面
- 任一被网关代理的 upstream（chat-api/admin-api/admin-web/dsh-runtime-host）**重启/重建都会让对应路由 502**，直到 gateway 也重启。这是真实的生产韧性缺陷：单实例重启会击穿网关而非自愈。

### 3.4 根治（用户决策：本轮即修）
- **代码改动**（用户决策 m00233：D1 立即根治；ADR-5 本轮补建）：
  - 在 `http` 上下文（`map` 块之后、`server` 之前）增加：
    ```
    resolver 127.0.0.11 valid=10s ipv6=off;   # Docker 内嵌 DNS
    resolver_timeout 5s;
    ```
  - 6 个反代 location 改为**变量式 upstream + `rewrite ... break` 保留原前缀剥离**行为：
    - `/admin/`    → `set $admin_web_up admin-web;` + `rewrite ^/admin/(.*)$ /$1 break;` + `proxy_pass http://$admin_web_up;`
    - `/admin-api/`→ `set $admin_api_up admin-api:8100;` + `rewrite ^/admin-api/(.*)$ /$1 break;` + `proxy_pass http://$admin_api_up;`
    - `/askai-api/`→ `set $chat_api_up chat-api:8000;` + `rewrite ^/askai-api/(.*)$ /$1 break;` + `proxy_pass http://$chat_api_up;`
    - `/api/`      → `set $chat_api_up chat-api:8000;` + `proxy_pass http://$chat_api_up;`（无 rewrite，保留原 URI）
    - `/dsh-web/`  → `set $dsh_up dsh-runtime-host:3080;` + `rewrite ^/dsh-web/(.*)$ /$1 break;` + `proxy_pass http://$dsh_up;`
    - `/`          → `set $user_web_up user-web;` + `proxy_pass http://$user_web_up;`
  - **覆盖全部三个活动网关配置**（同源缺陷）：`deploy/docker/nginx.conf`（当前 `.env` 指向）、`deploy/nginx/nginx.conf`（TLS 默认主线）、`deploy/docker/nginx-https.conf`（TLS 兼容入口，10-12 那轮用的就是它）。`deploy/docker/nginx-main.conf` 为空文件，未触碰。
- **加载方式**：`deploy/docker/nginx.conf` 是 bind mount，改完须 `docker compose up -d --force-recreate --no-deps --pull=never gateway` 重挂（注意：`restart gateway` 不重挂 bind mount，旧内容/失效挂载不会被修正）。`--force-recreate` 后 `nginx -t` 通过、`conf.d/default.conf` 含 resolver。
- **离线语法校验**：用本地 `nginx:1.31.5-alpine3.24-slim` 对三文件 `nginx -t`，均 `syntax is ok`（TLS 两文件在挂自签证书后 syntax ok；证书缺失报错与本次改动无关）。

### 3.5 受控验证（决定性证据）
- **实验设计**：让 chat-api **强制获得新 IP**，且**不重启 gateway**，立即探活。若旧代码（静态解析）则 502；修复后（per-request 重解析）应 200。
- **制造换 IP**：`docker rm -f mogo-chat-api-1` → 用 alpine 占位容器**钉死旧 IP**（`mogo_public=192.168.97.5`、`mogo_backend=192.168.107.9`）→ 再 `docker compose up -d --no-deps --pull=never chat-api` 重建，IPAM 无处复用，chat-api 拿到新 IP。
  - 实测：IP 由 `public 192.168.97.5 / backend 192.168.107.9` 变为 `public 192.168.97.10 / backend 192.168.107.11`。
- **额外强证据**：探针期间旧 IP `192.168.97.5` 正被占位容器钉死（alpine `sleep 600`，8000 无监听）。若网关缓存旧 IP，请求会打到占位容器 → `connection refused` → 502；实际返回 **200**，证明网关用的是**刚解析出的新 IP `192.168.97.10`**。这是「陈旧 IP 被占用 → 缓存必败、重解析必胜」的受控对照。
- **探针结果（gateway 全程未重启，CreatedAt 仍为 `2026-10-19 11:16:24`）**：
  - `/askai-api/health` → **200**（修复前此条件必 502）
  - `/api/auth/me` → **401**（到达 chat-api 并正确拒绝未认证）
  - `/healthz` → **200**
  - 网关错误日志 0 条 `connection refused` / `502 upstream`。
- **结论**：D1 根治有效，upstream 重启/重建换 IP 后网关无需重启即自愈。

---

## 四、路由 / 鉴权冒烟（经网关 `http://127.0.0.1:3000`）

| 路径 | 结果 | 说明 |
| --- | --- | --- |
| `/healthz` | 200 | 网关健康检查 |
| `/admin/` | 200 | admin-web 前端 |
| `/admin-api/api/setup/status` | 200 | admin-api |
| `/askai-api/health` | 200 | chat-api（自报 `version: 0.2.3`） |
| `/api/auth/me` | 401 | 到达 chat-api，未登录正常 |
| `/askai-api/api/models/available?tenant_id=default` | 401 | 到达 chat-api 并鉴权，正常 |
| `/dsh-web/` | 303 | 重定向（正常） |
| `https://localhost`（443） | 000 | TLS 关闭，443 死端口，预期 |

---

## 五、版本一致性核验

- `services/chat-api/app/main.py:45` 与 `services/chat-api/pyproject.toml` 版本号均为 `0.2.3`（R8 遗留未提交改动，仅两处版本号）。
- 重建前运行镜像自报 `0.2.1`（镜像 build 于 2026-10-17 20:46，早于上述改动）。
- 重建后运行镜像自报 `0.2.3`，已与 manifest/CHANGELOG 对齐。
- admin-api 在 8100 未暴露 `/health` 路径（探针返回空，非缺陷，路由 `/admin-api/` 经网关正常 200）。

---

## 六、遗留待办（Open）

- **TLS 方向**：用户已拍板本轮保持 `MOGO_TLS=0`；若后续要求 TLS 生效，需改 `.env` + 挂载证书 + 用 `nginx-https.conf`（已含 D1 根治），并按 10-12 报告那样复验就绪探针。
- **`.env` 密码与 `panweidb_up.sh` 默认分叉**：脚本硬编码 `APP_PW='1qaz!QAZ'` 已连不上（DB 口令后来被改），属配置卫生，不阻断，后续同步。
- **后续轮次**：三服务全量测试（容器内仅 admin-api 有 pytest；chat-api/document-api 需按 R8 方法或带测试依赖重建）、deploy/tests、CI 同款门禁、ARM 架构、故障转移、022 加固守卫。

## 七、本轮已闭环项（Done）

- **D1 根治**：三处活动网关配置均加 `resolver 127.0.0.11` + 变量式 `proxy_pass`；gateway `--force-recreate` 重挂；受控换 IP 验证通过（见第三节 3.4–3.5）。
- **ADR-5 文档落地**：补建 `Decisions/ADR-5-以OrbStack为生产环境进行回归.md`（status active）——前序会话误称已落库，实际文件系统无此文件，本轮按用户决策补建。
- **chat-api 版本对齐 0.2.1→0.2.3**：rebuild 本地镜像替换容器，经网关自报 `0.2.3`。
- **环境恢复**：panweidb DB 进程拉起 + 三崩溃服务 `Up (healthy)`。

Open objectives: 以 OrbStack 为准生产环境执行多轮回归（ADR-5，m00002）。
