#!/usr/bin/env bash
#
# verify_assertions.sh — mutation-test a shell assertion script.
#
# Why this exists
# ---------------
# An assertion can look correct and still never fail. Two real examples found in
# this repository:
#
#   * check_compose_image_modes.sh used bare `[[ ... ]]` as assertions under
#     `set -e`, which silently passed on bash 3.2 (macOS) because bash only
#     started aborting on a failed `[[ ]]` in 4.0.
#   * test_serial_image_pull.sh had the same pattern, so a broken expectation
#     passed locally while failing on CI.
#
# Reading an assertion cannot tell you whether it works. The only reliable test
# is to break the thing it guards and confirm the script actually fails. This
# tool automates that: it injects a mutation into a copy of the script and
# asserts the mutated copy exits non-zero.
#
# Usage
# -----
#   scripts/verify_assertions.sh <script.sh> [more-scripts...]
#
# Each script is run once unmutated (it must succeed) and once per mutation (it
# must then fail). A mutation that leaves the script succeeding is reported as a
# "dead assertion".
#
# Declaring mutations
# -------------------
# By default the tool auto-discovers expectations of the form
#   assert_eq <actual> <expected> <label>
# and perturbs <expected>. That only works for scripts using this convention.
#
# For anything else, declare an explicit mutation in the script under test:
#
#   # MUTATION: <name> | <sed-like python expression applied to the source> | <what it breaks>
#
# The mutation is a Python replacement expression evaluated with the script
# source bound to `src`, and must yield the mutated source. Example:
#
#   # MUTATION: wrong-policy | src.replace('--policy missing', '--policy always', 1) | pull policy expectation
#
# Declared mutations take precedence over auto-discovery.
#
# Exit status: 0 when every mutation was caught, 1 otherwise (2 on usage error).
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERBOSE="${VERIFY_ASSERTIONS_VERBOSE:-0}"
# Runner used to execute the scripts under test. Overridable so the same
# mutations can be replayed against a different bash (e.g. the bash 5.x used by
# CI) without editing anything.
SCRIPT_RUNNER="${VERIFY_ASSERTIONS_RUNNER:-bash}"
TIMEOUT_SECONDS="${VERIFY_ASSERTIONS_TIMEOUT:-120}"
# Most scripts here derive the repository root from their own path
# (`dirname "${BASH_SOURCE[0]}"/..`), so a mutated copy must keep the original
# file name and sit in the same directory as the original, otherwise the script
# fails for unrelated reasons and the mutation result is meaningless. Set to 0
# to run the mutated copy from a scratch directory instead.
IN_PLACE="${VERIFY_ASSERTIONS_IN_PLACE:-1}"

if [[ $# -eq 0 ]]; then
  printf 'usage: %s <script.sh> [more-scripts...]\n' "$(basename "$0")" >&2
  exit 2
fi

log() { printf '%s\n' "$*"; }
note() { [[ "${VERBOSE}" == "1" ]] && printf '  %s\n' "$*" || true; }

fail_count=0
total_mutations=0
caught_mutations=0
declared_any=0
unverified_count=0

# Run a command with a timeout, portable across GNU/BSD (no `timeout` on macOS
# by default, so fall back to a background watchdog).
run_with_timeout() {
  local seconds="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "${seconds}" "$@"
    return $?
  fi
  "$@" &
  local pid=$!
  (
    sleep "${seconds}"
    kill -TERM "${pid}" 2>/dev/null || true
  ) &
  local watchdog=$!
  local status=0
  wait "${pid}" || status=$?
  kill "${watchdog}" 2>/dev/null || true
  wait "${watchdog}" 2>/dev/null || true
  return "${status}"
}

# Extract `# MUTATION: name | expr | description` declarations.
# Extract `# MUTATION: name | expr | description` declarations and re-emit them
# as tab-separated records. The `|` separator is split on the first two
# occurrences only, so a mutation expression may itself contain `|`.
declared_mutations() {
  local file="$1"
  python3 - "${file}" <<'PY'
import re
import sys

path = sys.argv[1]
for line in open(path, encoding='utf-8'):
    m = re.match(r'\s*#\s*MUTATION:\s*(?P<rest>.*?)\s*$', line)
    if not m:
        continue
    rest = m.group('rest')
    parts = rest.split('|', 2)
    if len(parts) < 2:
        print(f'# MUTATION declaration needs "name | expr | description": {rest}',
              file=sys.stderr)
        sys.exit(1)
    name = parts[0].strip()
    expr = parts[1].strip()
    description = parts[2].strip() if len(parts) > 2 else ''
    if not name or not expr:
        print(f'# MUTATION declaration is incomplete: {rest}', file=sys.stderr)
        sys.exit(1)
    print(f'{name}\t{expr}\t{description}')
PY
}

# Auto-discover `assert_eq <actual> <expected> ...` expectations and produce
# mutations that perturb the expected value.
auto_mutations() {
  local file="$1"
  python3 - "${file}" <<'PY'
import re
import sys

path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()

seen = 0
for lineno, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('#'):
        continue
    m = re.match(r'assert_eq\s+', stripped)
    if not m:
        continue
    seen += 1
    if seen > 8:          # keep runtime bounded; declared mutations can cover more
        break
    label = f"auto-assert-{lineno}"
    # Perturb the *expected* operand. The label (last quoted argument) is left
    # alone so the failure message stays meaningful.
    expr = (
        "re.sub(r'(assert_eq\\s+[^\\n]*?)(\\s+\"[^\"]*\")(\\s+\"[^\"]*\"\\s*)$', "
        "lambda m: m.group(1) + ' \"__MUTATED_EXPECTATION__\"' + m.group(3), "
        "src, count=1, flags=re.M)"
    )
    print(f"{label}\t{expr}\tperturb expected value on line {lineno}")
PY
}

while [[ $# -gt 0 ]]; do
  script="$1"; shift
  if [[ ! -f "${script}" ]]; then
    printf 'error: no such script: %s\n' "${script}" >&2
    exit 2
  fi

  printf '\n=== %s ===\n' "${script}"

  # Baseline: the unmutated script must pass. If it does not, mutation results
  # are meaningless (an always-failing script would "catch" every mutation).
  if run_with_timeout "${TIMEOUT_SECONDS}" "${SCRIPT_RUNNER}" "${script}" >/dev/null 2>&1; then
    printf '  baseline: PASS\n'
  else
    printf '  baseline: FAIL — fix the script before mutation testing\n' >&2
    fail_count=$((fail_count + 1))
    continue
  fi

  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir}"' EXIT

  mutations="$(declared_mutations "${script}")"
  mode="declared"
  if [[ -z "${mutations}" ]]; then
    mutations="$(auto_mutations "${script}")"
    mode="auto"
  fi
  if [[ -n "${mutations}" ]]; then
    declared_any=1
  fi

  if [[ -z "${mutations}" ]]; then
    # Not a defect in the script under test: it simply uses assertions this tool
    # cannot perturb generically (e.g. bare `test`). Declaring mutations makes
    # it verifiable, so report it as "unverified" rather than failing.
    printf '  unverified: no mutations declared or discoverable\n' >&2
    printf '              add "# MUTATION: name | expr | description" to cover it\n' >&2
    unverified_count=$((unverified_count + 1))
    continue
  fi
  note "mutation source: ${mode}"

  while IFS=$'\t' read -r name expr description; do
    [[ -z "${name}" ]] && continue
    total_mutations=$((total_mutations + 1))

    # Keep the original file name so a script that resolves sibling resources
    # from `$0`/`BASH_SOURCE` still finds them; place it beside the original when
    # IN_PLACE=1 so `dirname "$0"/..` resolves to the same repository root.
    if [[ "${IN_PLACE}" == "1" ]]; then
      script_dir="$(cd "$(dirname "${script}")" && pwd)"
      mutated="${script_dir}/.$(basename "${script}").mutant-${name}.sh"
    else
      mutated="${tmp_dir}/${name}.sh"
    fi
    if ! python3 - "${script}" "${mutated}" "${expr}" <<'PY'
import sys
src_path, out_path, expr = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(src_path, encoding='utf-8').read()
import re  # noqa: F401  (available to mutation expressions)

# Hide the MUTATION comment lines while the expression runs, then restore them
# verbatim. Declarations embed the very text they target, so a plain
# `replace(..., 1)` would otherwise rewrite its own comment line and mutate
# nothing meaningful. Lines are replaced by a marker so restoration is exact.
_DECL = re.compile(r'^\s*#\s*MUTATION:')
_MARK = '###VFA-MUTATION-DECL###'
src_lines = src.splitlines(keepends=True)
masked_lines = [
    _MARK + ('\n' if line.endswith('\n') else '')
    if _DECL.match(line) else line
    for line in src_lines
]
masked = ''.join(masked_lines)

try:
    mutated = eval(expr, {'re': re, 'src': masked})
except Exception as exc:                                   # noqa: BLE001
    print(f'mutation expression failed: {exc}', file=sys.stderr)
    sys.exit(1)

# Restore the declaration lines unchanged so the mutant keeps its metadata.
restored = []
decl_iter = iter(src_lines)
for line in mutated.splitlines(keepends=True):
    if line.startswith(_MARK):
        for original in decl_iter:
            if _DECL.match(original):
                restored.append(original)
                break
    else:
        restored.append(line)
mutated = ''.join(restored)

if mutated == src:
    # The mutation did not change anything, so its result proves nothing.
    print('mutation is a no-op (source unchanged)', file=sys.stderr)
    sys.exit(1)

# A mutation that only edits the MUTATION declaration comments proves nothing:
# the script body is untouched, so the run necessarily passes. Catch this here
# rather than reporting a misleading "DEAD assertion".
comment_only = re.compile(r'^\s*#\s*MUTATION:')
if [line for line in src.splitlines() if not comment_only.match(line)] == \
   [line for line in mutated.splitlines() if not comment_only.match(line)]:
    print('mutation only touched its own declaration comment', file=sys.stderr)
    sys.exit(1)
open(out_path, 'w', encoding='utf-8').write(mutated)
PY
    then
      printf '  [%-28s] INVALID   — %s\n' "${name}" "${description}"
      fail_count=$((fail_count + 1))
      continue
    fi
    chmod +x "${mutated}"

    status=0
    run_with_timeout "${TIMEOUT_SECONDS}" "${SCRIPT_RUNNER}" "${mutated}" >/dev/null 2>&1 || status=$?
    # Always remove the mutant, including on the error paths above.
    rm -f "${mutated}"
    if [[ "${status}" -ne 0 ]]; then
      printf '  [%-28s] caught    — %s (exit %s)\n' "${name}" "${description}" "${status}"
      caught_mutations=$((caught_mutations + 1))
    else
      printf '  [%-28s] DEAD      — %s: script still passed after mutation\n' \
        "${name}" "${description}"
      fail_count=$((fail_count + 1))
    fi
  done <<<"${mutations}"

  rm -rf "${tmp_dir}"
  trap - EXIT
done

printf '\n----------------------------------------\n'
printf 'mutations caught: %s/%s\n' "${caught_mutations}" "${total_mutations}"
if [[ "${unverified_count}" -ne 0 ]]; then
  printf 'scripts with no usable mutation: %s\n' "${unverified_count}"
fi
if [[ "${fail_count}" -ne 0 ]]; then
  printf 'Assertion verification FAILED (%s problem(s)).\n' "${fail_count}" >&2
  exit 1
fi
printf 'Assertion verification OK: every mutation was caught.\n'
