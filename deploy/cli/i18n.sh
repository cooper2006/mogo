#!/usr/bin/env bash

movo_detect_locale() {
  local requested="${MOVO_LANG:-en}"
  requested="$(printf '%s' "${requested}" | tr '[:upper:]' '[:lower:]')"
  case "${requested}" in
    zh|zh-*|zh_*|cn|chinese)
      MOVO_LOCALE=zh
      ;;
    *)
      MOVO_LOCALE=en
      ;;
  esac
}

movo_usage() {
  if [[ "${MOVO_LOCALE}" == "zh" ]]; then
    printf '用法：\n'
    printf '  ./movo [--lang zh-CN|en] up [--build]  启动 MOGO 并输出初始化地址\n'
    printf '  ./movo build                          从源码构建 MOGO 镜像\n'
    printf '  ./movo update                         拉取当前版本镜像并更新服务\n'
    printf '  ./movo backup [目录]                  停机一致性备份全部 MOGO 数据卷\n'
    printf '  ./movo restore <目录> --yes           校验并恢复 MOGO 数据卷\n'
    printf '  ./movo status                         查看服务状态\n'
    printf '  ./movo logs [服务名]                  查看日志\n'
    printf '  ./movo restart                        重启服务\n'
    printf '  ./movo down                           停止服务（保留数据卷）\n'
    printf '  ./movo down -v                        停止服务并删除全部 MOGO 数据\n'
  else
    printf 'Usage:\n'
    printf '  ./movo [--lang zh-CN|en] up [--build]  Start MOGO and print the setup URL\n'
    printf '  ./movo build                           Build MOGO images from source\n'
    printf '  ./movo update                          Pull current images and update services\n'
    printf '  ./movo backup [directory]              Back up all MOGO volumes while stopped\n'
    printf '  ./movo restore <directory> --yes       Verify and restore MOGO volumes\n'
    printf '  ./movo status                          Show service status\n'
    printf '  ./movo logs [service]                  Show logs\n'
    printf '  ./movo restart                         Restart services\n'
    printf '  ./movo down                            Stop services and preserve volumes\n'
    printf '  ./movo down -v                         Stop services and delete all MOGO data\n'
  fi
}

movo_msg() {
  local key="$1"
  shift
  case "${MOVO_LOCALE}:${key}" in
    zh:docker_missing) printf '错误：未找到 Docker，请先安装 Docker Engine 或 Docker Desktop。\n' ;;
    en:docker_missing) printf 'Error: Docker was not found. Install Docker Engine or Docker Desktop first.\n' ;;
    zh:compose_missing) printf '错误：未找到 Docker Compose v2。\n' ;;
    en:compose_missing) printf 'Error: Docker Compose v2 was not found.\n' ;;
    zh:docker_stopped) printf '错误：Docker 尚未运行，请先启动 Docker。\n' ;;
    en:docker_stopped) printf 'Error: Docker is not running. Start Docker first.\n' ;;
    zh:image_source_missing) printf '错误：无法确定公开镜像地址。请从 GitHub 克隆仓库、在 .env 设置 MOGO_IMAGE_REGISTRY，或执行 ./movo up --build。\n' ;;
    en:image_source_missing) printf 'Error: public image location is unknown. Clone from GitHub, set MOGO_IMAGE_REGISTRY in .env, or run ./movo up --build.\n' ;;
    zh:using_local_images) printf '未配置公开镜像地址，将使用现有的本地 MOGO 镜像。\n' ;;
    en:using_local_images) printf 'No public image location is configured; using existing local MOGO images.\n' ;;
    zh:update_local_only) printf '错误：当前仅配置了本地镜像。请先设置 MOGO_IMAGE_REGISTRY，或使用 ./movo up --build 重新构建。\n' ;;
    en:update_local_only) printf 'Error: only local images are configured. Set MOGO_IMAGE_REGISTRY first, or rebuild with ./movo up --build.\n' ;;
    zh:waiting) printf '\n正在等待服务健康检查' ;;
    en:waiting) printf '\nWaiting for deployment health checks' ;;
    zh:done) printf ' 完成\n' ;;
    en:done) printf ' done\n' ;;
    zh:timeout) printf '\n服务未在预期时间内全部就绪。请执行 ./movo status 和 ./movo logs 查看原因。\n' ;;
    en:timeout) printf '\nServices did not become ready in time. Run ./movo status and ./movo logs for details.\n' ;;
    zh:ready_title) printf '\nMOGO 已启动。请在浏览器中完成首次初始化：\n\n' ;;
    en:ready_title) printf '\nMOGO is running. Complete the initial setup in your browser:\n\n' ;;
    zh:starting) printf '正在启动 MOGO 服务...\n' ;;
    en:starting) printf 'Starting MOGO services...\n' ;;
    zh:building) printf '正在从源码构建 MOGO 镜像...\n' ;;
    en:building) printf 'Building MOGO images from source...\n' ;;
    zh:pruned_dangling) printf '已清理构建残留的无标签镜像，释放约 %s MB。\n' "$1" ;;
    en:pruned_dangling) printf 'Pruned untagged build leftovers, reclaimed about %s MB.\n' "$1" ;;
    zh:updating) printf '正在拉取 MOGO 镜像并更新服务...\n' ;;
    en:updating) printf 'Pulling MOGO images and updating services...\n' ;;
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
    zh:remove_aborted) printf '已取消。自动化环境请显式传入 ./movo down -v --yes。\n' ;;
    en:remove_aborted) printf 'Cancelled. For automation, explicitly pass ./movo down -v --yes.\n' ;;
    zh:start_failed) printf '\nMOGO 启动失败，当前服务状态如下：\n' ;;
    en:start_failed) printf '\nMOGO failed to start. Current service status:\n' ;;
    zh:logs_hint) printf '请执行 ./movo logs 查看详细日志。\n' ;;
    en:logs_hint) printf 'Run ./movo logs for detailed logs.\n' ;;
    zh:stopped) printf 'MOGO 已停止，数据卷仍然保留。\n' ;;
    en:stopped) printf 'MOGO has stopped. Data volumes are preserved.\n' ;;
    zh:stopped_removed) printf 'MOGO 已停止，数据卷和初始化数据已删除。\n' ;;
    en:stopped_removed) printf 'MOGO has stopped. Data volumes and setup state were deleted.\n' ;;
    zh:unknown) printf '未知命令：%s\n\n' "$1" ;;
    en:unknown) printf 'Unknown command: %s\n\n' "$1" ;;
    *) printf '%s' "${key}" ;;
  esac
}
