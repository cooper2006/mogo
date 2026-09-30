#!/usr/bin/env bash
#
# 生成 mogo 的生产离线发布包：
#   确定版本号(git) -> 交叉构建 amd64 镜像 -> 打包 -> 校验 -> 渲染 Stack 清单 -> 生成部署单
#
# 用法：
#   ./prepare-release.sh [TAG] [选项]
#
#   TAG                版本号。**不给就自动取 git short hash**（`git rev-parse --short HEAD`），
#                      这也是默认且推荐的用法，保证 tag 与代码提交一一对应。
#   --skip-build       不重建应用镜像，复用本地已有镜像
#   --skip-pack        不重新打包 tar，复用已有 tar（只渲染清单 / 校验 / 出文档）
#   --out DIR          输出目录，默认 <仓库根>/prod-images-<TAG>
#   --mirror HOST      基础镜像走的镜像站，默认 docker.m.daocloud.io
#                      （也可用环境变量 MOGO_BASE_IMAGE_MIRROR 指定）
#   -h, --help         显示帮助
#
# 产出（<out>/）：
#   01-base.tar                   运行时基础镜像 alpine / mongo / redis / weaviate
#   02-app-small.tar              小体积应用镜像
#   03-chat-api.tar               chat-api
#   04-document-parser.tar        document-parser（document-api 与 document-worker 共用）
#   docker-compose.portainer.yml  已渲染、可直接上传 Portainer 的 Stack 清单
#   DEPLOY.md                     自包含的部署单（含实测体积与 sha256）
#   bundle.json                   发布包元数据（版本号 / commit / 校验结果）
#
# 已知耗时：应用镜像的交叉构建实测 1 小时以上，瓶颈是外网带宽。建议后台跑：
#   nohup ./prepare-release.sh > /tmp/prepare-release.log 2>&1 &

set -euo pipefail

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(cd "$SELF_DIR/../.." && pwd)

APP_PREFIX="ghcr.io/himovo"
# <服务名>:<tar 文件名>，每个大镜像单独打包（网页上传时可单独重传）
BIG_SPECS="chat-api:03-chat-api.tar document-parser:04-document-parser.tar"
BASE_TAR="01-base.tar"
SMALL_TAR="02-app-small.tar"
# 这些目录里的改动会影响镜像内容，工作区不干净时要重点提醒
IMAGE_PATHS="services/ apps/ deploy/docker/ docker-compose.yml docker-compose.build.yml"

TAG_ARG=""
SKIP_BUILD=0
SKIP_PACK=0
OUT_DIR=""
MIRROR="${MOGO_BASE_IMAGE_MIRROR:-docker.m.daocloud.io}"
PY="${MOGO_PYTHON:-python3}"

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf '\n  X %s\n' "$*" >&2; exit 1; }

# 打印脚本开头的整段注释作为帮助（自适应，改注释不用改这里）
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-pack)  SKIP_PACK=1;  shift ;;
    --out)    [ $# -ge 2 ] || die "--out 需要一个目录参数"; OUT_DIR="$2"; shift 2 ;;
    --mirror) [ $# -ge 2 ] || die "--mirror 需要一个主机名"; MIRROR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "未知选项：$1（用 -h 看用法）" ;;
    *) [ -z "$TAG_ARG" ] || die "只接受一个 TAG 参数"; TAG_ARG="$1"; shift ;;
  esac
done

# ------------------------------------------------------------ 1. 确定版本号
say "1/9 确定版本号"

git -C "$ROOT_DIR" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT_DIR 不是 git 仓库，请显式传入 TAG"

GIT_SHORT=$(git -C "$ROOT_DIR" rev-parse --short HEAD)
GIT_FULL=$(git -C "$ROOT_DIR" rev-parse HEAD)
GIT_BRANCH=$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)
GIT_SUBJECT=$(git -C "$ROOT_DIR" log -1 --pretty=%s)

if [ -n "$TAG_ARG" ]; then
  TAG="$TAG_ARG"
  info "版本号（命令行指定）：$TAG"
  if [ "$TAG" != "$GIT_SHORT" ]; then
    warn "与当前 git short hash（${GIT_SHORT}）不一致，产物将无法与提交一一对应"
  fi
else
  TAG="$GIT_SHORT"
  info "版本号（取自 git）：$TAG"
fi
case "$TAG" in
  *[!A-Za-z0-9._-]*) die "TAG 含非法字符（只允许字母数字 . _ -）：$TAG" ;;
esac

info "完整 commit : $GIT_FULL"
info "分支        : $GIT_BRANCH"
info "提交标题    : $GIT_SUBJECT"

# 工作区不干净 → tag 与实际构建内容不一致，镜像内容无法从 tag 复现
DIRTY=$(git -C "$ROOT_DIR" status --porcelain)
if [ -n "$DIRTY" ]; then
  DIRTY_COUNT=$(printf '%s\n' "$DIRTY" | grep -c . || true)
  warn "工作区有 $DIRTY_COUNT 项未提交改动，产物与 commit $GIT_SHORT 不完全对应"
  printf '%s\n' "$DIRTY" | sed 's/^/      /' >&2
  HITS=""
  for p in $IMAGE_PATHS; do
    if printf '%s\n' "$DIRTY" | grep -q -- "$p"; then HITS="$HITS $p"; fi
  done
  if [ -n "$HITS" ]; then
    warn "其中这些路径会直接影响镜像内容，强烈建议先提交再打包：$HITS"
  else
    info "这些改动都不影响镜像内容（非 services/apps/deploy 路径），可继续"
  fi
fi

# ---------------------------------------------------------------- 2. 前置检查
say "2/9 前置检查"

command -v docker >/dev/null 2>&1 || die "找不到 docker"
docker info >/dev/null 2>&1 || die "docker daemon 不可用"
command -v "$PY" >/dev/null 2>&1 || die "找不到 ${PY}（可用 MOGO_PYTHON 指定）"

OUT_DIR="${OUT_DIR:-$ROOT_DIR/prod-images-$TAG}"
info "输出目录    : $OUT_DIR"
info "镜像站      : $MIRROR"
info "本机架构    : $(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')（目标 linux/amd64）"

if [ -f "$ROOT_DIR/.env" ] && grep -q '_IMAGE=' "$ROOT_DIR/.env" 2>/dev/null; then
  warn "仓库根 .env 里有 *_IMAGE 覆盖，会在构建时改写镜像名（实测踩过）："
  grep -n '_IMAGE=' "$ROOT_DIR/.env" | sed 's/^/      /' >&2
  warn "本脚本会用显式 MOGO_*_IMAGE 覆盖掉它们，无需你手改 .env"
fi

# ------------------------------------------------- 3. 固定 compose 变量（关键）
say "3/9 固定 compose 变量"
# .env 里的 MOVO_*_IMAGE 会被 ${MOGO_*_IMAGE:-${MOVO_*_IMAGE:-默认}} 当成兜底值，
# 导致构建产物被打成别的名字。显式导出 MOGO_*_IMAGE（shell 环境优先于 .env）来屏蔽它。
export MOGO_VERSION="$TAG"
export MOGO_CHAT_API_IMAGE="$APP_PREFIX/chat-api:$TAG"
export MOGO_ADMIN_API_IMAGE="$APP_PREFIX/admin-api:$TAG"
export MOGO_DOCUMENT_API_IMAGE="$APP_PREFIX/document-parser:$TAG"
export MOGO_DOCUMENT_WORKER_IMAGE="$APP_PREFIX/document-parser:$TAG"
export MOGO_DSH_RUNTIME_HOST_IMAGE="$APP_PREFIX/dsh-runtime-host:$TAG"
export MOGO_USER_WEB_IMAGE="$APP_PREFIX/user-web:$TAG"
export MOGO_ADMIN_WEB_IMAGE="$APP_PREFIX/admin-web:$TAG"
export MOGO_GATEWAY_IMAGE="$APP_PREFIX/gateway:$TAG"
export DOCKER_DEFAULT_PLATFORM=linux/amd64
export BUILDX_NO_DEFAULT_ATTESTATIONS=1
info "已导出 MOGO_*_IMAGE 与 DOCKER_DEFAULT_PLATFORM=linux/amd64"

# ---------------------------------------------------------- 4. 收集镜像清单
say "4/9 从 compose 推导镜像清单"

ALL_IMAGES=$(cd "$ROOT_DIR" && docker compose -f docker-compose.yml config --images | sort -u)
[ -n "$ALL_IMAGES" ] || die "compose 没解析出任何镜像"

APP_IMAGES=""
BASE_IMAGES=""
while IFS= read -r img; do
  [ -n "$img" ] || continue
  case "$img" in
    "$APP_PREFIX"/*) APP_IMAGES="${APP_IMAGES}${img}
" ;;
    *) BASE_IMAGES="${BASE_IMAGES}${img}
" ;;
  esac
done <<EOF
$ALL_IMAGES
EOF

info "应用镜像（需交叉构建）："
printf '%s' "$APP_IMAGES" | sed 's/^/      /'
info "基础镜像（需 amd64 变体）："
printf '%s' "$BASE_IMAGES" | sed 's/^/      /'

# ------------------------------------------------------------ 5. 构建应用镜像
say "5/9 交叉构建应用镜像"
if [ "$SKIP_BUILD" = "1" ]; then
  info "跳过（--skip-build）"
else
  info "耗时较长（实测 1 小时以上），瓶颈是外网带宽；下面会实时输出构建日志"
  ( cd "$ROOT_DIR" && docker compose -f docker-compose.yml -f docker-compose.build.yml build )
fi

# ------------------------------------------------------------ 6. 校验应用镜像
say "6/9 校验应用镜像架构"
while IFS= read -r img; do
  [ -n "$img" ] || continue
  arch=$(docker image inspect "$img" --format '{{.Architecture}}' 2>/dev/null || true)
  [ "$arch" = "amd64" ] || die "$img 不存在或不是 amd64（实际：${arch:-缺失}）"
  info "OK  $img"
done <<EOF
$APP_IMAGES
EOF

# -------------------------------------------------- 7. 基础镜像的 amd64 变体
say "7/9 生成基础镜像的 amd64 变体"

STAGE_PAIRS=""   # 每行：<staging标签>@<规范名>
if [ "$SKIP_PACK" = "1" ]; then
  info "跳过（--skip-pack，不重新打包就不需要 staging 镜像）"
else
  STAGE_CTX=$(mktemp -d "${TMPDIR:-/tmp}/mogo-prepare-stage.XXXXXX")
  info "staging 构建上下文：${STAGE_CTX}（保留，便于排查；只有几 KB）"

  # 镜像站前缀解析：Docker Hub 单段名补 library/；自带 registry 的引用原样透传
  mirror_ref() {
    ref="$1"
    case "$ref" in
      */*) : ;;
      *) printf '%s/library/%s' "$MIRROR" "$ref"; return ;;
    esac
    host="${ref%%/*}"
    case "$host" in
      *.*|*:*) printf '%s' "$ref" ;;
      *) printf '%s/%s' "$MIRROR" "$ref" ;;
    esac
  }

  while IFS= read -r img; do
    [ -n "$img" ] || continue
    src=$(mirror_ref "$img")
    safe=$(printf '%s' "$img" | tr '/:' '__')
    stage="mogo-staging/${safe}:amd64"
    printf 'FROM %s\nLABEL mogo.export.platform=linux/amd64\n' "$src" > "$STAGE_CTX/Dockerfile"

    # 必须走 buildx：docker pull --platform 在 OrbStack 上是空操作，
    # 而本地只有 arm64 内容时 docker save --platform 会报 no suitable export target found。
    if ! docker buildx build --platform linux/amd64 --load \
          -f "$STAGE_CTX/Dockerfile" -t "$stage" "$STAGE_CTX" >"$STAGE_CTX/build.log" 2>&1; then
      tail -8 "$STAGE_CTX/build.log" >&2
      die "基础镜像 amd64 构建失败：${img}（源：${src}）"
    fi
    arch=$(docker image inspect "$stage" --format '{{.Architecture}}')
    [ "$arch" = "amd64" ] || die "$stage 架构异常：$arch"

    STAGE_PAIRS="${STAGE_PAIRS}${stage}@${img}
"
    info "OK  $img  ->  $stage"
  done <<EOF
$BASE_IMAGES
EOF
fi

# -------------------------------------------------------------------- 8. 打包
say "8/9 打包"
mkdir -p "$OUT_DIR"

# 小体积应用镜像 = 除 BIG_SPECS 之外的全部
SMALL_IMAGES=""
while IFS= read -r img; do
  [ -n "$img" ] || continue
  repo="${img%:*}"; svc="${repo##*/}"
  is_big=0
  for spec in $BIG_SPECS; do
    [ "${spec%%:*}" = "$svc" ] && is_big=1
  done
  [ "$is_big" = "1" ] || SMALL_IMAGES="${SMALL_IMAGES}${img}
"
done <<EOF
$APP_IMAGES
EOF

if [ "$SKIP_PACK" = "1" ]; then
  info "跳过（--skip-pack），复用 $OUT_DIR 里已有的 tar"
else
  # 01：基础镜像合并成一个包（源是 staging 标签，目标写成规范名）
  [ -n "$STAGE_PAIRS" ] || die "基础镜像清单为空"
  # shellcheck disable=SC2086
  set -- $(printf '%s' "$STAGE_PAIRS" | tr '\n' ' ')
  info "01  $BASE_TAR  <- $# 个基础镜像"
  "$PY" "$SELF_DIR/merge_images.py" "$OUT_DIR/$BASE_TAR" "$@"

  # 02：小体积应用镜像，标签已是规范名，直接 save
  [ -n "$SMALL_IMAGES" ] || die "小体积应用镜像清单为空"
  # shellcheck disable=SC2086
  set -- $(printf '%s' "$SMALL_IMAGES" | tr '\n' ' ')
  info "02  $SMALL_TAR  <- $# 个应用镜像"
  docker save -o "$OUT_DIR/$SMALL_TAR" "$@"

  # 03..：每个大镜像单独一个包
  for spec in $BIG_SPECS; do
    svc="${spec%%:*}"; file="${spec##*:}"
    info "$(printf '%s' "$file" | cut -c1-2)  $file  <- $APP_PREFIX/$svc:$TAG"
    docker save -o "$OUT_DIR/$file" "$APP_PREFIX/$svc:$TAG"
  done
fi

# ------------------------------------------------- 9. 渲染清单 / 校验 / 出部署单
say "9/9 渲染清单、校验、出部署单"

TPL="$SELF_DIR/docker-compose.portainer.yml.tpl"
[ -f "$TPL" ] || die "找不到清单模板 $TPL"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
# 渲染：删掉模板专用注释行（#!TEMPLATE-ONLY 前缀）、替换版本占位符、注入来源信息
"$PY" -c '
import pathlib, sys
src, dst, tag, prov = sys.argv[1:5]
lines = [l for l in pathlib.Path(src).read_text().splitlines()
         if not l.startswith("#!TEMPLATE-ONLY")]
out = []
for i, l in enumerate(lines):
    out.append(l.replace("__MOGO_TAG__", tag))
    if i == 0:
        out += ["#", prov]
pathlib.Path(dst).write_text("\n".join(out) + "\n")
' "$TPL" "$OUT_DIR/docker-compose.portainer.yml" "$TAG" \
  "# 由 deploy/production/prepare-release.sh 渲染：tag=$TAG, commit=${GIT_FULL:0:12}, 分支 $GIT_BRANCH, $TIMESTAMP"
info "已渲染 docker-compose.portainer.yml"

# 渲染结果不该再出现占位符或模板专用行
if grep -q '__MOGO_TAG__\|#!TEMPLATE-ONLY' "$OUT_DIR/docker-compose.portainer.yml"; then
  die "渲染后的清单里还残留占位符或模板专用行，请检查模板"
fi
info "已确认无残留占位符"

# 渲染出来的清单必须能过 compose 语法校验
if ( cd "$ROOT_DIR" && docker compose -f "$OUT_DIR/docker-compose.portainer.yml" config >/dev/null 2>&1 ); then
  info "渲染后的清单 compose 语法校验通过"
else
  die "渲染后的清单没通过 compose 语法校验，请检查模板"
fi

# 写发布包计划，交给 verify_bundle.py 校验并回填结果
PLAN_FILE="$OUT_DIR/.bundle-plan.txt"
: > "$PLAN_FILE"
csv() { printf '%s' "$1" | awk 'NF{printf "%s%s", (n++ ? "," : ""), $0}'; }
printf '%s|%s\n' "$BASE_TAR" "$(csv "$BASE_IMAGES")" >> "$PLAN_FILE"
printf '%s|%s\n' "$SMALL_TAR" "$(csv "$SMALL_IMAGES")" >> "$PLAN_FILE"
for spec in $BIG_SPECS; do
  svc="${spec%%:*}"; file="${spec##*:}"
  printf '%s|%s\n' "$file" "$APP_PREFIX/$svc:$TAG" >> "$PLAN_FILE"
done

"$PY" - "$OUT_DIR" "$TAG" "$PLAN_FILE" "$GIT_FULL" "$GIT_BRANCH" "$GIT_SUBJECT" <<'PY'
import datetime, json, pathlib, sys

out, tag, plan_file = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
commit, branch, subject = sys.argv[4], sys.argv[5], sys.argv[6]

packages = []
for line in plan_file.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    fname, imgs = line.split("|", 1)
    packages.append({"file": fname, "images": [x for x in imgs.split(",") if x]})

plan = {
    "tag": tag,
    "commit": commit,
    "branch": branch,
    "commit_subject": subject,
    "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "compose_file": "docker-compose.portainer.yml",
    "packages": packages,
}
(out / "bundle.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
print(f"  已写入 {out / 'bundle.json'}（{len(packages)} 个包，tag={tag}，commit={commit[:12]}）")
PY

"$PY" "$SELF_DIR/verify_bundle.py" "$OUT_DIR" || die "镜像包校验未通过，见上面的失败项"
"$PY" "$SELF_DIR/render_deploy_doc.py" "$OUT_DIR"

# --------------------------------------------------------------------- 汇总
say "完成"
info "版本     : $TAG  (commit ${GIT_FULL:0:12}, 分支 $GIT_BRANCH)"
info "发布包目录：$OUT_DIR"
ls -la "$OUT_DIR" | sed 's/^/      /'
printf '\n'
info "把这个目录整体交给运维：上传 4 个 tar 到 Portainer 的 Images -> Import，"
info "再用其中的 docker-compose.portainer.yml 建 Stack（名字填 mogo）。"
info "具体步骤见 $OUT_DIR/DEPLOY.md"
