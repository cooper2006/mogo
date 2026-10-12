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
cp "$PROJECT_ROOT/server.crt" "$TLS_DIR/fullchain.pem"
cp "$PROJECT_ROOT/server.key" "$TLS_DIR/privkey.pem"

echo ""
echo "✅ 证书已复制到 deploy/tls/"
echo ""
echo "启用 HTTPS:"
echo "  MOGO_NGINX_CONF=./deploy/nginx/nginx.conf docker compose up -d"
echo ""
echo "验证:"
echo "  curl -k https://localhost:443/healthz"
echo "  openssl s_client -connect localhost:443 -servername localhost 2>/dev/null | openssl x509 -noout -subject -dates"
