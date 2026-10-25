# TLS Certificates

Place your certificate pair here to enable HTTPS for the MOGO gateway.

## Files required

| File | Mode | Description |
|------|------|-------------|
| `fullchain.pem` | `0644` | Full certificate chain (cert + intermediates) |
| `privkey.pem` | `0644` | Private key |

**`privkey.pem` 必须是 `0644`。** 网关自 022 FR-26 起以非 root 的 `appuser`
(UID 10001) 运行，而证书是 bind mount 进容器的：Linux 上 bind mount 保留宿主
uid，0600 的私钥归宿主用户所有 → 容器内 uid 10001 读不到，nginx 启动即失败
并进入 crash-loop：

```
nginx: [emerg] cannot load certificate key "/etc/nginx/certs/privkey.pem" (13: Permission denied)
```

> macOS / OrbStack 的 bind mount 会把文件属主映射成容器运行用户，所以 0600
> 在本地也能跑 —— 不要因为本机跑得通就认为权限没问题，生产 Linux 会挂。

`openssl req -newkey` 生成的私钥默认就是 0600，`cp` 也会保留源模式，所以
**每次放证书后都要显式 chmod**。`deploy/tls/setup-certs.sh` 会自动归一化并自检。

要求更严格（私钥不 world-readable）时，用 root 把属主改成容器 uid 并保留 0600：

```bash
sudo chown 10001:10001 deploy/tls/privkey.pem && chmod 0600 deploy/tls/privkey.pem
```

## Usage

### 1. 放证书

放到本目录（或 `MOGO_TLS_CERTS_DIR` 指向的目录）：

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName = DNS:localhost,IP:127.0.0.1"
chmod 0644 privkey.pem fullchain.pem    # 必需，见上
```

也可以直接用项目根目录的自签名证书（会一并做权限归一化与自检）：

```bash
bash deploy/tls/setup-certs.sh
```

### 2. 把运行中的网关切到 TLS

**先持久化开关** —— 在仓库根的 `.env` 里加一行（compose 会读 `.env`）：

```
MOGO_NGINX_CONF=./deploy/nginx/nginx.conf
```

写进 `.env` 而不是每次命令行传，是为了让后续 `./mogo up` / `docker compose up`
都保持 TLS，不会在下次部署时悄悄退回 HTTP。

**再让网关生效** —— TLS 配置是**挂载**进容器的，不是烤进镜像的，所以不需要重新构建镜像，
只要让 gateway 容器按新的挂载重建：

```bash
# 推荐：只重建 gateway 容器，复用当前运行的镜像 tag（源码栈与仓库栈都适用）
export MOGO_GATEWAY_IMAGE="$(docker inspect mogo-gateway-1 --format '{{.Config.Image}}')"
docker compose -f docker-compose.yml up -d --no-deps gateway
```

也可以走项目标准命令，但它会把 6 个应用镜像全部重新构建一遍（慢）：

```bash
./mogo up --build gateway
```

> ⚠️ **不要**用裸 `docker compose up -d gateway`。`docker-compose.yml` 里 gateway 的
> image 是 `${MOGO_GATEWAY_IMAGE:-…ghcr.io/mogoai/gateway:${MOGO_VERSION:-latest}}`，
> 缺了镜像名时会解析成 `ghcr.io/mogoai/gateway:latest`，于是去拉远端镜像 ——
> 要么失败，要么把你本地构建的镜像换掉。`./mogo` 会导出正确的 bare 名。
>
> ⚠️ `--build` 不受服务名过滤：`./mogo up --build gateway` 会把全部 6 个应用镜像重建一遍，
> 而且不带 `--no-deps` 时会连带 recreate gateway 的依赖链
> （chat-api / admin-api / user-web / admin-web / document-api）。
> 只想动 gateway 就用上面的 `--no-deps` 方式。

### 3. 验证

```bash
curl -k https://localhost/healthz                      # 200
curl -k https://localhost/admin-api/api/setup/status   # {"…","ready":true,…}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/admin/setup   # 301
curl -s http://localhost:3000/healthz                  # 200（探针豁免，不跳转）
openssl s_client -connect localhost:443 -servername localhost </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -dates
```

### 回退到 HTTP

注释掉 `.env` 里的 `MOGO_NGINX_CONF` 那一行，再执行 `./mogo up --build gateway`。

## 切换后的行为与已知坑

| 现象 | 说明 |
|------|------|
| HTTP（宿主 `MOGO_PORT`，默认 3000）非 `/healthz` 请求全部 301 | 规则是 `return 301 https://$host$request_uri`；nginx 的 `$host` **不含端口**，所以 `http://localhost:3000/x` 会跳到 `https://localhost/x`（即 443），这是期望行为 |
| `/healthz` 不跳转，HTTP 200 | 刻意豁免，供负载均衡与容器健康检查使用 |
| 宿主 443 被别的进程占用 | 实测本机 IPv4 443 被第三方代理（Steam++ / Watt Toolkit）占用，OrbStack 只拿到 IPv6，于是 `https://127.0.0.1/` 打到别人身上（404），而 `https://localhost/`、`https://[::1]/` 正常。**释放 443 或统一用 `https://localhost/`** |
| 自定义 `MOGO_HTTPS_PORT`（非 443） | 跳转目标仍固定指向 443：配置是静态文件，拿不到宿主端口。需要同时改 `deploy/nginx/nginx.conf` 里的 `return 301` 行 |
| `./mogo up` 报 "Services did not become ready in time" | 就绪探针已适配 TLS：会跟随 301、跳过自签名校验，并在宿主端口被占用时回退到容器内直连 admin-api |

## Custom certificate directory

Set `MOGO_TLS_CERTS_DIR` in your `.env` to point to an alternate location:

```
MOGO_TLS_CERTS_DIR=/etc/letsencrypt/live/example.com
```

注意：Let's Encrypt 的 `live/` 目录里是符号链接，指向 `archive/`（root `0700`），
容器内 uid 10001 穿不过去。请把证书复制到本目录再 `chmod 0644`，或用 root 把
文件 `chown 10001:10001`。

## Troubleshooting

| 现象 | 原因 / 修复 |
|------|-------------|
| `nginx: [emerg] cannot load certificate key ... (13: Permission denied)` | 私钥对容器内 uid 10001 不可读 → `chmod 0644 privkey.pem`，或 `sudo chown 10001:10001 privkey.pem` |
| `nginx: [emerg] unknown "connection_upgrade" variable` | TLS 配置缺少 `map $http_upgrade $connection_upgrade` 块（`$connection_upgrade` 必须先定义再使用） |
| 网关反复 `Restarting` | `docker logs mogo-gateway-1` 看 nginx emerg 行，多为上面两条 |
| 浏览器打开 `https://127.0.0.1/` 不是 MOGO 页面 | 宿主 IPv4 443 被别的进程占用（见上表），改用 `https://localhost/` |
| 证书是自签名的，浏览器提示不安全 | 预期；或把 `deploy/tls/fullchain.pem` 导入系统信任库 |

回归守卫见 `deploy/tests/test_tls_gateway_config.py`。

## Expiry alerting & manual replacement（到期告警与手工更换，024 T094 / FR-046/FR-048）

### 到期告警

所有证书 MUST 登记在 `deploy/certs/inventory.yml`（域名、责任人、用途、到期时间、续期方式、拨测状态），
由 `deploy/cli/cert-check.sh`（经 `./mogo cert check`）做三件事：

1. **到期检查**：读取 `notAfter`，剩余 ≤ 30 天告警（WARN），≤ 7 天升级 CRIT；
2. **证书链校验**：`openssl s_client -verify_return_error`，验证码非 0 判 FAIL；
3. **外部拨测**（不依赖本机 `/etc/hosts`）：`dig @1.1.1.1 <domain> +tcp +short A` 解析真实外部 IP，
   再对该 IP 建立 TLS 连接校验，结论回写 `inventory.yml` 的 `probeStatus` / `probeCheckedAt`。

每日由 `.github/workflows/nightly-drift.yml` 的证书检查步骤自动跑一次，失败即告警。

> 证书本身不会自动续期——`cert-check.sh` 只负责「发现要到期」；**更换必须由人执行**。

### 手工更换流程

适用于客户自有证书 / 非 ACME 证书（`renewMethod: manual`）。任何证书都先做权限归一化
（见上文「Files required」），否则容器内 uid 10001 读不到私钥会 crash-loop。

```bash
# 1. 备份当前证书（避免换到一半出问题无法回退）
cp -a deploy/tls deploy/tls.bak.$(date +%Y%m%d%H%M%S)

# 2. 放入新证书对（来源：CA 签发文件或 certbot 等）
install -m 0644 new-fullchain.pem deploy/tls/fullchain.pem
install -m 0644 new-privkey.pem   deploy/tls/privkey.pem
chmod 0644 deploy/tls/fullchain.pem deploy/tls/privkey.pem   # 必需！

# 3. 校验新证书：私钥与证书匹配 + 不早于今日 + 有效期内
openssl pkey  -in deploy/tls/privkey.pem   -pubout > /tmp/mogo-pub.pem
openssl x509  -in deploy/tls/fullchain.pem -pubkey -noout  > /tmp/mogo-cert.pub
diff /tmp/mogo-pub.pem /tmp/mogo-cert.pub || echo "⚠️ 私钥与证书不匹配，请勿上线"
openssl x509 -in deploy/tls/fullchain.pem -noout -dates

# 4. 重建 gateway 容器让新证书挂载生效（不要裸 docker compose up gateway）
export MOGO_GATEWAY_IMAGE="$(docker inspect mogo-gateway-1 --format '{{.Config.Image}}')"
docker compose -f docker-compose.yml up -d --no-deps gateway

# 5. 验证
curl -k https://localhost/healthz                       # 200
openssl s_client -connect localhost:443 -servername localhost </dev/null 2>/dev/null \
  | openssl x509 -noout -dates -subject                 # notAfter 已是新证书
./mogo cert check --write-probe-status                   # 全部 PASS 且回写 probeStatus

# 6. 更新清单到期时间与续期方式
#    手工编辑 deploy/certs/inventory.yml 对应条目的 expiry / renewMethod，
#    然后 `./mogo cert check --write-probe-status` 重跑。

# 7. 清理备份（保留最近 N 份；确认新证书稳定运行 ≥ 24h 后再删）
```

### ACME / Certbot（可选）

内置 `deploy/docker/certbot` 容器（`profiles: ["acme"]`），适合有公网域名 + HTTP-01 或 DNS-01 授权的场景。
用法见 `deploy/docker/certbot/README.md`。**没有公网域名 / 没有 CA 授权时不要用它**，走上面的手工更换流程。

### 常见坑

| 现象 | 原因 / 修复 |
|------|-------------|
| 换证书后网关 crash-loop | 私钥模式仍是 0600 → `chmod 0644`，或 `sudo chown 10001:10001`（见上文） |
| `openssl s_client` 报 `verify error:num=19:self-signed certificate` | 自签名证书预期；正式证书应改为可信 CA 签发 |
| `./mogo cert check` 全部 FAIL | `dig @1.1.1.1` 解析不到 A 记录（无外网 DNS）→ 加 `--resolver none` 改走本机解析 |
| 到期前 7 天还没换 | 走升级流程：`deploy/runbook/alert-escalation.md`（T099） |
