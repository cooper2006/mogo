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

1. **放证书**到本目录（或 `MOGO_TLS_CERTS_DIR` 指向的目录）：

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

2. **切换网关配置**（compose 层挂载切换，不需要改仓库里的文件）：

   ```bash
   MOGO_NGINX_CONF=./deploy/nginx/nginx.conf docker compose up -d gateway
   ```

   `deploy/nginx/nginx.conf` 是 TLS 侧配置的唯一事实来源，
   `deploy/docker/nginx-https.conf` 是等价的兼容入口。
   443 端口已由 `docker-compose.yml` 无条件暴露（`MOGO_HTTPS_PORT`，默认 443）。

3. **验证**：

   ```bash
   curl -k https://localhost/healthz
   openssl s_client -connect localhost:443 -servername localhost </dev/null 2>/dev/null \
     | openssl x509 -noout -subject -dates
   ```

   HTTP(80) 会 301 跳转到 HTTPS，`/healthz` 例外（供负载均衡探针使用）。

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

回归守卫见 `deploy/tests/test_tls_gateway_config.py`。
