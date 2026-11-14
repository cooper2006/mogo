#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Generate pip requirements files with integrity hashes (QF-465)
# ═══════════════════════════════════════════════════════════════════════
#
# Uses pip-compile --generate-hashes with the Tsinghua PyPI mirror.
# Generates hashes for ALL compatible platforms, so --require-hashes
# works on any platform (Linux amd64/arm64, macOS, Windows).
#
# Performance: ~3 minutes per service with the Tsinghua mirror.
# (Previously >5 min with pypi.org; the mirror is the key optimization.)
#
# Usage:
#   bash scripts/generate-hashes.sh <service>
#   bash scripts/generate-hashes.sh <service> --docker <python-version> [platform]
#
# Examples:
#   bash scripts/generate-hashes.sh chat-api            # 本机 python3（3.13 in CI）
#   bash scripts/generate-hashes.sh document-parser --docker 3.10 linux/amd64
#
# --docker 模式：把 pip-compile 放进指定 Python 版本的容器里跑（amd64，与生产同构）。
#   document-parser 必须用 --docker 3.10：其 Docling 家族依赖只兼容 Python 3.10，
#   且 Dockerfile 是 3.10；在 3.13 上编译出的锁与 3.10 运行时不匹配（QF-465 回退根因）。
#
# Output:
#   services/<service>/requirements.in      — direct dependency specs (input, no hashes)
#   services/<service>/requirements.txt     — pinned versions WITH hashes (generated output)
#
# Then Dockerfile uses:
#   RUN pip install --require-hashes -r requirements.txt
#
# 注意：requirements-docling.txt 是显式降级（不加哈希）——见该文件头部注释与
# docs/WORK_LOG.md 2026-10-07。本脚本只对服务主 requirements.txt 生成哈希；
# docling 子文件若需重新钉版本，手工编辑即可（它不走 --require-hashes）。
#
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SERVICE=""
DOCKER_MODE=0
PYVER=""
PLATFORM="linux/amd64"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker)
      DOCKER_MODE=1
      PYVER="${2:?--docker requires a python version}"
      [[ -n "${3:-}" && "$3" != --* ]] && PLATFORM="$3"; shift
      ;;
    *)
      [[ -z "$SERVICE" ]] && SERVICE="$1"
      ;;
  esac
  shift
done

SERVICE="${SERVICE:?Usage: $0 <service> [--docker <python-version> [platform]]}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$ROOT/services/$SERVICE"
PY="${PYTHON:-python3}"
# 默认值在 HOST shell 里保证 PIP_INDEX_URL 有值；容器模式通过 `export` 传给容器，
# 避免 -e 拿到空串导致容器内 `set -u` 报 unbound variable。
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL

if [[ ! -d "$SERVICE_DIR" ]]; then
  echo "Error: services/$SERVICE not found" >&2
  exit 1
fi

REQUIREMENTS="$SERVICE_DIR/requirements.txt"
INFILE="$SERVICE_DIR/requirements.in"

# ── Guard：拒绝把已带哈希的 requirements.txt 反写进 requirements.in（幂等性）──
# 脚本设计意图：.in 始终保存"直接依赖规格"（无哈希），.txt 是生成的锁文件。
# 一旦 .in 里出现 `--hash`，说明它被（重复运行或其它来源）污染成锁文件，
# 此时继续生成只会越滚越脏，必须停下让人先恢复 .in。
if grep -q -- '--hash=' "$INFILE" 2>/dev/null; then
  echo "Error: $INFILE 已包含 --hash 行（被污染成锁文件）。" >&2
  echo "       请先恢复成无哈希的直接依赖规格（如 git checkout -- \"$INFILE\"），" >&2
  echo "       或手工整理后再运行本脚本。" >&2
  exit 1
fi

if [[ "$DOCKER_MODE" == "1" ]]; then
  # 在指定 Python 版本的容器里跑 pip-compile（与生产同构）。
  # .in 作为输入、.txt 作为输出，均在挂载的 SERVICE_DIR 内完成；不覆盖 .in。
  # 用 DaoCloud 镜像兜底（国内拉 docker.io 可能 502）。
  IMAGE="docker.m.daocloud.io/library/python:${PYVER}-slim-bookworm"
  echo "==> Running pip-compile --generate-hashes in $IMAGE ($PLATFORM)"
  docker run --rm --platform "$PLATFORM" \
    -v "$SERVICE_DIR":/work -w /work \
    -e PIP_INDEX_URL \
    "$IMAGE" bash -lc '
      set -uo pipefail
      pip install -q pip-tools
      python -m piptools compile --generate-hashes --strip-extras \
        --index-url "$PIP_INDEX_URL" --quiet \
        --output-file requirements.txt requirements.in
    '
else
  # 本机模式（QF-465 原路径）：用 $PY（默认 python3）跑 pip-compile。
  echo "==> Running pip-compile --generate-hashes (Tsinghua mirror)"
  pip install --quiet pip-tools 2>/dev/null || true
  "$PY" -m piptools compile \
    --generate-hashes \
    --strip-extras \
    --index-url "$PIP_INDEX_URL" \
    --quiet \
    --output-file "$REQUIREMENTS" \
    "$INFILE"
fi

echo ""
echo "✅ $REQUIREMENTS updated with hashes."
echo "   $(grep -c 'sha256:' "$REQUIREMENTS") hashes, $(grep -c '^' "$REQUIREMENTS") lines"
echo ""
echo "   Dockerfile should use:"
echo "     RUN pip install --require-hashes -r requirements.txt"
echo ""
echo "   Re-run this script after any dependency change."
[[ "$DOCKER_MODE" == "1" ]] && echo "   (regenerated under $PLATFORM / Python $PYVER; verify --require-hashes install before shipping)"