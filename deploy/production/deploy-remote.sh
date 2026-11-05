#!/usr/bin/env bash
# =============================================================================
# mogo 远程部署脚本（docker context over SSH）
# -----------------------------------------------------------------------------
# 通过 docker context 把 mogo 部署到「远端 Docker 主机」，而不是本机。
# 场景与 deploy-offline.sh 一致：AMD64、停用 mongo / panweidb 容器、
# 用外部 PanWeiDB + 栈内 Redis，全部走离线 / 国内镜像。
#
# 与 deploy-offline.sh 的关键区别：
#   镜像不是导到「本机」docker，而是导到「远端 daemon」：
#     - base-images/*.tar 通过 `docker --context <name> load` 直接灌入远端 daemon
#       （走 SSH 隧道，架构天然是远端 amd64，不会因本机是 arm64 而错）。
#     - 缺失的应用镜像由「远端 daemon」直接拉取（--platform linux/amd64），
#       优先国内镜像站，失败回退上游。远端需能访问外网；若完全离线，
#       请用 --app-tar-dir 把应用镜像 tar 包一并 load 到远端。
#   应用连外部 PanWeiDB 的连接信息从本仓库 .env 读取（compose CLI 在本地
#   读取 .env 后将配置下发到远端 daemon）。
#
# 用法：
#   bash deploy/production/deploy-remote.sh [选项]
#
# 选项：
#   --remote-env <file>  连接信息文件（默认 deploy/production/remote.env）
#   --version <tag>      应用镜像版本（默认 .env 的 MOGO_VERSION → latest）
#   --app-tar-dir <dir>  额外的应用镜像 tar 目录，load 到远端 daemon
#   --docker-hub-mirror / --ghcr-mirror / --base-images
#   --skip-load          跳过 base-images 导入
#   --skip-app-pull      跳过远端应用镜像拉取（假定已用 tar 灌入）
#   --dry-run            只打印步骤，不实际改动
#   --check              启动后等待并打印健康状态
#   -h | --help          帮助
#
# 前置：
#   - 本地已装 docker + compose 插件（脚本在「本地」运行，操作「远端」daemon）。
#   - 远端 172.17.5.96 已装 Docker Engine，bonc 用户可运行 docker
#     （docker 组或 sudo）。
#   - 若用密码登录（非密钥），本地需装 sshpass；脚本会用临时 PATH 包装 ssh
#     让 docker 的 SSH 调用带上密码。
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
OVERRIDE="docker-compose.prod-external-panweidb.yml"
ENV_FILE="${ROOT_DIR}/.env"
PLATFORM="linux/amd64"
REMOTE_ENV="${REMOTE_ENV:-${SCRIPT_DIR}/remote.env}"

# ── 载入连接环境变量 ─────────────────────────────────────────────────────────
if [[ -f "${REMOTE_ENV}" ]]; then
  set -a; . "${REMOTE_ENV}"; set +a
else
  echo "[error] 未找到连接信息文件: ${REMOTE_ENV}" >&2
  exit 1
fi

REMOTE_HOST="${REMOTE_HOST:-172.17.5.96}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_USER="${REMOTE_USER:-bonc}"
REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"
DOCKER_CONTEXT="${DOCKER_CONTEXT:-mogo-remote}"
REMOTE_USE_SUDO="${REMOTE_USE_SUDO:-0}"

# ── 部署默认值（可被同名环境变量或参数覆盖）─────────────────────────────────
PANWEIDB_HOST="${PANWEIDB_HOST:-172.17.5.145}"
PANWEIDB_PORT="${PANWEIDB_PORT:-17700}"
PANWEIDB_USER="${PANWEIDB_USER:-boncuser}"
PANWEIDB_PASSWORD="${PANWEIDB_PASSWORD:-1qaz!QAZ}"
PANWEIDB_DB="${PANWEIDB_DB:-mogo}"
PANWEIDB_SCHEMA="${PANWEIDB_SCHEMA:-public}"

MOGO_VERSION="${MOGO_VERSION:-}"
MOGO_PLATFORM="${MOGO_PLATFORM:-${PLATFORM}}"
MOGO_PULL_POLICY="${MOGO_PULL_POLICY:-never}"
MOGO_DATA_BACKEND="${MOGO_DATA_BACKEND:-panweidb}"

BASE_IMAGES_DIR="${BASE_IMAGES_DIR:-${ROOT_DIR}/base-images/images/amd64}"
DOCKER_HUB_MIRROR="${DOCKER_HUB_MIRROR:-docker.m.daocloud.io}"
GHCR_MIRROR="${GHCR_MIRROR:-ghcr.nju.edu.cn}"
APP_TAR_DIR="${APP_TAR_DIR:-}"

# ── 命令行开关 ─────────────────────────────────────────────────────────────
DO_LOAD=1
DO_APP_PULL=1
DO_CHECK=0
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-env)       REMOTE_ENV="$2"; shift 2 ;;
    --version)          MOGO_VERSION="$2"; shift 2 ;;
    --app-tar-dir)      APP_TAR_DIR="$2"; shift 2 ;;
    --base-images)      BASE_IMAGES_DIR="$2"; shift 2 ;;
    --docker-hub-mirror) DOCKER_HUB_MIRROR="$2"; shift 2 ;;
    --ghcr-mirror)      GHCR_MIRROR="$2"; shift 2 ;;
    --skip-load)        DO_LOAD=0; shift ;;
    --skip-app-pull)    DO_APP_PULL=0; shift ;;
    --check)            DO_CHECK=1; shift ;;
    --dry-run)          DRY_RUN=1; shift ;;
    -h|--help)          sed -n '1,60p' "${BASH_SOURCE[0]}" | grep -E '^#' | sed 's/^#\{1,2\} //'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# ── 日志 ───────────────────────────────────────────────────────────────────
log()  { printf '\033[0;32m[deploy-remote]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }
run()  { if [[ "${DRY_RUN}" -eq 1 ]]; then log "(dry-run) $*"; else eval "$@"; fi; }

# 没有显式版本时，从 .env 读 MOGO_VERSION，再退到 latest。
if [[ -z "${MOGO_VERSION}" && -f "${ENV_FILE}" ]]; then
  MOGO_VERSION="$(grep -E '^[[:space:]]*MOGO_VERSION=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- | tr -d '\r')"
fi
MOGO_VERSION="${MOGO_VERSION:-latest}"

# ── 前置检查 ───────────────────────────────────────────────────────────────
if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
  err "未找到 docker（DOCKER_BIN=${DOCKER_BIN}）。"; exit 1
fi
if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  err "docker compose 插件不可用。"; exit 1
fi

# 真实 ssh 二进制路径（供 sshpass 包装脚本调用）。
REAL_SSH="$(command -v ssh || true)"
[[ -z "${REAL_SSH}" ]] && { err "未找到 ssh 客户端。"; exit 1; }

SSHPASS_BIN="$(command -v sshpass || true)"
if [[ -n "${REMOTE_PASSWORD}" ]]; then
  if [[ -z "${SSHPASS_BIN}" ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      warn "已配置 REMOTE_PASSWORD 但本地未找到 sshpass；dry-run 继续，真实部署前请安装（apt-get install sshpass）。"
    else
      err "已配置 REMOTE_PASSWORD 但未找到 sshpass。"
      err "请安装 sshpass（如 apt-get install sshpass / brew install hudochenkov/sshpass/sshpass），"
      err "或改用 SSH 密钥登录并清空 REMOTE_PASSWORD。"
      exit 1
    fi
  fi
  # 临时目录放一个 ssh 包装脚本：docker 调用 ssh 时自动带上密码。
  # 仅在 sshpass 可用时创建；dry-run 且缺 sshpass 时跳过（不会真正连接）。
  if [[ -n "${SSHPASS_BIN}" ]]; then
  SSH_WRAP_DIR="$(mktemp -d)"
  cat > "${SSH_WRAP_DIR}/ssh" <<WRAP
#!/usr/bin/env bash
exec "${SSHPASS_BIN}" -p "\${REMOTE_PASSWORD}" "${REAL_SSH}" \\
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "\$@"
WRAP
  chmod +x "${SSH_WRAP_DIR}/ssh"
  export PATH="${SSH_WRAP_DIR}:${PATH}"
  log "使用 sshpass 走密码登录（REMOTE_PASSWORD 已生效）。"
  fi
fi

# ── 创建 / 复用 docker context ─────────────────────────────────────────────
ENDPOINT="ssh://${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
# 确保后续命令都走本 context，而不是任何 DOCKER_HOST。
unset DOCKER_HOST
DC=("${DOCKER_BIN}" --context "${DOCKER_CONTEXT}")

if "${DOCKER_BIN}" context inspect "${DOCKER_CONTEXT}" >/dev/null 2>&1; then
  log "docker context 已存在，重建以刷新端点: ${DOCKER_CONTEXT}"
  run "${DOCKER_BIN} context rm -f ${DOCKER_CONTEXT}"
fi
log "创建 docker context: ${DOCKER_CONTEXT} -> ${ENDPOINT}"
run "${DOCKER_BIN} context create ${DOCKER_CONTEXT} --docker host=${ENDPOINT}"
run "${DOCKER_BIN} context use ${DOCKER_CONTEXT}"

# ── 验证到远端 daemon 的连通性 ─────────────────────────────────────────────
log "验证远端 daemon 连通性（docker --context ${DOCKER_CONTEXT} ps）..."
if [[ "${DRY_RUN}" -eq 0 ]]; then
  if ! "${DC[@]}" ps >/dev/null 2>&1; then
    err "无法连到远端 daemon：${ENDPOINT}"
    err "请确认：① 远端 docker 已启动；② ${REMOTE_USER} 可执行 docker"
    [[ "${REMOTE_USE_SUDO}" -eq 1 ]] && err "   （REMOTE_USE_SUDO=1，需在远端把 bonc 加入 docker 组或配置 NOPASSWD sudo）"
    err "③ 密码/密钥正确；④ 本地已装 sshpass（密码方式）。"
    exit 1
  fi
  log "  ✓ 远端 daemon 可达。"
else
  log "(dry-run) 跳过连通性检查"
fi

# ── 导出离线部署所需环境变量（写入本地 .env，供远端 compose 读取）──────────
export MOGO_PROFILE="${MOGO_PROFILE:-prod}"
export MOGO_PLATFORM="${MOGO_PLATFORM}"
export MOGO_PULL_POLICY="${MOGO_PULL_POLICY}"
export MOGO_DATA_BACKEND="${MOGO_DATA_BACKEND}"
export MOGO_VERSION="${MOGO_VERSION}"
export PANWEIDB_HOST PANWEIDB_PORT PANWEIDB_USER PANWEIDB_PASSWORD PANWEIDB_DB PANWEIDB_SCHEMA
export MOGO_REDIS_URL="${MOGO_REDIS_URL:-redis://redis:6379/0}"
export MOGO_KERNEL_REDIS_URL="${MOGO_KERNEL_REDIS_URL:-redis://redis:6379/1}"

log "目标架构        : ${MOGO_PLATFORM}（远端 daemon）"
log "应用镜像版本    : ${MOGO_VERSION}"
log "数据后端        : ${MOGO_DATA_BACKEND}（外部 PanWeiDB @ ${PANWEIDB_HOST}:${PANWEIDB_PORT}）"
log "Redis           : 栈内（远端）"
log "Mongo/PanWeiDB  : 容器已停用"
log "远端 Docker 主机: ${ENDPOINT}（context=${DOCKER_CONTEXT}）"

set_env_key() {
  local key="$1" value="$2" file="${ENV_FILE}"
  touch "${file}"
  if grep -q "^[[:space:]]*${key}=" "${file}"; then
    sed -i.bak -E "s|^[[:space:]]*${key}=.*|${key}=${value}|" "${file}" && rm -f "${file}.bak"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  fi
}
log "合并部署变量到 ${ENV_FILE} ..."
run "set_env_key MOGO_PROFILE prod"
run "set_env_key MOGO_PLATFORM ${MOGO_PLATFORM}"
run "set_env_key MOGO_PULL_POLICY ${MOGO_PULL_POLICY}"
run "set_env_key MOGO_DATA_BACKEND ${MOGO_DATA_BACKEND}"
run "set_env_key MOGO_VERSION ${MOGO_VERSION}"
run "set_env_key MOGO_USE_EXTERNAL_DB 0"
run "set_env_key PANWEIDB_HOST ${PANWEIDB_HOST}"
run "set_env_key PANWEIDB_PORT ${PANWEIDB_PORT}"
run "set_env_key PANWEIDB_USER ${PANWEIDB_USER}"
run "set_env_key PANWEIDB_PASSWORD ${PANWEIDB_PASSWORD}"
run "set_env_key PANWEIDB_DB ${PANWEIDB_DB}"
run "set_env_key PANWEIDB_SCHEMA ${PANWEIDB_SCHEMA}"
run "set_env_key MOGO_REDIS_URL ${MOGO_REDIS_URL}"
run "set_env_key MOGO_KERNEL_REDIS_URL ${MOGO_KERNEL_REDIS_URL}"

# ── 镜像导入到「远端 daemon」────────────────────────────────────────────────
remote_image_present() { "${DC[@]}" image inspect "$1" >/dev/null 2>&1; }

resolve_mirror() {
  local imgref="$1" first="${1%%/*}"
  if [[ "$imgref" != */* ]]; then printf '%s/library/%s' "${DOCKER_HUB_MIRROR}" "${imgref}"; return; fi
  case "$first" in
    *.*|localhost*|*:*) case "$first" in
        ghcr.io) printf '%s/%s' "${GHCR_MIRROR}" "${imgref#ghcr.io/}" ;;
        *)       printf '%s' "${imgref}" ;;
      esac ;;
    *) printf '%s/%s' "${DOCKER_HUB_MIRROR}" "${imgref}" ;;
  esac
}

load_tar_dir() {
  local dir="$1" label="$2"
  if [[ ! -d "${dir}" ]]; then warn "  ${label} 目录不存在: ${dir}（跳过）"; return; fi
  shopt -s nullglob; local files=("${dir}"/*.tar); shopt -u nullglob
  if [[ ${#files[@]} -eq 0 ]]; then warn "  ${label} 下没有 .tar 镜像包（跳过）"; return; fi
  for f in "${files[@]}"; do
    log "  ↳ load 到远端: $(basename "$f")"
    run "${DC[@]} load -i \"$f\"" || warn "  导入失败: $f"
  done
}

log "步骤 1/3：base-images 离线镜像包灌入远端 daemon ..."
if [[ "${DO_LOAD}" -eq 1 ]]; then
  load_tar_dir "${BASE_IMAGES_DIR}" "base-images"
else
  log "  （--skip-load 已跳过）"
fi

log "步骤 2/3：应用镜像 tar 包灌入远端 daemon ..."
if [[ -n "${APP_TAR_DIR}" ]]; then
  load_tar_dir "${APP_TAR_DIR}" "app-tar-dir"
fi

# ── 远端 daemon 直接补齐缺失的应用镜像 ─────────────────────────────────────
get_required_images() {
  "${DOCKER_BIN}" compose -f docker-compose.yml -f "${OVERRIDE}" config 2>/dev/null \
    | awk '
        /^services:/ { in_sv=1; next }
        /^volumes:/ || /^networks:/ { in_sv=0 }
        in_sv && /^  [a-zA-Z0-9_.-]+:/ { svc=$1; sub(/:$/,"",svc); cur=svc }
        in_sv && /^[[:space:]]+profiles:/ { has_profile[cur]=1 }
        in_sv && /^[[:space:]]+image:/ { img=$2; if (!(cur in has_profile)) print img }
      ' | sort -u
}

provision_remote_image() {
  # 注意：在 set -u 下，本函数内 imgref 这类局部变量在“命令替换 + 失败命令的
  # if/fi”之后会被 nounset 误报为未绑定（镜像名其实有值，关闭 -u 即可验证）。
  # 因此所有引用统一用 ${var:-} 兜底，既避免误报，又在真正为空时安全降级。
  local imgref="${1:-}"
  local mref=""
  local ok=0
  if [[ -z "${imgref:-}" ]]; then warn "provision_remote_image 收到空镜像引用，跳过。"; return 1; fi
  if remote_image_present "${imgref:-}"; then log "  ✓ 远端已存在: ${imgref:-}"; return 0; fi
  mref="$(resolve_mirror "${imgref:-}")"
  if [[ -n "${mref:-}" && "${mref:-}" != "${imgref:-}" ]]; then
    log "  ↳ 远端国内镜像: ${mref:-}"
    if "${DC[@]}" pull --platform "${MOGO_PLATFORM}" "${mref:-}" >/dev/null 2>&1 && \
       "${DC[@]}" tag "${mref:-}" "${imgref:-}" >/dev/null 2>&1; then
      log "  ✓ 已从国内镜像灌入远端: ${imgref:-}"; return 0
    fi
    warn "  远端国内镜像拉取失败: ${mref:-}"
  fi
  log "  ↳ 远端上游官方源: ${imgref:-}"
  if "${DC[@]}" pull --platform "${MOGO_PLATFORM}" "${imgref:-}" >/dev/null 2>&1; then
    log "  ✓ 已从上游灌入远端: ${imgref:-}"; return 0
  fi
  warn "  远端无法获取镜像: ${imgref:-}（请改用 --app-tar-dir 灌入离线包）"
  return 1
}

if [[ "${DO_APP_PULL}" -eq 1 ]]; then
  log "步骤 3/3：远端补齐缺失镜像（国内镜像站 → 上游官方源）..."
  imgs="$(get_required_images)"
  [[ -z "${imgs}" ]] && { err "无法从 compose 解析所需镜像列表。"; exit 1; }
  # 用 here-string 而非管道，使 while 在当前 shell 执行（避免管道子 shell 下
  # set -u 把函数局部变量误判为未绑定的怪异行为）。
  while IFS= read -r img; do
    [[ -n "$img" ]] || continue
    if [[ "${DRY_RUN}" -eq 1 ]]; then log "(dry-run) 处理镜像: $img"
    else provision_remote_image "$img" || true; fi
  done <<< "${imgs}"
else
  log "跳过远端应用镜像拉取（--skip-app-pull），假定镜像已就绪。"
fi

# ── 启动（在远端 daemon 上）────────────────────────────────────────────────
log "在远端启动服务（${OVERRIDE}）..."
run "${DC[@]} compose -f docker-compose.yml -f ${OVERRIDE} up -d"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "dry-run 结束，未实际改动远端。"
  [[ -n "${SSH_WRAP_DIR:-}" ]] && rm -rf "${SSH_WRAP_DIR}"
  exit 0
fi

log "部署完成。若需查看远端容器状态："
log "  docker --context ${DOCKER_CONTEXT} ps"
log "  docker --context ${DOCKER_CONTEXT} compose -f docker-compose.yml -f ${OVERRIDE} ps"

if [[ "${DO_CHECK}" -eq 1 ]]; then
  log "等待远端服务健康（最多 ~5 分钟）..."
  "${DC[@]}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format 'table {{.Service}}\t{{.Status}}' || true
  for i in $(seq 1 30); do
    unhealthy="$("${DC[@]}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk '$2!="healthy" && $2!="" {print $1}')"
    [[ -z "${unhealthy}" ]] && break
    sleep 10
  done
  log "远端服务状态："
  "${DC[@]}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format 'table {{.Service}}\t{{.Status}}' || true
fi

# 清理临时 ssh 包装目录。
[[ -n "${SSH_WRAP_DIR:-}" ]] && rm -rf "${SSH_WRAP_DIR}"
log "完成。"
