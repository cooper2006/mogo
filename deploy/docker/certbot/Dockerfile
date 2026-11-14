# 024 T093 (FR-046/FR-048)：Certbot 容器（可选 ACME 自动续期）。
#
# 用途：对有公网域名 + 有效授权（HTTP-01 或 DNS-01）的场景自动申请 / 续期
# Let's Encrypt 证书，结果输出到 deploy/tls/（与网关挂载目录一致）。
# 没有公网域名 / 没有授权时**不要**启用本容器，请走 deploy/tls/README.md 的
# 手工更换流程（T094）。
#
# 镜像：基础镜像使用 certbot/certbot（通过镜像站 docker.m.daocloud.io 拉取，
#      避免 Docker Hub 直连 Bad Gateway）。构建与运行见 README.md。

FROM docker.m.daocloud.io/certbot/certbot:latest

# 非 root 运行（延续 022 FR-26 的 appuser 约定）
USER root

# 入口脚本：默认走 HTTP-01 自动续期，失败时告警并不阻断主部署
COPY docker-entrypoint.sh /usr/local/bin/mogo-certbot-entrypoint
RUN chmod +x /usr/local/bin/mogo-certbot-entrypoint

ENTRYPOINT ["/usr/local/bin/mogo-certbot-entrypoint"]