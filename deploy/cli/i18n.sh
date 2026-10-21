#!/usr/bin/env bash

mogo_detect_locale() {
  local requested="${MOGO_LANG:-en}"
  requested="$(printf '%s' "${requested}" | tr '[:upper:]' '[:lower:]')"
  case "${requested}" in
    zh|zh-*|zh_*|cn|chinese)
      MOGO_LOCALE=zh
      ;;
    *)
      MOGO_LOCALE=en
      ;;
  esac
}

mogo_usage() {
  if [[ "${MOGO_LOCALE}" == "zh" ]]; then
    printf '用法：\n'
    printf '  ./mogo [--lang zh-CN|en] up [--build]  启动 MOGO 并输出初始化地址\n'
    printf '  ./mogo build                          从源码构建 MOGO 镜像\n'
    printf '  ./mogo update                         拉取当前版本镜像并更新服务\n'
    printf '  ./mogo backup [目录]                  停机一致性备份全部 MOGO 数据卷\n'
    printf '  ./mogo restore <目录> --yes           校验并恢复 MOGO 数据卷\n'
    printf '  ./mogo status                         查看服务状态\n'
    printf '  ./mogo logs [服务名]                  查看日志\n'
    printf '  ./mogo restart                        重启服务\n'
    printf '  ./mogo down                           停止服务（保留数据卷）\n'
    printf '  ./mogo down -v                        停止服务并删除全部 MOGO 数据\n'
  else
    printf 'Usage:\n'
    printf '  ./mogo [--lang zh-CN|en] up [--build]  Start MOGO and print the setup URL\n'
    printf '  ./mogo build                           Build MOGO images from source\n'
    printf '  ./mogo update                          Pull current images and update services\n'
    printf '  ./mogo backup [directory]              Back up all MOGO volumes while stopped\n'
    printf '  ./mogo restore <directory> --yes       Verify and restore MOGO volumes\n'
    printf '  ./mogo status                          Show service status\n'
    printf '  ./mogo logs [service]                  Show logs\n'
    printf '  ./mogo restart                         Restart services\n'
    printf '  ./mogo down                            Stop services and preserve volumes\n'
    printf '  ./mogo down -v                         Stop services and delete all MOGO data\n'
  fi
}

mogo_msg() {
  local key="$1"
  shift
  case "${MOGO_LOCALE}:${key}" in
    zh:docker_missing) printf '错误：未找到 Docker，请先安装 Docker Engine 或 Docker Desktop。\n' ;;
    en:docker_missing) printf 'Error: Docker was not found. Install Docker Engine or Docker Desktop first.\n' ;;
    zh:compose_missing) printf '错误：未找到 Docker Compose v2。\n' ;;
    en:compose_missing) printf 'Error: Docker Compose v2 was not found.\n' ;;
    zh:docker_stopped) printf '错误：Docker 尚未运行，请先启动 Docker。\n' ;;
    en:docker_stopped) printf 'Error: Docker is not running. Start Docker first.\n' ;;
    zh:image_source_missing) printf '错误：无法确定公开镜像地址。请从 GitHub 克隆仓库、在 .env 设置 MOGO_IMAGE_REGISTRY，或执行 ./mogo up --build。\n' ;;
    en:image_source_missing) printf 'Error: public image location is unknown. Clone from GitHub, set MOGO_IMAGE_REGISTRY in .env, or run ./mogo up --build.\n' ;;
    zh:using_local_images) printf '未配置公开镜像地址，将使用现有的本地 MOGO 镜像。\n' ;;
    en:using_local_images) printf 'No public image location is configured; using existing local MOGO images.\n' ;;
    zh:update_local_only) printf '错误：当前仅配置了本地镜像。请先设置 MOGO_IMAGE_REGISTRY，或使用 ./mogo up --build 重新构建。\n' ;;
    en:update_local_only) printf 'Error: only local images are configured. Set MOGO_IMAGE_REGISTRY first, or rebuild with ./mogo up --build.\n' ;;
    zh:waiting) printf '\n正在等待服务健康检查' ;;
    en:waiting) printf '\nWaiting for deployment health checks' ;;
    zh:done) printf ' 完成\n' ;;
    en:done) printf ' done\n' ;;
    zh:timeout) printf '\n服务未在预期时间内全部就绪。请执行 ./mogo status 和 ./mogo logs 查看原因。\n' ;;
    en:timeout) printf '\nServices did not become ready in time. Run ./mogo status and ./mogo logs for details.\n' ;;
    zh:ready_title) printf '\nMOGO 已启动。请在浏览器中完成首次初始化：\n\n' ;;
    en:ready_title) printf '\nMOGO is running. Complete the initial setup in your browser:\n\n' ;;
    zh:starting) printf '正在启动 MOGO 服务...\n' ;;
    en:starting) printf 'Starting MOGO services...\n' ;;
    zh:building) printf '正在从源码构建 MOGO 镜像...\n' ;;
    en:building) printf 'Building MOGO images from source...\n' ;;
    zh:pruned_dangling) printf '已清理构建残留的无标签镜像，释放约 %s MB。\n' "$1" ;;
    en:pruned_dangling) printf 'Pruned untagged build leftovers, reclaimed about %s MB.\n' "$1" ;;
    zh:pruned_previous_release) printf '已清理上一版本的 %s 个镜像，释放约 %s MB。\n' "$1" "$2" ;;
    en:pruned_previous_release) printf 'Pruned %s image(s) from the previous release, reclaimed about %s MB.\n' "$1" "$2" ;;
    zh:updating) printf '正在拉取 MOGO 镜像并更新服务...\n' ;;
    en:updating) printf 'Pulling MOGO images and updating services...\n' ;;
    zh:dsh_lb_reload_failed) printf '提示：DSH 负载均衡器重载配置失败，其上游地址可能仍是旧 IP（已有自动重试兜底）。\n' ;;
    en:dsh_lb_reload_failed) printf 'Note: the DSH load balancer failed to reload; its upstreams may still hold stale IPs (automatic retry still covers this).\n' ;;
    zh:pulling_images) printf '正在串行拉取镜像（第 %s 次）...\n' "$1" ;;
    en:pulling_images) printf 'Pulling images sequentially (attempt %s)...\n' "$1" ;;
    zh:pull_retry) printf '第 %s 次拉取失败，%s 秒后继续重试；按 Ctrl+C 可停止。\n' "$1" "$2" ;;
    en:pull_retry) printf 'Image pull attempt %s failed; retrying in %s seconds. Press Ctrl+C to stop.\n' "$1" "$2" ;;
    zh:base_images_reused) printf '基础镜像已存在于本地，跳过远端拉取（复用 %s 个）。\n' "$1" ;;
    en:base_images_reused) printf 'Base images already exist locally; skipping remote downloads (reused %s).\n' "$1" ;;
    zh:base_image_pulling) printf '本地缺少基础镜像 %s，正在拉取...\n' "$1" ;;
    en:base_image_pulling) printf 'Base image %s is missing locally; pulling...\n' "$1" ;;
    zh:base_image_pull_failed) printf '错误：无法获取基础镜像 %s。\n' "$1" ;;
    en:base_image_pull_failed) printf 'Error: unable to obtain base image %s.\n' "$1" ;;
    zh:base_image_missing) printf '错误：本地缺少基础镜像 %s，且当前策略禁止联网拉取。\n' "$1" ;;
    en:base_image_missing) printf 'Error: base image %s is missing locally and the current policy forbids network pulls.\n' "$1" ;;
    zh:backup_stopping) printf '正在停止服务并创建一致性数据卷备份...\n' ;;
    en:backup_stopping) printf 'Stopping services to create a consistent volume backup...\n' ;;
    zh:backup_failed) printf '备份失败，正在尝试恢复服务。\n' ;;
    en:backup_failed) printf 'Backup failed; attempting to restart the deployment.\n' ;;
    zh:backup_complete) printf '备份完成：%s\n' "$1" ;;
    en:backup_complete) printf 'Backup completed: %s\n' "$1" ;;
    zh:restore_confirm) printf '恢复会覆盖当前全部 MOGO 数据。确认后请重新执行并添加 --yes。\n' ;;
    en:restore_confirm) printf 'Restore overwrites all current MOGO data. Run the command again with --yes to confirm.\n' ;;
    zh:restore_complete) printf 'MOGO 数据恢复完成，服务已就绪。\n' ;;
    en:restore_complete) printf 'MOGO data restoration completed and services are ready.\n' ;;
    zh:dsh_build_target) printf 'DSH Runtime 目标构建版本：%s\n' "$1" ;;
    en:dsh_build_target) printf 'DSH Runtime build target: %s\n' "$1" ;;
    zh:dsh_running_version) printf 'DSH Runtime 运行版本：%s\n' "$1" ;;
    en:dsh_running_version) printf 'DSH Runtime running version: %s\n' "$1" ;;
    zh:migrating_project) printf '正在迁移旧版 Compose 服务名（数据卷会保留）...\n' ;;
    en:migrating_project) printf 'Migrating the legacy Compose project name (data volumes are preserved)...\n' ;;
    zh:remove_confirm) printf '这会永久删除全部 MOGO 数据卷和初始化数据。输入 MOGO 确认：' ;;
    en:remove_confirm) printf 'This permanently deletes all MOGO volumes and setup data. Type MOGO to confirm: ' ;;
    zh:remove_aborted) printf '已取消。自动化环境请显式传入 ./mogo down -v --yes。\n' ;;
    en:remove_aborted) printf 'Cancelled. For automation, explicitly pass ./mogo down -v --yes.\n' ;;
    zh:start_failed) printf '\nMOGO 启动失败，当前服务状态如下：\n' ;;
    en:start_failed) printf '\nMOGO failed to start. Current service status:\n' ;;
    zh:logs_hint) printf '请执行 ./mogo logs 查看详细日志。\n' ;;
    en:logs_hint) printf 'Run ./mogo logs for detailed logs.\n' ;;
    zh:stopped) printf 'MOGO 已停止，数据卷仍然保留。\n' ;;
    en:stopped) printf 'MOGO has stopped. Data volumes are preserved.\n' ;;
    zh:stopped_removed) printf 'MOGO 已停止，数据卷和初始化数据已删除。\n' ;;
    en:stopped_removed) printf 'MOGO has stopped. Data volumes and setup state were deleted.\n' ;;
    zh:tls_generating_certs) printf '未找到 TLS 证书，正在 %s 生成自签名证书对（CN=localhost）...\n' "$1" ;;
    en:tls_generating_certs) printf 'No TLS certificate pair found; generating a self-signed pair (CN=localhost) in %s...\n' "$1" ;;
    zh:tls_certs_generated) printf '已生成自签名证书：%s/fullchain.pem 与 privkey.pem（权限 0644）。浏览器会提示不安全；正式环境请换成 CA 签发的证书。\n' "$1" ;;
    en:tls_certs_generated) printf 'Generated a self-signed certificate pair in %s (mode 0644). Browsers will warn; replace it with a CA-issued pair for real use.\n' "$1" ;;
    zh:tls_cert_generated_without_san) printf '提示：当前 openssl 不支持 -addext，生成的证书没有 SAN，浏览器会拒绝；curl -k 与服务端调用不受影响。\n' ;;
    en:tls_cert_generated_without_san) printf 'Note: this openssl has no -addext, so the certificate was generated without a SAN and browsers will reject it; curl -k and server-to-server calls are unaffected.\n' ;;
    zh:tls_certs_missing_no_openssl) printf '错误：网关已启用 TLS，但 %s 下没有证书，且本机没有 openssl 无法生成。请放入 fullchain.pem 与 privkey.pem（私钥需 0644），或安装 openssl 后重试。\n' "$1" ;;
    en:tls_certs_missing_no_openssl) printf 'Error: TLS is enabled for the gateway but no certificate pair exists in %s, and openssl is unavailable to generate one. Place fullchain.pem and privkey.pem there (private key mode 0644), or install openssl and retry.\n' "$1" ;;
    zh:tls_cert_generation_failed) printf '错误：openssl 生成证书失败（%s）。请手动生成，或把 MOGO_NGINX_CONF 指向 deploy/docker/nginx.conf 临时退回 HTTP。\n' "$1" ;;
    en:tls_cert_generation_failed) printf 'Error: openssl failed to generate a certificate pair in %s. Generate one manually, or point MOGO_NGINX_CONF at deploy/docker/nginx.conf to fall back to HTTP for now.\n' "$1" ;;
    zh:tls_gateway_restart_failed) printf '提示：重启 gateway 让新证书生效失败，请执行 ./mogo restart 手动重启。\n' ;;
    en:tls_gateway_restart_failed) printf 'Note: restarting the gateway to apply the new certificate failed; run ./mogo restart manually.\n' ;;
    zh:local_images_missing) printf '错误：本地缺少 %s 个 MOGO 应用镜像。\n' "$1" ;;
    en:local_images_missing) printf 'Error: %s MOGO application image(s) are missing locally.\n' "$1" ;;
    zh:local_images_missing_hint) printf '纯 registry 拉取链路已停用：本仓库生成的 ghcr.io/mogoai/<service> 引用并不存在（实测 denied）。请改用 ./mogo up --build 从源码构建；若要固定版本，先设 MOGO_VERSION=vX.Y.Z。\n' ;;
    en:local_images_missing_hint) printf 'The pure-registry path is retired: the ghcr.io/mogoai/<service> reference this repository generates does not exist (verified denied). Build from source with ./mogo up --build instead; set MOGO_VERSION=vX.Y.Z to pin a version.\n' ;;
    zh:update_registry_retired) printf '错误：./mogo update 依赖的 registry 拉取链路已停用——本仓库生成的 ghcr.io/mogoai/<service> 引用并不存在（实测 denied），且旧实现会无限重试。请改用 ./mogo up --build 从源码构建并更新（先 MOGO_VERSION=vX.Y.Z 可固定到某个发布 tag）。\n' ;;
    en:update_registry_retired) printf 'Error: ./mogo update relied on the registry pull path, which is retired -- the ghcr.io/mogoai/<service> reference this repository generates does not exist (verified denied), and the old implementation retried it forever. Rebuild and update from source with ./mogo up --build instead (set MOGO_VERSION=vX.Y.Z to pin a release tag).\n' ;;
    zh:unknown) printf '未知命令：%s\n\n' "$1" ;;
    en:unknown) printf 'Unknown command: %s\n\n' "$1" ;;
    *) printf '%s' "${key}" ;;
  esac
}
