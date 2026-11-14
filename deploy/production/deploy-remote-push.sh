#!/usr/bin/env bash
# =============================================================================
# mogo 远程部署 —— 推送「本地已构建镜像」到离线远端 daemon
# -----------------------------------------------------------------------------
# 前置：应用镜像已在本机 Kiri（docker context=kiri）按 AMD64 + 当前代码
#       离线构建完成（见 docker-compose.build.yml + base-images/ 离线依赖包）。
# 本脚本只负责：
#   1. 建立/复用 docker context（ssh://bonc@172.17.5.96:22）；
#   2. 按内容指纹（RootFS.Layers）比对后推送应用/基础镜像（小镜像 save|load，大镜像 tar+scp+load）；
#   3. 用 docker-compose.prod-external-panweidb.yml 覆盖在远端 up -d
#      （停用 mongo / panweidb，保留栈内 redis / weaviate，连外部 PanWeiDB）。
#
# 与 deploy-remote.sh 的区别：镜像不从 registry 拉取，而是直接用本机已构建的
# 本地镜像推送（适合“远端离线、镜像在本地”的场景）。
#
# 用法：
#   bash deploy/production/deploy-remote-push.sh [--check] [--dry-run] [--force-push]
#                                               [--images-only] [--remote-env <file>]
#
# 开关：
#   --check        启动后等待就绪、打印状态，并校验运行容器是否用的是当前 tag 镜像
#   --force-push   远端同名 tag 与本地内容不一致时强制覆盖（默认只告警并跳过）
#   --images-only  只推镜像：不 scp 网关配置、不改写 .env、不 up、不 check、不清理
#                  （远端有手工维护的 compose 补丁、不希望被 up 覆盖时用这一档）
#   --dry-run      只打印将执行的操作，不推送 / 不 scp / 不启动 / 不清理
#   --remote-env   指定连接信息文件（默认 deploy/production/remote.env）
#
# 注意：脚本按内容指纹（RootFS.Layers，取不到层时退回镜像 ID）判断是否需要推送，
#       不再只看远端有没有同名 tag，也不用跨 image store 不可比的 .Id 直接判等。
#       `:latest` 已存在但内容不同 = 代码没上线，必须加 --force-push 或换版本化 tag。
#       大于 PUSH_STREAM_MAX_MB（默认 200）的镜像自动改用 tar + scp + 远端 docker load，
#       避免 save|load 长管道在慢速/不稳链路上 broken pipe。
#
# 前置：本地 docker + compose 插件 + (密码方式) sshpass；远端 Docker Engine 可达。
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
LOCAL_CONTEXT="${LOCAL_CONTEXT:-kiri}"
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

# ── 部署默认值 ──────────────────────────────────────────────────────────────
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
MOGO_REDIS_URL="${MOGO_REDIS_URL:-redis://redis:6379/0}"
MOGO_KERNEL_REDIS_URL="${MOGO_KERNEL_REDIS_URL:-redis://redis:6379/1}"

# ── 命令行开关 ─────────────────────────────────────────────────────────────
DO_CHECK=0
DRY_RUN=0
FORCE_PUSH=0
IMAGES_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-env) REMOTE_ENV="$2"; shift 2 ;;
    --check)      DO_CHECK=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --force-push) FORCE_PUSH=1; shift ;;
    --images-only) IMAGES_ONLY=1; shift ;;
    -h|--help)    sed -n '1,40p' "${BASH_SOURCE[0]}" | grep -E '^#' | sed 's/^#\{1,2\} //'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# ── 日志 ───────────────────────────────────────────────────────────────────
log()  { printf '\033[0;32m[push]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }
run()  { if [[ "${DRY_RUN}" -eq 1 ]]; then log "(dry-run) $*"; else eval "$@"; fi; }

if [[ -z "${MOGO_VERSION:-}" && -f "${ENV_FILE}" ]]; then
  # 注意：`set -o pipefail` 下 grep 无匹配会返回 1，令整个赋值失败并以 1 退出
  # （脚本静默终止、不打印任何错误）。.env 里 MOGO_VERSION 常被注释掉，故用 `|| true` 兜底。
  MOGO_VERSION="$(grep -E '^[[:space:]]*MOGO_VERSION=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- | tr -d '\r' || true)"
fi
MOGO_VERSION="${MOGO_VERSION:-latest}"

# ── 前置检查 ───────────────────────────────────────────────────────────────
if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
  err "未找到 docker（DOCKER_BIN=${DOCKER_BIN}）。"; exit 1
fi
if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  err "docker compose 插件不可用。"; exit 1
fi
REAL_SSH="$(command -v ssh || true)"
[[ -z "${REAL_SSH:-}" ]] && { err "未找到 ssh 客户端。"; exit 1; }

SSHPASS_BIN="$(command -v sshpass || true)"
if [[ -n "${REMOTE_PASSWORD:-}" ]]; then
  if [[ -z "${SSHPASS_BIN:-}" ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      warn "已配置 REMOTE_PASSWORD 但本地未找到 sshpass；dry-run 继续，真实部署前请安装 sshpass。"
    else
      err "已配置 REMOTE_PASSWORD 但未找到 sshpass。请安装 sshpass 或改用 SSH 密钥登录并清空 REMOTE_PASSWORD。"; exit 1
    fi
  fi
  if [[ -n "${SSHPASS_BIN:-}" ]]; then
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
unset DOCKER_HOST
DC=("${DOCKER_BIN}" --context "${DOCKER_CONTEXT}")
LOCAL_DC=("${DOCKER_BIN}" --context "${LOCAL_CONTEXT}")

if "${DOCKER_BIN}" context inspect "${DOCKER_CONTEXT}" >/dev/null 2>&1; then
  log "docker context 已存在，重建以刷新端点: ${DOCKER_CONTEXT}"
  run "${DOCKER_BIN} context rm -f ${DOCKER_CONTEXT}"
fi
log "创建 docker context: ${DOCKER_CONTEXT} -> ${ENDPOINT}"
run "${DOCKER_BIN} context create ${DOCKER_CONTEXT} --docker host=${ENDPOINT}"
run "${DOCKER_BIN} context use ${DOCKER_CONTEXT}"

# ── 验证远端 daemon 连通性 ─────────────────────────────────────────────────
log "验证远端 daemon 连通性（docker --context ${DOCKER_CONTEXT} ps）..."
if [[ "${DRY_RUN}" -eq 0 ]]; then
  if ! "${DC[@]}" ps >/dev/null 2>&1; then
    err "无法连到远端 daemon：${ENDPOINT}"
    err "请确认：① 远端 docker 已启动；② ${REMOTE_USER} 可执行 docker；③ 密码/密钥正确；④ 本地已装 sshpass（密码方式）。"
    exit 1
  fi
  log "  ✓ 远端 daemon 可达。"
else
  log "(dry-run) 跳过连通性检查"
fi

# ── 导出部署环境变量到本地 .env（供远端 compose 读取）──────────────────────
export MOGO_PROFILE="${MOGO_PROFILE:-prod}"
export MOGO_PLATFORM="${MOGO_PLATFORM}"
export MOGO_PULL_POLICY="${MOGO_PULL_POLICY}"
export MOGO_DATA_BACKEND="${MOGO_DATA_BACKEND}"
export MOGO_VERSION="${MOGO_VERSION}"
export PANWEIDB_HOST PANWEIDB_PORT PANWEIDB_USER PANWEIDB_PASSWORD PANWEIDB_DB PANWEIDB_SCHEMA
export MOGO_REDIS_URL MOGO_KERNEL_REDIS_URL

log "目标架构        : ${MOGO_PLATFORM}（远端 daemon）"
log "应用镜像版本    : ${MOGO_VERSION}"
log "强制覆盖推送    : $([[ "${FORCE_PUSH}" -eq 1 ]] && echo '是（--force-push）' || echo '否（内容不同只告警）')"
log "数据后端        : ${MOGO_DATA_BACKEND}（外部 PanWeiDB @ ${PANWEIDB_HOST}:${PANWEIDB_PORT}）"
log "Redis           : 栈内（远端）"
log "Mongo/PanWeiDB  : 容器已停用"
log "本地镜像源      : docker context=${LOCAL_CONTEXT}（amd64，离线构建）"
log "远端 Docker 主机: ${ENDPOINT}（context=${DOCKER_CONTEXT}）"

set_env_key() {
  local key="${1:-}" value="${2:-}" file="${ENV_FILE}"
  # --images-only 不执行 up，无需把部署变量写进本地 .env；否则会把 dev 的
  # MOGO_PLATFORM / MOGO_DATA_BACKEND 悄悄翻成生产口径，影响本地 arm64 栈。
  if [[ "${IMAGES_ONLY}" -eq 1 ]]; then return 0; fi
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
# 密码不经过 run()：run 在 dry-run 下会把整条命令（含明文密码）打到日志。
if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "(dry-run) set_env_key PANWEIDB_PASSWORD <hidden>"
else
  set_env_key PANWEIDB_PASSWORD "${PANWEIDB_PASSWORD}"
fi
run "set_env_key PANWEIDB_DB ${PANWEIDB_DB}"
run "set_env_key PANWEIDB_SCHEMA ${PANWEIDB_SCHEMA}"
run "set_env_key MOGO_REDIS_URL ${MOGO_REDIS_URL}"
run "set_env_key MOGO_KERNEL_REDIS_URL ${MOGO_KERNEL_REDIS_URL}"

# ── 镜像清单：应用（本地 kiri 已构建） + 运行时基础镜像（规范名）────────
# 应用镜像（ghcr.io/mogoai/*:${MOGO_VERSION}）
APP_IMAGES=(chat-api document-parser dsh-runtime-host gateway admin-api admin-web user-web)
# 运行时基础镜像（compose 默认规范名；已在 kiri retag 为 amd64）
BASE_IMAGES=(alpine:3.21 nginx:1.31.5-alpine3.24-slim redis:7.4.2-alpine semitechnologies/weaviate:1.25.7)

# ── 推送：内容感知 + 稳定传输（2026-11-05 事故后加固）─────────────────────
# 旧逻辑只看「远端有没有同名 tag」，:latest 一动不动就永远跳过，导致代码更新后
# 脚本显示成功、线上仍是旧镜像。现在改为比较内容指纹。
# 指纹用 RootFS.Layers 而不是 .Id：本地 Kiri 是 containerd/OCI image store，
# 远端 Docker Engine 是 classic graph driver，同一份内容两边 .Id 不同，只比 .Id
# 会让每次 amd64 部署都误报「内容不同/推送失败」，并诱发重复全量传输。
# [push-image-guard:begin] 本段可被 deploy/tests/test_deploy_push_guard.py 独立提取单测
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
REMOTE_SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_DEPLOY_DIR="/home/${REMOTE_USER}/mogo-deploy"
SUDO_PREFIX=""
if [[ "${REMOTE_USE_SUDO}" == "1" ]]; then SUDO_PREFIX="sudo "; fi
PUSH_STREAM_MAX_MB="${PUSH_STREAM_MAX_MB:-200}"
PUSH_KEEP_TARS="${PUSH_KEEP_TARS:-0}"
PUSH_TMP_DIR="${PUSH_TMP_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/mogo-push-images.XXXXXX")}"
trap 'if [[ "${PUSH_KEEP_TARS}" != "1" ]]; then rm -rf "${PUSH_TMP_DIR}"; fi' EXIT

ssh_run() {
  if [[ -n "${SSHPASS_BIN:-}" ]]; then
    "${SSHPASS_BIN}" -p "${REMOTE_PASSWORD}" ssh "${SSH_OPTS[@]}" "$@"
  else
    ssh "${SSH_OPTS[@]}" "$@"
  fi
}
scp_run() {
  if [[ -n "${SSHPASS_BIN:-}" ]]; then
    "${SSHPASS_BIN}" -p "${REMOTE_PASSWORD}" scp "${SSH_OPTS[@]}" "$@"
  else
    scp "${SSH_OPTS[@]}" "$@"
  fi
}

image_id_local()  { "${LOCAL_DC[@]}" image inspect "${1:-}" --format '{{.Id}}' 2>/dev/null || true; }
image_id_remote() { "${DC[@]}" image inspect "${1:-}" --format '{{.Id}}' 2>/dev/null || true; }
image_layers_local()  { "${LOCAL_DC[@]}" image inspect "${1:-}" --format '{{.RootFS.Layers}}' 2>/dev/null || true; }
image_layers_remote() { "${DC[@]}" image inspect "${1:-}" --format '{{.RootFS.Layers}}' 2>/dev/null || true; }

# 层列表可能带方括号、换行或多余空白，统一成逗号分隔的摘要串再比较。
normalize_fingerprint() {
  printf '%s' "${1:-}" | tr -d '[]()' | tr -s '[:space:]' ',' | sed 's/^,//; s/,$//'
}

# 内容指纹 = RootFS.Layers；两端都能给出层列表时比层，否则一起退回 .Id。
# 必须「同一口径同时用于两端」：一边比层、一边比 ID 必然判成不一致，
# 会造成和旧版按 .Id 判等同样的假失败（误报 + 无谓的全量重传）。
# 结果写入 FP_LOCAL / FP_REMOTE / FP_KIND（layers|id）。
resolve_fingerprints() {
  local imgref="${1:-}" ll="" rl=""
  ll="$(normalize_fingerprint "$(image_layers_local "${imgref}")")"
  rl="$(normalize_fingerprint "$(image_layers_remote "${imgref}")")"
  if [[ -n "${ll}" && -n "${rl}" ]]; then
    FP_KIND="layers"; FP_LOCAL="${ll}"; FP_REMOTE="${rl}"
    return 0
  fi
  FP_KIND="id"
  FP_LOCAL="$(image_id_local "${imgref}")"
  FP_REMOTE="$(image_id_remote "${imgref}")"
}

# 小镜像走 save|load 管道；超过阈值改走「本地 tar → scp → 远端本地 docker load」。
# 实测 VPN 链路约 0.8MB/s，4GB 镜像经 SSH 管道 2 分钟即 broken pipe，还会打断 VPN。
transfer_image() {
  local imgref="${1:-}" size_mb=""
  size_mb="$("${LOCAL_DC[@]}" image inspect "${imgref}" --format '{{.Size}}' 2>/dev/null \
    | awk '{printf "%d", $1/1024/1024}' || true)"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "  (dry-run) 将推送 ${imgref}（约 ${size_mb:-未知}MB）"
    return 0
  fi
  if [[ -n "${size_mb}" && "${size_mb}" -le "${PUSH_STREAM_MAX_MB}" ]]; then
    log "  ↳ 推送（save|load，${size_mb}MB，amd64）: ${imgref}"
    "${LOCAL_DC[@]}" save "${imgref}" | "${DC[@]}" load
  else
    transfer_image_via_tar "${imgref}" "${size_mb:-未知}"
  fi
}

transfer_image_via_tar() {
  local imgref="${1:-}" size_mb="${2:-未知}"
  local tag local_tar remote_dir remote_tar started elapsed want got
  # 文件名带上镜像 ID，避免同名 tag 换内容后复用了旧 tar。
  tag="$(printf '%s' "${imgref}" | tr '/:@.' '____')-$(image_id_local "${imgref}" | cut -c8-19)"
  local_tar="${PUSH_TMP_DIR}/${tag}.tar"
  remote_dir="${REMOTE_DEPLOY_DIR}/images"
  remote_tar="${remote_dir}/${tag}.tar"
  log "  ↳ 大镜像（${size_mb}MB）改用 tar + scp + 远端 docker load（避免长管道中断）"
  if [[ ! -s "${local_tar}" ]]; then
    log "     本地导出 ${imgref} ..."
    "${LOCAL_DC[@]}" save "${imgref}" -o "${local_tar}" || { warn "  ✗ 本地导出失败: ${imgref}"; return 1; }
  fi
  ssh_run "${REMOTE_SSH_TARGET}" "mkdir -p ${remote_dir}" \
    || { warn "  ✗ 远端建目录失败: ${remote_dir}"; return 1; }
  started="$(date +%s)"
  log "     scp 传输中（慢链路可能耗时很久，请勿中断）..."
  scp_run "${local_tar}" "${REMOTE_SSH_TARGET}:${remote_tar}" \
    || { warn "  ✗ scp 失败: ${imgref}"; return 1; }
  elapsed=$(( $(date +%s) - started ))
  log "     传输完成（${elapsed}s），远端 docker load 中 ..."
  ssh_run "${REMOTE_SSH_TARGET}" "${SUDO_PREFIX}docker load -i ${remote_tar}" \
    || { warn "  ✗ 远端 docker load 失败: ${imgref}"; return 1; }
  local ll="" rl=""
  ll="$(normalize_fingerprint "$(image_layers_local "${imgref}")")"
  rl="$(normalize_fingerprint "$(ssh_run "${REMOTE_SSH_TARGET}" \
      "${SUDO_PREFIX}docker image inspect ${imgref} --format '{{.RootFS.Layers}}'" 2>/dev/null \
      | grep -oE 'sha256:[0-9a-f]+' || true)")"
  if [[ -n "${ll}" && -n "${rl}" ]]; then
    want="${ll}"; got="${rl}"
  else
    # 任一端拿不到层列表时两端一起退回镜像 ID，避免混口径造成假不一致。
    want="$(image_id_local "${imgref}")"
    got="$(ssh_run "${REMOTE_SSH_TARGET}" \
      "${SUDO_PREFIX}docker image inspect ${imgref} --format '{{.Id}}'" 2>/dev/null \
      | grep -oE 'sha256:[0-9a-f]+' | tail -n 1 || true)"
  fi
  if [[ -z "${got}" || "${got}" != "${want}" ]]; then
    warn "  ✗ 推送后远端内容指纹不一致（remote=${got:0:19}… , local=${want:0:19}…）: ${imgref}"
    return 1
  fi
  log "     ✓ 远端内容指纹校验通过（${got:0:19}…）"
}

STALE_IMAGES=()
UPDATED_IMAGES=()
FAILED_IMAGES=()
UNVERIFIED_IMAGES=()

push_image() {
  local imgref="${1:-}" local_fp="" remote_fp="" arch=""
  if [[ -z "${imgref}" ]]; then warn "push_image 收到空引用，跳过。"; return 1; fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "  (dry-run) 将按内容指纹校验并按需推送: ${imgref}"
    return 0
  fi
  resolve_fingerprints "${imgref}"
  local_fp="${FP_LOCAL}"
  remote_fp="${FP_REMOTE}"

  if [[ -z "${local_fp}" ]]; then
    if [[ -n "${remote_fp}" ]]; then
      warn "  ⚠ 本地缺失、远端存在，无法校验内容（保留远端）: ${imgref}"
      UNVERIFIED_IMAGES+=("${imgref}")
      return 0
    fi
    warn "  ✗ 本地 kiri 缺失: ${imgref}（请先在本地构建）；远端将尝试 fallback"
    return 1
  fi
  if [[ -n "${remote_fp}" && "${remote_fp}" == "${local_fp}" ]]; then
    log "  ✓ 内容一致（${local_fp:0:19}…）: ${imgref}"
    return 0
  fi

  # 架构安全网：只对真正要推送的镜像做，避免把 arm64 误灌入离线 amd64 远端。
  arch="$("${LOCAL_DC[@]}" inspect "${imgref}" --format '{{.Architecture}}' 2>/dev/null || true)"
  if [[ "${arch}" != "amd64" ]]; then
    warn "  ✗ 本地镜像架构非 amd64（实际=${arch:-未知}）: ${imgref}；跳过推送。"
    warn "    请先用 DOCKER_DEFAULT_PLATFORM=linux/amd64 从源码重新构建该镜像。"
    return 1
  fi

  if [[ -n "${remote_fp}" && "${FORCE_PUSH}" -ne 1 ]]; then
    warn "  ⚠ 远端同名 tag 内容不同（本地 ${local_fp:0:19}… ≠ 远端 ${remote_fp:0:19}…）: ${imgref}"
    warn "    默认跳过，本次部署【不会】更新该镜像的代码；加 --force-push 或换版本化 tag。"
    STALE_IMAGES+=("${imgref}")
    return 0
  fi
  if [[ -n "${remote_fp}" ]]; then
    log "  ↳ --force-push：覆盖远端同名 tag: ${imgref}"
  else
    log "  ↳ 远端缺失，推送: ${imgref}"
  fi
  if transfer_image "${imgref}"; then
    log "  ✓ 已推送并校验: ${imgref}"
    UPDATED_IMAGES+=("${imgref}")
    return 0
  fi
  warn "  ✗ 推送失败: ${imgref}"
  FAILED_IMAGES+=("${imgref}")
  return 1
}

report_push_summary() {
  local img=""
  if [[ ${#STALE_IMAGES[@]} -gt 0 ]]; then
    warn "════════════════════════════════════════════════════════════"
    warn "⚠ 有 ${#STALE_IMAGES[@]} 个镜像『远端与本地内容不同』但本次未推送："
    for img in "${STALE_IMAGES[@]:-}"; do
      if [[ -n "${img}" ]]; then warn "    - ${img}"; fi
    done
    warn "  若这些镜像包含本次代码改动，上线不会生效！"
    warn "  处置：bash deploy/production/deploy-remote-push.sh --force-push --check"
    warn "  或将 .env 的 MOGO_VERSION 改为版本化 tag（如 commit hash）。"
    warn "════════════════════════════════════════════════════════════"
  fi
  if [[ ${#FAILED_IMAGES[@]} -gt 0 ]]; then
    warn "⚠ 推送失败 ${#FAILED_IMAGES[@]} 个："
    for img in "${FAILED_IMAGES[@]:-}"; do
      if [[ -n "${img}" ]]; then warn "    - ${img}"; fi
    done
  fi
  if [[ ${#UPDATED_IMAGES[@]} -gt 0 ]]; then
    log "✓ 本次实际推送/覆盖 ${#UPDATED_IMAGES[@]} 个镜像。"
  fi
}

image_name_for_service() {
  case "${1:-}" in
    document-api|document-worker) printf 'document-parser' ;;
    *) printf '%s' "${1:-}" ;;
  esac
}
APP_SERVICES=(chat-api admin-api document-api document-worker dsh-runtime-host gateway admin-web user-web)

verify_running_images() {
  local svc="" imgref="" want="" cids="" cid="" got="" mismatched=0
  for svc in "${APP_SERVICES[@]:-}"; do
    [[ -n "${svc}" ]] || continue
    imgref="ghcr.io/mogoai/$(image_name_for_service "${svc}"):${MOGO_VERSION}"
    want="$(image_id_remote "${imgref}")"
    [[ -n "${want}" ]] || continue
    cids="$("${DC[@]}" compose -f docker-compose.yml -f "${OVERRIDE}" ps -q "${svc}" 2>/dev/null || true)"
    for cid in ${cids}; do
      [[ -n "${cid}" ]] || continue
      got="$("${DC[@]}" inspect "${cid}" --format '{{.Image}}' 2>/dev/null || true)"
      if [[ -n "${got}" && "${got}" != "${want}" ]]; then
        warn "  ✗ 容器 ${svc} (${cid:0:12}) 仍在旧镜像 ${got:0:19}…（期望 ${want:0:19}…）"
        mismatched=$((mismatched + 1))
      fi
    done
  done
  if [[ "${mismatched}" -eq 0 ]]; then
    log "  ✓ 运行容器与远端 :${MOGO_VERSION} 镜像 ID 一致。"
  else
    warn "有 ${mismatched} 个容器仍在使用旧镜像；可执行："
    warn "  ${DOCKER_BIN} --context ${DOCKER_CONTEXT} compose -f docker-compose.yml -f ${OVERRIDE} up -d --force-recreate <service>"
  fi
}
# [push-image-guard:end]

log "步骤 1/2：推送基础镜像到远端 daemon ..."
for img in "${BASE_IMAGES[@]:-}"; do
  [[ -n "${img:-}" ]] || continue
  push_image "${img}" || true
done

log "步骤 2/2：推送应用镜像（:${MOGO_VERSION}）到远端 daemon ..."
for svc in "${APP_IMAGES[@]:-}"; do
  [[ -n "${svc:-}" ]] || continue
  push_image "ghcr.io/mogoai/${svc}:${MOGO_VERSION}" || true
done
report_push_summary

# ── --images-only：只推镜像，远端服务保持现状 ──────────────────────────────
# 用途：远端有手工维护的 compose 补丁（如 MESC 侧 override）时，up -d 会按本仓库
# 的 compose 文件重建容器、丢掉那些补丁。此档只把镜像灌进远端 daemon，
# 启动时机与方式交给远端维护者。
if [[ "${IMAGES_ONLY}" -eq 1 ]]; then
  log "--images-only：跳过网关配置 scp / 远端 up -d / 就绪与镜像 ID 校验 / 旧镜像清理。"
  if [[ "${DRY_RUN}" -eq 0 && "${FORCE_PUSH}" -ne 1 && ${#STALE_IMAGES[@]} -gt 0 ]]; then
    warn "有 ${#STALE_IMAGES[@]} 个镜像因内容不同且未加 --force-push 而未推送（见上方告警）。"
  fi
  exit 0
fi

# ── 同步网关配置文件到远端宿主机 ──────────────────────────────────────────
# 关键：gateway 的 nginx/canary/tls 配置通过「宿主 bind mount」挂载，而远程部署时
# 本机相对路径会被解析为本机 Mac 路径、远端不存在 -> docker 自动建为目录 -> 挂载失败
# （"not a directory: directory onto file"）。故此处先把配置 scp 到远端可写目录，
# 并在 up 时以远端绝对路径注入，覆盖 .env 里的相对路径（仅本次 compose 调用生效）。
sync_gateway_config() {
  local remote="${REMOTE_SSH_TARGET}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "(dry-run) 跳过网关配置 scp（目标 ${remote}:${REMOTE_DEPLOY_DIR}）"
    return 0
  fi
  log "同步网关配置到远端 ${remote}:${REMOTE_DEPLOY_DIR} ..."
  ssh_run "${remote}" "mkdir -p ${REMOTE_DEPLOY_DIR}/docker ${REMOTE_DEPLOY_DIR}/canary ${REMOTE_DEPLOY_DIR}/tls" \
    || warn "远端建目录失败（请确认 ${REMOTE_USER} 对 HOME 可写）"
  [[ -f deploy/docker/nginx.conf ]] \
    && { scp_run deploy/docker/nginx.conf "${remote}:${REMOTE_DEPLOY_DIR}/docker/nginx.conf" && log "  ✓ nginx.conf" || warn "  ✗ nginx.conf"; }
  [[ -f deploy/canary/nginx-canary.conf ]] \
    && { scp_run deploy/canary/nginx-canary.conf "${remote}:${REMOTE_DEPLOY_DIR}/canary/nginx-canary.conf" && log "  ✓ nginx-canary.conf" || warn "  ✗ nginx-canary.conf"; }
  [[ -d deploy/tls ]] \
    && { scp_run deploy/tls/*.pem "${remote}:${REMOTE_DEPLOY_DIR}/tls/" 2>/dev/null; log "  ✓ tls 证书（如有）"; }
}
sync_gateway_config

# 注入远端绝对路径，覆盖 .env 里的相对路径（export 仅对后续 compose 子进程生效，不污染 .env）
export MOGO_NGINX_CONF="${REMOTE_DEPLOY_DIR}/docker/nginx.conf"
export MOGO_CANARY_NGINX_CONF="${REMOTE_DEPLOY_DIR}/canary/nginx-canary.conf"
export MOGO_TLS_CERTS_DIR="${REMOTE_DEPLOY_DIR}/tls"

# dsh-runtime-host 在 compose 里写的是 ${MOGO_DSH_RUNTIME_HOST_IMAGE:-…:固定 rc tag}，
# .env 里那个 dev 固定 tag 会被带到远端：远端 daemon 只有 :${MOGO_VERSION}，up 直接
# "No such image"。这里把它对齐到本次推送的同一版本（只对本次 compose 调用生效）。
export MOGO_DSH_RUNTIME_HOST_IMAGE="${MOGO_DSH_RUNTIME_HOST_IMAGE:-ghcr.io/mogoai/dsh-runtime-host:${MOGO_VERSION}}"
log "dsh-runtime-host 镜像引用: ${MOGO_DSH_RUNTIME_HOST_IMAGE}"

# ── 远端启动 ───────────────────────────────────────────────────────────────
log "远端启动服务（up -d，覆盖=${OVERRIDE}）..."
run "${DC[@]} compose -f docker-compose.yml -f ${OVERRIDE} up -d"

if [[ "${DO_CHECK}" -eq 1 ]]; then
  log "等待服务就绪（最多约 120s）..."
  for i in $(seq 1 24); do
    sleep 5
    if "${DC[@]}" compose -f docker-compose.yml -f "${OVERRIDE}" ps --format '{{.Name}} {{.State}}' 2>/dev/null | grep -qiE 'restarting|paused'; then
      :
    else
      break
    fi
  done
  log "远端服务状态："
  "${DC[@]}" compose -f docker-compose.yml -f "${OVERRIDE}" ps 2>/dev/null || true
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    log "校验运行容器是否使用当前 :${MOGO_VERSION} 镜像 ..."
    verify_running_images || true
  fi
fi

# ── 部署后清理：仅保留最新版本应用镜像 ──────────────────────────────────────
# 用户要求：7 个应用镜像每次部署后只保留最新一份（:${MOGO_VERSION}），删除旧版本 commit
# tag 与畸形 tag，释放远端磁盘。复用 prune-old-app-images.sh（默认清理远端 context）。
if [[ "${DRY_RUN}" -eq 0 ]]; then
  log "部署后清理远端旧版本应用镜像（仅保留 :${MOGO_VERSION}）..."
  bash "${SCRIPT_DIR}/prune-old-app-images.sh" \
    || warn "旧镜像清理失败（非致命）；可稍后手动执行: bash ${SCRIPT_DIR}/prune-old-app-images.sh"
else
  log "(dry-run) 跳过 prune 调用（真实部署结束时会自动清理）"
fi

if [[ "${DRY_RUN}" -eq 0 && "${FORCE_PUSH}" -ne 1 && ${#STALE_IMAGES[@]} -gt 0 ]]; then
  warn "完成，但有 ${#STALE_IMAGES[@]} 个镜像未更新（见上方 stale 告警）——本次部署未上线这些镜像的新代码。"
else
  log "完成。应用镜像已推送并启动于远端 ${ENDPOINT}（context=${DOCKER_CONTEXT}）。"
fi
