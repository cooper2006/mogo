#!/usr/bin/env bash
# 024 T093：Certbot 容器入口 —— ACME 申请 / 续期并将结果拷到 deploy/tls。
#
# 容器启动时执行：
#   1) 若证书不存在 → 用 --standalone 方式申请（需 80/443 可达，仅用于首次）
#      更推荐用 DNS-01 插件（见 README.md），本入口聚焦 HTTP-01。
#   2) 已存在 → 执行 renew，仅到期前续期（--force-renewal 可强制）。
#   3) 把 live/ 下的证书拷贝成 deploy/tls/{fullchain,privkey}.pem 并 chmod 0644，
#      保持与手工流程一致的权限（容器内 uid 10001 需可读）。
#
# 环境变量：
#   CERTBOT_DOMAINS   必填，逗号分隔（如 "mogo.example.com,api.mogo.example.com"）
#   CERTBOT_EMAIL     必填，续期通知邮箱
#   CERTBOT_RENEW_ONLY 设为 1 时只做 renew，不申请新证书（默认自动判断）
#   CERTBOT_WEBROOT   设为 webroot 路径（推荐，避免占用 80/443）
#   CERTBOT_EXTRA     额外参数透传（如 --dns-cloudflare 等插件参数）

set -Eeuo pipefail

CERTBOT_DOMAINS="${CERTBOT_DOMAINS:-}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

if [[ -z "${CERTBOT_DOMAINS}" || -z "${CERTBOT_EMAIL}" ]]; then
  printf 'FAIL 需要 CERTBOT_DOMAINS 与 CERTBOT_EMAIL\n' >&2
  exit 2
fi

DOMAIN="${CERTBOT_DOMAINS%%,*}"
LIVE_DIR="/etc/letsencrypt/live/${DOMAIN}"
OUT_DIR="/etc/nginx/certs"           # 容器内网关证书挂载目录

# 解析 domains 参数：-d a -d b
DOMAIN_ARGS=()
IFS=',' read -ra DL <<<"${CERTBOT_DOMAINS}"
for d in "${DL[@]}"; do
  [[ -n "${d}" ]] && DOMAIN_ARGS+=("-d" "${d}")
done

MODE_ARGS=()
if [[ -n "${CERTBOT_WEBROOT:-}" ]]; then
  MODE_ARGS+=(--webroot -w "${CERTBOT_WEBROOT}")
else
  MODE_ARGS+=(--standalone --preferred-challenges http)
fi

renew_only=0
[[ "${CERTBOT_RENEW_ONLY:-0}" == "1" ]] && renew_only=1

if [[ -d "${LIVE_DIR}" ]] && [[ "${renew_only}" == "0" ]]; then
  # 已存在证书 → 只续期
  renew_only=1
fi

EXTRA=()
if [[ -n "${CERTBOT_EXTRA:-}" ]]; then
  # 简单空格分词，供插件参数使用
  # shellcheck disable=SC2206
  EXTRA=(${CERTBOT_EXTRA})
fi

CERTBOT_ARGS=(certonly --non-interactive --agree-tos --email "${CERTBOT_EMAIL}" \
  --expand --keep-until-expiring "${DOMAIN_ARGS[@]}" "${MODE_ARGS[@]}" "${EXTRA[@]}")

if [[ "${renew_only}" == "1" ]]; then
  printf 'RUN certbot renew（已存在证书，%s）\n' "${LIVE_DIR}"
  certbot renew --non-interactive --agree-tos "${EXTRA[@]}"
else
  printf 'RUN certbot 申请新证书 domains=%s\n' "${CERTBOT_DOMAINS}"
  certbot "${CERTBOT_ARGS[@]}"
fi

# 拷出证书到网关目录，权限归一化（0644）
if [[ -f "${LIVE_DIR}/fullchain.pem" ]]; then
  install -m 0644 "${LIVE_DIR}/fullchain.pem" "${OUT_DIR}/fullchain.pem"
  install -m 0644 "${LIVE_DIR}/privkey.pem"   "${OUT_DIR}/privkey.pem"
  printf 'OK 证书已更新: %s → %s\n' "${LIVE_DIR}" "${OUT_DIR}"
  openssl x509 -in "${OUT_DIR}/fullchain.pem" -noout -subject -dates || true
else
  printf 'FAIL 未生成 fullchain.pem（%s）\n' "${LIVE_DIR}" >&2
  exit 1
fi

# 触发网关重新加载证书（reload 比重建快且不断连）
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q 'mogo-gateway'; then
  docker exec mogo-gateway-1 nginx -s reload >/dev/null 2>&1 || \
    printf 'WARN 未能 reload gateway，请手动 ./mogo restart gateway\n' >&2
fi

printf 'certbot 完成\n'