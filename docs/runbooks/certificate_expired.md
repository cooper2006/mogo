# 证书过期

> 告警：`MogoServiceScrapeDown`（P0，仅在网关探活覆盖时）/ 浏览器侧 TLS 报错
> 关联场景：全站 HTTPS 打不开、API 客户端报证书错误

> 说明：本场景目前**没有专属告警规则**。证书到期不会让 `/ready` 失败，也不会让
> `up` 变 0（Prometheus 走内网明文抓取），所以属于「监控盲区」——下方 §1 给出了
> 必须人工/脚本前置检查的替代手段，并把「证书到期天数指标」列为改进项。

## 1. 症状

- 浏览器地址栏证书警告（`NET::ERR_CERT_DATE_INVALID`）；
- `curl -v https://<域名>/` 报 `certificate has expired`；
- 客户端 SDK 全线握手失败，服务端日志却一切正常（**故障在 TLS 层，应用无感**）；
- 用户侧：整个站点/网关不可访问，比单个服务故障影响面更大。

[只读排查]

```bash
# 证书有效期（仓库内自签/挂载证书）
openssl x509 -in deploy/tls/fullchain.pem -noout -dates -subject
openssl x509 -in deploy/tls/fullchain.pem -noout -enddate

# 线上真实域名（把 example.com 换成实际域名）
echo | openssl s_client -servername example.com -connect example.com:443 2>/dev/null \
  | openssl x509 -noout -dates

# 剩余天数一键检查
openssl x509 -in deploy/tls/fullchain.pem -noout -checkend 604800 && echo "7天内不会过期" || echo "7天内过期！"
```

## 2. 影响

- 全站不可用（HTTPS 握手失败），影响面**大于任何单服务故障**；
- 若存在非 TLS 入口（内网明文），可能出现「内网正常、外网全挂」的误判陷阱；
- API 客户端若未关闭校验，会连续重试放大日志与告警噪音。

## 3. 根因（按概率排序）

1. **证书自然到期** — 最常见。自签证书默认 365 天，无人续期。
2. **续期后未重载网关** — 文件已更新但 nginx 未 `reload`，仍在用旧证书。
3. **部署了错误的证书链** — `fullchain.pem` 缺中间证书，部分客户端（Android/Java）
   校验失败但桌面浏览器正常。
4. **私钥权限** — 022 FR-26 起网关以非 root(UID 10001) 运行，私钥 0600 会导致
   `cannot load certificate key ... Permission denied`（表现为启动失败而非过期）。
5. **域名与 SAN 不匹配** — 证书未覆盖实际访问域名。

## 4. 恢复步骤

```bash
# A. 重新签发/续期（自签，会改状态）
bash deploy/tls/setup-certs.sh
# 生产建议用 ACME：
#   certbot renew --deploy-hook 'docker compose exec gateway nginx -s reload'

# B. 权限修正（必须 0644 或容器内 UID 可读；私钥不可 world-readable 但需 10001 可读）
chmod 640 deploy/tls/privkey.pem
ls -l deploy/tls/

# C. 重载网关（不中断连接）
docker compose exec gateway nginx -t          # 先校验配置
docker compose exec gateway nginx -s reload

# D. 校验证书链完整性
openssl verify -CAfile deploy/tls/fullchain.pem deploy/tls/fullchain.pem
```

**禁止**：不要把私钥提交到仓库（`scripts/check-secrets.sh` 会拦截）；不要让
`nginx -s reload` 在 `nginx -t` 失败时执行（会保留旧配置但掩盖问题）。

## 5. 验证

```bash
echo | openssl s_client -servername <域名> -connect <域名>:443 2>/dev/null | openssl x509 -noout -dates
curl -sSf -o /dev/null -w '%{http_code}\n' https://<域名>/
curl -s http://127.0.0.1:9093/api/v2/alerts | grep -i cert || echo "（无证书相关告警规则，见 §改进）"
```

## 6. 事后复盘模板

```markdown
### 复盘：证书过期（YYYY-MM-DD）
- 过期时间 / 发现时间 / 恢复时间 / 不可用总时长：
- 为什么没有提前发现？现有检查（CI / 定时任务）是否覆盖：
- 影响面：外部用户占比、是否有客户端长连接被强断：
- 改进项：
  - [ ] 接入 `x509_cert_not_after` 类文本文件导出 + Prometheus textfile collector，
        补 `MogoCertificateExpiringSoon` 规则（P0：< 7 天）
  - [ ] 续期自动化与到期前 30/14/7 天提醒
  - [ ] nginx reload 纳入续期 hook 并验证
```
