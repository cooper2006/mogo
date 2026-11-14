# Certbot 容器（024 T093 / FR-046/FR-048）

可选组件：为有公网域名 + ACME 授权的场景自动申请 / 续期 Let's Encrypt 证书。

> **没有公网域名 / 没有 CA 授权时不要启用本组件**。请走
> `deploy/tls/README.md` 的「到期告警与手工更换」（T094），手工更换同样满足
> 到期告警要求。

## 前置条件

- 域名已解析到本机公网 IP，且 80/443 可从公网访问（HTTP-01），或配置 DNS 插件；
- `.env` 已设置 `MOGO_NGINX_CONF=./deploy/nginx/nginx.conf`（网关走 TLS）；
- 本机可访问镜像站 `docker.m.daocloud.io`（避免 Docker Hub 直连 Bad Gateway）。

## 使用

在 `docker-compose.yml` 中启用 `certbot` 服务（`profiles: ["acme"]`），并设置环境变量：

```bash
# 方式一：HTTP-01（需 80/443 公网可达）
CERTBOT_DOMAINS=mogo.example.com,api.mogo.example.com CERTBOT_EMAIL=ops@example.com \
  docker compose --profile acme up certbot

# 方式二：DNS-01（推荐，不依赖 80/443）
CERTBOT_DOMAINS=mogo.example.com CERTBOT_EMAIL=ops@example.com \
  CERTBOT_EXTRA="--dns-cloudflare --dns-cloudflare-credentials /run/secrets/cloudflare_creds" \
  docker compose --profile acme up certbot
```

入口脚本 `docker-entrypoint.sh` 会：
1. 首次申请（`certonly`），或已存在时 `renew`；
2. 把 `live/<domain>/{fullchain,privkey}.pem` 拷到 `/etc/nginx/certs/`，并 `chmod 0644`；
3. 尝试 `nginx -s reload` 让网关立即生效。

## 定时续期

由宿主 cron 定时拉起容器（推荐每天 03:00），或由 CI 的
`.github/workflows/nightly-drift.yml` 的证书检查步骤触发检查：

```cron
0 3 * * * cd /path/to/mogo && docker compose --profile acme run --rm certbot >/var/log/mogo-certbot.log 2>&1
```

证书到期仍由 `deploy/cli/cert-check.sh`（`./mogo cert check`）独立把关，不依赖本容器。

## 验证

```bash
./mogo cert check --write-probe-status    # 全部 PASS 且回写 probeStatus
curl -k https://localhost/healthz          # 200
```

## 常见坑

| 现象 | 原因 / 修复 |
|------|-------------|
| 拉取 `certbot/certbot` 失败 Bad Gateway | Docker Hub 直连失败，使用镜像站 `docker.m.daocloud.io/certbot/certbot` |
| `certonly` 报 80/443 被占用 | 网关 / 宿主机已占端口 → 改用 DNS-01 插件，或先停网关再申请 |
| 证书生成但网关仍显示旧证书 | 未 reload；`docker exec mogo-gateway-1 nginx -s reload` |
| 内网部署无公网域名 | 不要用本组件，走 `deploy/tls/README.md` 手工更换 |