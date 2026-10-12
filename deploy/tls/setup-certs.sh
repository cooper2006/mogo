#!/bin/bash
# 将项目根目录的自签名证书复制到 deploy/tls/ 供 nginx 使用。
# 用法: bash deploy/tls/setup-certs.sh
#
# 预期源文件（项目根目录）:
#   server.crt  → deploy/tls/fullchain.pem
#   server.key  → deploy/tls/privkey.pem

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TLS_DIR="$SCRIPT_DIR"

echo "📋 源目录: $PROJECT_ROOT"
echo "📁 目标目录: $TLS_DIR"

# 检查源文件是否存在
if [[ ! -f "$PROJECT_ROOT/server.crt" ]]; then
    echo "❌ 未找到 $PROJECT_ROOT/server.crt"
    echo "   用法: bash deploy/tls/setup-certs.sh"
    exit 1
fi

if [[ ! -f "$PROJECT_ROOT/server.key" ]]; then
    echo "❌ 未找到 $PROJECT_ROOT/server.key"
    echo "   用法: bash deploy/tls/setup-certs.sh"
    exit 1
fi

# 检查证书有效性
CERT_EXPIRY=$(openssl x509 -in "$PROJECT_ROOT/server.crt" -noout -enddate 2>/dev/null | cut -d= -f2)
CERT_SUBJECT=$(openssl x509 -in "$PROJECT_ROOT/server.crt" -noout -subject 2>/dev/null | cut -d= -f2)
echo "📜 证书主题: $CERT_SUBJECT"
echo "⏰ 到期时间: $CERT_EXPIRY"

# 检查证书是否过期
if openssl x509 -in "$PROJECT_ROOT/server.crt" -noout -checkend 0 2>/dev/null; then
    echo "✅ 证书未过期"
else
    echo "⚠️  证书已过期！请重新生成:"
    echo "   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \\"
    echo "     -keyout server.key -out server.crt -subj '/CN=localhost' \\"
    echo "     -addext 'subjectAltName = DNS:localhost,IP:127.0.0.1'"
    exit 1
fi

# 检查 SAN（Subject Alternative Name）—— 现代浏览器强制要求
if ! openssl x509 -in "$PROJECT_ROOT/server.crt" -noout -text 2>/dev/null | grep -q "Subject Alternative Name"; then
    echo ""
    echo "⚠️  证书缺少 Subject Alternative Name (SAN) 扩展"
    echo "   现代浏览器（Chrome/Firefox）会拒绝此证书。"
    echo "   如需浏览器信任，请重新生成:"
    echo ""
    echo "   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \\"
    echo "     -keyout server.key -out server.crt -subj '/CN=localhost' \\"
    echo "     -addext 'subjectAltName = DNS:localhost,IP:127.0.0.1'"
    echo ""
    echo "   仅用于 curl -k / 后端 API 调用时可忽略此警告。"
fi

# 复制证书
#
# ⚠️ 权限必须显式归一化，不能只 cp 完就走：``cp`` 会保留源文件模式，而
# ``server.key`` 是 openssl 生成的 0600，cp 出来就是 0600。
#
# 为什么 0600 会让网关起不来：自 022 FR-26/T026 起网关以非 root 的
# appuser(UID 10001) 运行，证书是 bind mount 进容器的。Linux 上 bind mount
# 保留宿主 uid，0600 的私钥归宿主用户所有 → 容器内 nginx 启动即失败：
#   nginx: [emerg] cannot load certificate key "/etc/nginx/certs/privkey.pem"
#                  (13: Permission denied)
# 随后进入 crash-loop。
#
# ⚠️ macOS / OrbStack 的 bind mount 会把文件属主映射成容器运行用户，所以 0600
# 在本地也能跑。不要因为本机跑得通就认为权限没问题 —— 生产 Linux 会挂。
#
# 0644 = 容器内任意 uid 都能读，与 docker-compose.yml 里 gateway 的注释一致。
# 若要求更严格（私钥不 world-readable），脚本无法 sudo，请手动改属主：
#   sudo chown 10001:10001 deploy/tls/privkey.pem && chmod 0600 deploy/tls/privkey.pem
cp "$PROJECT_ROOT/server.crt" "$TLS_DIR/fullchain.pem"
cp "$PROJECT_ROOT/server.key" "$TLS_DIR/privkey.pem"
chmod 0644 "$TLS_DIR/fullchain.pem" "$TLS_DIR/privkey.pem"

# 自检：确认私钥至少有一个「非 owner」可读位。容器内跑的是 uid 10001，它不是宿主
# 上的文件属主，所以只靠 owner 位（0600/0400）在 Linux 上必然读不到。
if [[ -z "$(find "$TLS_DIR/privkey.pem" -perm -004 -print 2>/dev/null)" ]]; then
    echo "❌ deploy/tls/privkey.pem 缺少 o+r，容器内 appuser(UID 10001) 读不到，"
    echo "   网关会在启用 TLS 后 crash-loop。修复: chmod 0644 $TLS_DIR/privkey.pem"
    exit 1
fi

echo ""
echo "✅ 证书已复制到 deploy/tls/"
echo "   私钥模式: $(ls -l "$TLS_DIR/privkey.pem" | awk '{print $1}')（容器内 UID 10001 可读）"
echo ""
echo "启用 HTTPS:"
echo "  MOGO_NGINX_CONF=./deploy/nginx/nginx.conf docker compose up -d"
echo ""
echo "验证:"
echo "  curl -k https://localhost:443/healthz"
echo "  openssl s_client -connect localhost:443 -servername localhost 2>/dev/null | openssl x509 -noout -subject -dates"
