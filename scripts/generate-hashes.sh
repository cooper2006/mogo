#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Generate pip requirements files with integrity hashes (QF-465)
# ═══════════════════════════════════════════════════════════════════════
#
# Usage:
#   bash scripts/generate-hashes.sh <service>
#
# For each Python service, creates:
#   services/<service>/requirements.in      — dependency specs (no hashes)
#   services/<service>/requirements.txt     — pinned versions WITH hashes
#
# Then update Dockerfile:
#   RUN pip install --require-hashes -r requirements.txt
#
# Performance: uses the Tsinghua PyPI mirror for fast downloads.
# Generates ~1000 hashes in ~3 minutes on a decent connection.
#
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SERVICE="${1:?Usage: $0 <service>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$ROOT/services/$SERVICE"
PY="${PYTHON:-python3}"

if [[ ! -d "$SERVICE_DIR" ]]; then
  echo "Error: services/$SERVICE not found" >&2
  exit 1
fi

REQUIREMENTS="$SERVICE_DIR/requirements.txt"
INFILE="$SERVICE_DIR/requirements.in"

# Create requirements.in from current requirements.txt (strip comments, keep pins)
echo "==> Generating $INFILE from $REQUIREMENTS"
grep -vE '^\s*(#|$)' "$REQUIREMENTS" > "$INFILE"

# Generate hashes using pip-compile with Tsinghua mirror
echo "==> Running pip-compile --generate-hashes (Tsinghua mirror)"
pip install --quiet pip-tools 2>/dev/null || true

PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}" \
  "$PY" -m piptools compile \
  --generate-hashes \
  --strip-extras \
  --index-url "${PIP_INDEX_URL}" \
  --quiet \
  --output-file "$REQUIREMENTS" \
  "$INFILE"

echo ""
echo "✅ $REQUIREMENTS updated with hashes."
echo "   Update Dockerfile to add --require-hashes:"
echo "     RUN pip install --require-hashes -r requirements.txt"
echo ""
echo "   Re-run this script after any dependency change."
echo ""
echo "ℹ️  The generated requirements.txt now contains:"
grep -c 'sha256:' "$REQUIREMENTS" | xargs echo "   Total hashes:"
grep -c '^' "$REQUIREMENTS" | xargs echo "   Total lines:"