#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=../deploy/cli/pull.sh
source "${ROOT_DIR}/deploy/cli/pull.sh"

movo_msg() { :; }
sleep() { :; }

calls=()
failures_remaining=0
failure_status=1
mogo_compose() {
  calls+=("$*")
  if ((failures_remaining > 0)); then
    failures_remaining=$((failures_remaining - 1))
    return "${failure_status}"
  fi
}

# Assertions use an explicit failure branch rather than a bare `[[ ... ]]`:
# under bash 3.2 (the version shipped with macOS) a failing `[[ ]]` does NOT
# trigger errexit, so a bare assertion silently passes there even though it
# correctly fails on the bash 5.x used by CI. Failing loudly keeps local runs
# and CI in agreement.
fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_eq() {
  local actual="$1" expected="$2" label="$3"
  [[ "${actual}" == "${expected}" ]] || fail "${label}: expected '${expected}', got '${actual}'"
}

movo_pull_images_serially missing
assert_eq "${#calls[@]}" "1" "first pull issues exactly one call"
assert_eq "${calls[0]}" "--parallel 1 pull --policy missing" "first pull policy"

calls=()
failures_remaining=4
MOVO_PULL_RETRY_DELAY_SECONDS=0 movo_pull_images_serially always
assert_eq "${#calls[@]}" "5" "retries until success"
assert_eq "${calls[4]}" "--parallel 1 pull --policy always" "final retry policy"

calls=()
failures_remaining=1
failure_status=130
if MOVO_PULL_RETRY_DELAY_SECONDS=0 movo_pull_images_serially missing; then
  printf 'Expected an interrupted pull to stop.\n' >&2
  exit 1
else
  pull_status=$?
fi
assert_eq "${pull_status}" "130" "interrupted pull status is propagated"
assert_eq "${#calls[@]}" "1" "interrupted pull stops immediately"

printf 'Serial image pull behavior is valid.\n'
