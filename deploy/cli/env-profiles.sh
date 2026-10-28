#!/usr/bin/env bash
# 环境 profile：把 dev / test / prod 三个运行环境固化成 compose profile 组合。
# 由 mogo CLI source，在命令分发前调用 mogo_apply_profile。
#
# 语义（2026-10-28 用户确认）：
#   dev   arm64  + 栈内 mongo 容器
#   test  arm64  + 栈内 panweidb 容器
#   prod  amd64  + 外部 panweidb（栈内不启动任何数据库容器；redis/weaviate 仍在栈内，
#                  与 deploy/production 的 x86 交付模板保持一致）
#
# 架构（2026-10-28 用户确认）：目标架构必须在启动前就确定，不在宿主架构上
# 静默降级。未显式指定 MOGO_PLATFORM 且宿主架构与 profile 目标不一致时，本模块
# 直接拒绝启动并要求先把架构写明；要演练用宿主架构跑，就显式写宿主架构。
#
# 编码方式：profile 挂在「数据库服务」上，而不是挂在应用服务上——
#   docker-compose.yml 里 mongo 是 `profiles: [dev]`，panweidb 是 `profiles: [panweidb, test]`，
#   应用服务不带 profile。于是：
#     --profile dev  -> 只多拉起 mongo
#     --profile test -> 只多拉起 panweidb
#     --profile prod -> 两个都不拉起
# 没有把 profile 挂到应用服务上，是因为 compose 只能「按 profile 启用服务」，
# 不能「按 profile 禁用服务」；缺数据库时会直接报
# `depends on undefined service`，所以应用服务对 mongo/redis/panweidb 的
# depends_on 都写了 `required: false`（未启用时 compose 跳过该依赖）。

# profile 的固定顺序，用于错误提示。
MOGO_PROFILE_NAMES="dev test prod"

# 本文件既被 mogo CLI source（那里已有 dotenv_value），也被 dev.sh 这类宿主
# 脚本直接 source。后者没有 CLI 的实现，这里给一份等价兜底：取 .env 里同名键的
# 最后一条定义，并去掉首尾引号与 CR。
if ! declare -F dotenv_value >/dev/null 2>&1; then
  dotenv_value() {
    local key="$1"
    local env_file="${ROOT_DIR:-.}/.env"
    local line=""
    if [[ -f "${env_file}" ]]; then
      line="$(grep -E "^[[:space:]]*${key}=" "${env_file}" | tail -n 1 || true)"
    fi
    line="${line#*=}"
    line="${line%$'\r'}"
    line="${line#\"}"
    line="${line%\"}"
    line="${line#\'}"
    line="${line%\'}"
    printf '%s' "${line}"
  }
fi

mogo_profile_is_valid() {
  case "${1:-}" in
    dev|test|prod) return 0 ;;
    *) return 1 ;;
  esac
}

# 环境变量优先（已 export 的覆盖 .env），否则读 .env——与 deploy/cli/images.sh
# 里 mogo_panweidb_backend_selected 的口径一致。
mogo_profile_env_value() {
  local key="$1" value
  value="${!key-}"
  if [[ -z "${value}" ]]; then
    value="$(dotenv_value "${key}")"
  fi
  printf '%s' "${value}"
}

# 把 profile 名并入 COMPOSE_PROFILES（逗号分隔、去重、保留用户已有的其它
# profile，例如 ha / pool / observability / backup）。
mogo_profile_add_compose_profile() {
  local want="$1" existing="${COMPOSE_PROFILES:-}" item
  local -a parts=()
  if [[ -n "${existing}" ]]; then
    IFS=',' read -r -a parts <<< "${existing}"
  fi
  for item in ${parts[@]+"${parts[@]}"}; do
    if [[ "${item}" == "${want}" ]]; then
      export COMPOSE_PROFILES="${existing}"
      return 0
    fi
  done
  if [[ -n "${existing}" ]]; then
    export COMPOSE_PROFILES="${existing},${want}"
  else
    export COMPOSE_PROFILES="${want}"
  fi
}

# down 要把所有环境留下的数据库容器都收拾掉：只带当前 profile 时，compose
# 只清理该 profile 启用的服务，别的环境起的容器会存活（实测 v5.5.0：不带
# --profile dev 的 down 不会删除 dev profile 起的 mongo）。所以 down 之前把
# 三个环境 profile 一起并进 COMPOSE_PROFILES。
mogo_profile_cover_all_environments() {
  local name
  for name in ${MOGO_PROFILE_NAMES}; do
    mogo_profile_add_compose_profile "${name}"
  done
}

mogo_profile_host_platform() {
  case "$(uname -m 2>/dev/null || true)" in
    arm64|aarch64) printf 'linux/arm64' ;;
    x86_64|amd64) printf 'linux/amd64' ;;
    *) printf '' ;;
  esac
}

mogo_profile_target_platform() {
  case "${1:-}" in
    dev|test) printf 'linux/arm64' ;;
    prod) printf 'linux/amd64' ;;
    *) printf '' ;;
  esac
}

mogo_profile_backend_label() {
  case "${1:-}" in
    dev) printf 'mongo' ;;
    test) printf 'panweidb' ;;
    prod) printf 'panweidb-external' ;;
    *) printf '' ;;
  esac
}

# 未显式给 --profile 时的推断规则（保持既有部署行为不变）：
#   MOGO_USE_EXTERNAL_DB=1     -> prod（外部数据库，栈内不跑 DB 容器）
#   MOGO_DATA_BACKEND=panweidb -> test（栈内 panweidb）
#   其余                       -> dev（栈内 mongo，历史默认）
mogo_profile_infer() {
  local external backend
  external="$(mogo_profile_env_value MOGO_USE_EXTERNAL_DB)"
  if [[ "${external}" == "1" ]]; then
    printf 'prod'
    return 0
  fi
  backend="$(mogo_profile_env_value MOGO_DATA_BACKEND)"
  backend="$(printf '%s' "${backend}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  if [[ "${backend}" == "panweidb" ]]; then
    printf 'test'
    return 0
  fi
  printf 'dev'
}

# 容器平台：架构必须在启动前定下来，不做静默降级。
#   - MOGO_PLATFORM 显式给（环境变量或 .env）-> 原样使用，CLI 不再改写；
#   - 未显式给 -> 导出 profile 的目标架构（dev/test=arm64，prod=amd64）；
#   - 未显式给且宿主架构 != 目标架构 -> 直接拒绝启动，要求先写架构。
# 最后一条是刻意的：在 arm64 开发机上 `--profile prod` 若悄悄退回 arm64，得到的是
# "prod 拓扑 + arm64 镜像"的混合体，既不是真正的 x86 交付，也不像演练。要演练就
# 显式写 `MOGO_PLATFORM=linux/arm64`（宿主架构），要交付就写 `linux/amd64`。
mogo_profile_configure_platform() {
  local profile="$1" target host explicit
  target="$(mogo_profile_target_platform "${profile}")"
  host="$(mogo_profile_host_platform)"
  explicit="$(mogo_profile_env_value MOGO_PLATFORM)"
  if [[ -n "${explicit}" ]]; then
    export MOGO_PLATFORM="${explicit}"
    return 0
  fi
  if [[ -z "${target}" ]]; then
    return 0
  fi
  if [[ -n "${host}" && "${host}" != "${target}" ]]; then
    mogo_msg profile_arch_unspecified "${profile}" "${target}" "${host}" >&2
    return 2
  fi
  export MOGO_PLATFORM="${target}"
}

# 归一化 + 校验 + 导出。返回非 0 时调用方应中止启动。
#   第一个参数 announce（默认 true）：false 时只导出、不打印选中行，
#   用于 help / version 这类不碰 compose 的命令。
#   第二个参数 pin_platform（默认 true）：false 时不推导容器架构，
#   用于 dev.sh 这类宿主原生进程（没有容器平台可钉）。
mogo_apply_profile() {
  local announce="${1:-true}"
  local pin_platform="${2:-true}"
  local profile="${MOGO_PROFILE:-}"
  if [[ -n "${profile}" ]]; then
    if ! mogo_profile_is_valid "${profile}"; then
      mogo_msg profile_invalid "${profile}" "${MOGO_PROFILE_NAMES}" >&2
      return 2
    fi
  else
    profile="$(mogo_profile_infer)"
  fi
  export MOGO_PROFILE="${profile}"

  local backend external panweidb_host
  backend="$(mogo_profile_env_value MOGO_DATA_BACKEND)"
  backend="$(printf '%s' "${backend}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  external="$(mogo_profile_env_value MOGO_USE_EXTERNAL_DB)"

  case "${profile}" in
    dev)
      # dev 固定 mongo：若 .env 里还写着 panweidb，属于环境与 profile 冲突，
      # 直接提示改用 --profile test，避免"起了 mongo 却连 panweidb"的怪状态。
      if [[ "${backend}" == "panweidb" ]]; then
        mogo_msg profile_dev_backend_conflict >&2
        return 2
      fi
      if [[ "${external}" == "1" ]]; then
        mogo_msg profile_dev_external_conflict >&2
        return 2
      fi
      export MOGO_DATA_BACKEND=mongo
      ;;
    test)
      if [[ "${external}" == "1" ]]; then
        mogo_msg profile_test_external_conflict >&2
        return 2
      fi
      export MOGO_DATA_BACKEND=panweidb
      ;;
    prod)
      export MOGO_DATA_BACKEND=panweidb
      panweidb_host="$(mogo_profile_env_value PANWEIDB_HOST)"
      if [[ -z "${panweidb_host}" ]]; then
        mogo_msg profile_prod_panweidb_missing >&2
        return 2
      fi
      case "${panweidb_host}" in
        panweidb|mongo|redis)
          mogo_msg profile_prod_panweidb_internal "${panweidb_host}" >&2
          return 2
          ;;
      esac
      ;;
  esac

  mogo_profile_add_compose_profile "${profile}"
  if [[ "${pin_platform}" != "false" ]]; then
    mogo_profile_configure_platform "${profile}" || return $?
  fi
  if [[ "${announce}" != "false" ]]; then
    mogo_msg profile_selected "${profile}" "$(mogo_profile_backend_label "${profile}")"
  fi
}
