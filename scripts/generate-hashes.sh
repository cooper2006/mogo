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
#
# Output:
#   services/<service>/requirements.in      — dependency specs (no hashes)
#   services/<service>/requirements.txt     — pinned versions WITH hashes
#
# Then Dockerfile uses:
#   RUN pip install --require-hashes -r requirements.txt
#
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SERVICE="${1:?Usage: $0 <service>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$ROOT/services/$SERVICE"
PY="${PYTHON:-python3}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [[ ! -d "$SERVICE_DIR" ]]; then
  echo "Error: services/$SERVICE not found" >&2
  exit 1
fi

REQUIREMENTS="$SERVICE_DIR/requirements.txt"
INFILE="$SERVICE_DIR/requirements.in"

# Create requirements.in from current requirements.txt
echo "==> Generating $INFILE from $REQUIREMENTS"
grep -vE '^\s*(#|$)' "$REQUIREMENTS" > "$INFILE"

# Generate hashes using pip-compile with Tsinghua mirror
echo "==> Running pip-compile --generate-hashes (Tsinghua mirror)"
pip install --quiet pip-tools 2>/dev/null || true

PIP_INDEX_URL="$PIP_INDEX_URL" \
  "$PY" -m piptools compile \
  --generate-hashes \
  --strip-extras \
  --index-url "$PIP_INDEX_URL" \
  --quiet \
  --output-file "$REQUIREMENTS" \
  "$INFILE"

echo ""
echo "✅ $REQUIREMENTS updated with hashes."
echo "   $(grep -c 'sha256:' "$REQUIREMENTS") hashes, $(grep -c '^' "$REQUIREMENTS") lines"
echo ""
echo "   Dockerfile should use:"
echo "     RUN pip install --require-hashes -r requirements.txt"
echo ""
echo "   Re-run this script after any dependency change."