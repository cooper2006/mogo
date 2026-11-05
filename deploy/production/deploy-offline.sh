#!/usr/bin/env bash
# =============================================================================
# mogo 生产离线部署脚本
# -----------------------------------------------------------------------------
# 场景：AMD64 生产环境，停用 mongo 与 panweidb 容器，使用「外部 PanWeiDB +
#       栈内 Redis」，全部走离线镜像。
#
# 镜像策略（先本地、后国内镜像）：
#   ① 先从 base-images/images/amd64/*.tar 离线导入；
#   ② 仍缺失的镜像（主要是 ghcr.io/mogoai/* 应用镜像）从国内镜像站拉取，
#      失败再回退到上游官方源。
#
# 与 deploy/cli 的 mogo CLI 互不依赖——本脚本可在只有 docker + 代码仓库的
# 裸生产机上直接运行。它复用仓库约定（读/写项目根目录的 .env，compose 文件
# 优先级与 docker-compose.external.yml 一致）。
#
# 用法：
#   bash deploy/production/deploy-offline.sh [选项]
#
# 选项：
#   --version <tag>        应用镜像版本（默认取 .env 的 MOGO_VERSION，再退到 latest）
#   --base-images <dir>    base-images 目录（默认 <仓库>/base-images/images/amd64）
#   --docker-hub-mirror <host>   Docker Hub 镜像站（默认 docker.m.daocloud.io）
#   --ghcr-mirror <host>   ghcr.io 镜像站（默认 ghcr.nju.edu.cn）
#   --skip-load            跳过 base-images/*.tar 导入（镜像已导入时省时间）
#   --skip-pull            跳过镜像获取（仅启动，假定镜像已就绪）
#   --dry-run              只打印将要执行的步骤，不实际改动
#   --check                启动后等待并打印各服务健康状态
#   -h | --help            显示本帮助
#
# 环境变量（均可被同名环境变量覆盖，优先级高于 .env 与默认值）：
#   PANWEIDB_HOST / PANWEIDB_PORT / PANWEIDB_USER / PANWEIDB_PASSWORD
#   PANWEIDB_DB / PANWEIDB_SCHEMA
#   MOGO_VERSION / MOGO_PLATFORM / MOGO_PULL_POLICY / MOGO_DATA_BACKEND
#   DOCKER_HUB_MIRROR / GHCR_MIRROR / BASE_IMAGES_DIR
# =============================================================================
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
OVERRIDE="docker-compose.prod-external-panweidb.yml"
ENV_FILE="${ROOT_DIR}/.env"
PLATFORM="linux/amd64"

# ── 默认值（可被同名环境变量或命令行参数覆盖）──────────────────────────────
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

# ── 命令行开关 ─────────────────────────────────────────────────────────────
DO_LOAD=1
DO_PULL=1
DO_CHECK=0
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)        MOGO_VERSION="$2"; shift 2 ;;
    --base-images)    BASE_IMAGES_DIR="$2"; shift 2 ;;
    --docker-hub-mirror) DOCKER_HUB_MIRROR="$2"; shift 2 ;;
    --ghcr-mirror)   GHCR_MIRROR="$2"; shift 2 ;;
    --skip-load)     DO_LOAD=0; shift ;;
    --skip-pull)     DO_PULL=0; shift ;;
    --check)         DO_CHECK=1; shift ;;
    --dry-run)       DRY_RUN=1; shift ;;
    -h|--help)       sed -n '1,60p' "${BASH_SOURCE[0]}" | grep -E '^#' | sed 's/^#\{1,2\} //'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# ── 日志 ───────────────────────────────────────────────────────────────────
log()  { printf '\033[0;32m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }
run()  { if [[ "${DRY_RUN}" -eq 1 ]]; then log "(dry-run) $*"; else eval "$@"; fi; }

# 没有显式给版本时，从 .env 读 MOGO_VERSION，再退到 latest。
if [[ -z "${MOGO_VERSION}" && -f "${ENV_FILE}" ]]; then
  MOGO_VERSION="$(grep -E '^[[:space:]]*MOGO_VERSION=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- | tr -d '\r')"
fi
MOGO_VERSION="${MOGO_VERSION:-latest}"

# ── 前置检查 ───────────────────────────────────────────────────────────────
if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
  err "未找到 docker（DOCKER_BIN=${DOCKER_BIN}）。请先安装 Docker Engine 与 compose 插件。"
  exit 1
fi
if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  err "docker compose 插件不可用，请安装 Docker Compose v2。"
  exit 1
fi
if [[ ! -f "${ROOT_DIR}/docker-compose.yml" ]]; then
  err "未在 ${ROOT_DIR} 找到 docker-compose.yml。"
  exit 1
fi
if [[ ! -f "${ROOT_DIR}/${OVERRIDE}" ]]; then
  err "未找到覆盖文件 ${OVERRIDE}（应与 docker-compose.yml 同目录）。"
  exit 1
fi

# ── 把部署所需的变量导出给后续 docker compose（同时约束架构与离线拉取）─────
export MOGO_PROFILE="${MOGO_PROFILE:-prod}"
export MOGO_PLATFORM="${MOGO_PLATFORM}"
export MOGO_PULL_POLICY="${MOGO_PULL_POLICY}"
export MOGO_DATA_BACKEND="${MOGO_DATA_BACKEND}"
export MOGO_VERSION="${MOGO_VERSION}"
export PANWEIDB_HOST PANWEIDB_PORT PANWEIDB_USER PANWEIDB_PASSWORD PANWEIDB_DB PANWEIDB_SCHEMA
export MOGO_REDIS_URL="${MOGO_REDIS_URL:-redis://redis:6379/0}"
export MOGO_KERNEL_REDIS_URL="${MOGO_KERNEL_REDIS_URL:-redis://redis:6379/1}"

log "目标架构        : ${MOGO_PLATFORM}"
log "应用镜像版本    : ${MOGO_VERSION}"
log "数据后端        : ${MOGO_DATA_BACKEND}（外部 PanWeiDB）"
log "外部 PanWeiDB   : ${PANWEIDB_USER}@${PANWEIDB_HOST}:${PANWEIDB_PORT}/${PANWEIDB_DB} (schema=${PANWEIDB_SCHEMA})"
log "Redis           : 栈内（${MOGO_REDIS_URL} / ${MOGO_KERNEL_REDIS_URL}）"
log "Mongo/PanWeiDB  : 容器已停用（外部实例接管）"
log "base-images 目录: ${BASE_IMAGES_DIR}"
log "Docker Hub 镜像 : ${DOCKER_HUB_MIRROR} | ghcr.io 镜像 : ${GHCR_MIRROR}"

# ── 写入/更新 .env 中的部署变量（幂等，不破坏既有其它配置）────────────────
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

# ── 镜像获取 ───────────────────────────────────────────────────────────────
image_present() {
  "${DOCKER_BIN}" image inspect "$1" >/dev/null 2>&1
}

# 把镜像引用解析为「国内镜像站地址」（返回空表示无需走镜像站，直接用原引用）。
resolve_mirror() {
  local ref="$1" first="${1%%/*}"
  if [[ "$ref" != */* ]]; then
    # Docker Hub 官方库镜像（单段名）
    printf '%s/library/%s' "${DOCKER_HUB_MIRROR}" "${ref}"
    return
  fi
  case "$first" in
    *.*|localhost*|*:*)
      # 带注册中心主机名：按具体主机选镜像站
      case "$first" in
        ghcr.io) printf '%s/%s' "${GHCR_MIRROR}" "${ref#ghcr.io/}" ;;
        *)       printf '%s' "${ref}" ;;   # 其它注册中心：无镜像站规则，原样返回
      esac
      ;;
    *)
      # Docker Hub 用户/仓库（两段、首段无点）
      printf '%s/%s' "${DOCKER_HUB_MIRROR}" "${ref}"
      ;;
  esac
}

provision_image() {
  local ref="$1" mref
  if image_present "$ref"; then
    log "  ✓ 已存在(本地): $ref"
    return 0
  fi
  mref="$(resolve_mirror "$ref")"
  if [[ -n "$mref" && "$mref" != "$ref" ]]; then
    log "  ↳ 国内镜像: $mref"
    if "${DOCKER_BIN}" pull "$mref" >/dev/null 2>&1 && "${DOCKER_BIN}" tag "$mref" "$ref" >/dev/null 2>&1; then
      log "  ✓ 已从国内镜像导入: $ref"
      return 0
    fi
    warn "  国内镜像拉取失败: $mref"
  fi
  log "  ↳ 上游官方源: $ref"
  if "${DOCKER_BIN}" pull "$ref" >/dev/null 2>&1; then
    log "  ✓ 已从上游拉取: $ref"
    return 0
  fi
  err "  无法获取镜像: $ref（base-images、国内镜像、上游均失败）"
  return 1
}

# 从合并后的 compose 配置里取出「默认会启动」的服务所用镜像
# （排除带 profiles 的服务，即 mongo[dev] 与 panweidb[panweidb,test] 等）。
get_required_images() {
  "${DOCKER_BIN}" compose -f docker-compose.yml -f "${OVERRIDE}" config 2>/dev/null \
    | awk '
        /^services:/ { in_sv=1; next }
        /^volumes:/ || /^networks:/ { in_sv=0 }
        in_sv && /^  [a-zA-Z0-9_.-]+:/ {
          svc=$1; sub(/:$/,"",svc); cur=svc
        }
        in_sv && /^[[:space:]]+profiles:/ { has_profile[cur]=1 }
        in_sv && /^[[:space:]]+image:/ {
          img=$2
          if (!(cur in has_profile)) print img
        }
      ' | sort -u
}

if [[ "${DO_PULL}" -eq 1 ]]; then
  if [[ "${DO_LOAD}" -eq 1 ]]; then
    log "步骤 1/2：从 base-images 离线导入镜像包 ..."
    if [[ -d "${BASE_IMAGES_DIR}" ]]; then
      shopt -s nullglob
      files=("${BASE_IMAGES_DIR}"/*.tar)
      shopt -u nullglob
      if [[ ${#files[@]} -eq 0 ]]; then
        warn "  ${BASE_IMAGES_DIR} 下没有 .tar 镜像包，跳过。"
      else
        for f in "${files[@]}"; do
          log "  ↳ 导入 $(basename "$f")"
          run "${DOCKER_BIN} load -i \"$f\"" || warn "  导入失败: $f"
        done
      fi
    else
      warn "  base-images 目录不存在: ${BASE_IMAGES_DIR}（跳过离线导入）"
    fi
  else
    log "步骤 1/2：跳过 base-images 导入（--skip-load）"
  fi

  log "步骤 2/2：补齐缺失镜像（国内镜像站 → 上游官方源）..."
  imgs="$(get_required_images)"
  if [[ -z "${imgs}" ]]; then
    err "无法从 compose 配置解析出所需镜像列表，请检查 compose 文件。"
    exit 1
  fi
  echo "${imgs}" | while IFS= read -r img; do
    [[ -n "$img" ]] || continue
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "(dry-run) 处理镜像: $img"
    else
      provision_image "$img" || true
    fi
  done
else
  log "跳过镜像获取（--skip-pull），假定镜像已就绪。"
fi

# ── 启动 ───────────────────────────────────────────────────────────────────
log "启动服务（${OVERRIDE}）..."
run "${DOCKER_BIN} compose -f docker-compose.yml -f ${OVERRIDE} up -d"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "dry-run 结束，未实际启动。"
  exit 0
fi

# ── 可选：等待并打印健康状态 ───────────────────────────────────────────────
if [[ "${DO_CHECK}" -eq 1 ]]; then
  log "等待服务健康（最多 ~5 分钟）..."
  "${DOCKER_BIN}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format 'table {{.Service}}\t{{.Status}}' || true
  for i in $(seq 1 30); do
    unhealthy="$("${DOCKER_BIN}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk '$2!="healthy" && $2!="" {print $1}')"
    [[ -z "${unhealthy}" ]] && break
    sleep 10
  done
  log "服务状态："
  "${DOCKER_BIN}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format 'table {{.Service}}\t{{.Status}}' || true
fi

log "完成。访问入口：http://localhost:${MOGO_PORT:-3000}/admin/setup"
