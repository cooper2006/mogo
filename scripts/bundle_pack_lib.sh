#!/usr/bin/env bash
# Reproducible packing for the *-bundle.tar.gz build-context archives.
#
# Why this file exists
# --------------------
# `tar -czf` is not reproducible. Every member's mtime is written into the tar
# header, and gzip embeds its own timestamp plus the output name in the gzip
# header. Packing an unchanged cache twice therefore produces two different
# files -- measured on admin-api's 58-wheel cache: same input, two sha256s
# (4fc12452... and a39e42b1...).
#
# That matters because the Dockerfiles put the bundle in a `COPY` layer:
#
#   COPY pip-wheels-bundle.tar.gz /tmp/pip-wheels-bundle.tar.gz
#
# Docker keys that layer on content, so a *no-op* re-pack still invalidated it
# and forced every install step below (apt, torch, docling models) to re-run.
# The scripts claimed "same bundle = cached", but the bundle was never actually
# the same. This helper makes that claim true.
#
# Two mechanisms, both needed:
#   1. normalise every member's mtime, emit entries in a stable traversal and
#      run gzip with -n (no name/mtime in its header) -> same input, same bytes;
#   2. compare the freshly built archive against the one on disk and throw the
#      new one away when identical, so the *file's* mtime does not churn either
#      (some tooling re-sends a context when mtime moves, not just content).
#
# Compressor choice
# -----------------
# .whl and .deb payloads are already compressed (zip / xz), so the default
# gzip -6 spends ~2.6x the CPU to save ~2%: measured on a 34MiB wheel cache,
# -6 gave 35.10MB in 0.91s while uncompressed was 35.94MB in 0.34s. Level 1
# keeps the .tar.gz contract the Dockerfiles rely on (`tar -xzf`) without
# paying for a compression pass that cannot win. Override with
# BUNDLE_GZIP_LEVEL=6 if a bundle ever holds genuinely compressible payloads.
#
# Usage (from a script that already defines `die`):
#
#   source "${ROOT_DIR}/scripts/bundle_pack_lib.sh"
#   rc=0; bundle_pack "${bundle_path}" "${staged_dir}" || rc=$?
#   case "${rc}" in
#     0) printf '    repacked\n' ;;
#     1) printf '    unchanged\n' ;;
#     *) die "packing ${bundle_path} failed" ;;
#   esac
#
# `src` must be a throwaway copy: mtimes inside it are rewritten in place.
# Never point it at base-images/ -- that cache is meant to survive as-is.

# Any constant timestamp works; the only requirement is that it never varies.
BUNDLE_MTIME="${BUNDLE_MTIME:-202001010000}"
BUNDLE_GZIP_LEVEL="${BUNDLE_GZIP_LEVEL:-1}"

# Staging and temp files must live on the *same* filesystem as the bundle, for
# two reasons measured on document-parser's 873MB / 174-wheel arm64 cache:
#
#   1. `cp -c` (APFS clonefile) is a metadata operation on the same volume --
#      0.11s -- but silently falls back to a real byte copy when the target is
#      on another volume: 47.9s. `mktemp -d` defaults to $TMPDIR, which on
#      macOS is /var/folders, a *different* volume from the repo. Every pack
#      was paying the full copy for that reason alone.
#   2. bundle_pack ends with `mv`; same-volume mv is a rename (instant),
#      cross-volume mv is another full copy of the finished archive.
#
# base-images/ is git-ignored and outside every build context, so leftovers
# there can never leak into a `docker build` context either.
BUNDLE_STAGE_ROOT="${BUNDLE_STAGE_ROOT:-${ROOT_DIR:-.}/base-images/.pack-staging}"
BUNDLE_FP_DIR="${BUNDLE_FP_DIR:-${ROOT_DIR:-.}/base-images/.pack-fingerprints}"

# A staging directory on the bundle's volume. Callers stay responsible for
# removing it; stale ones from an interrupted run are swept here so a crash
# never accumulates hundreds of megabytes.
bundle_stage_dir() {
  mkdir -p "${BUNDLE_STAGE_ROOT}" || return 1
  find "${BUNDLE_STAGE_ROOT}" -mindepth 1 -maxdepth 1 \
       \( -name 'stage.*' -o -name 'tar.*' \) -mtime +0 \
       -exec rm -rf {} + 2>/dev/null || true
  mktemp -d "${BUNDLE_STAGE_ROOT}/stage.XXXXXX"
}

# Copy a tree, cloning blocks when the filesystem supports it. `cp -c` is
# rejected outright by GNU cp, so the fallback costs one failed exec on Linux
# and nothing else.
bundle_clone() {
  local src="$1" dst="$2"
  mkdir -p "${dst}" || return 1
  cp -cRf "${src}/." "${dst}/" 2>/dev/null && return 0
  cp -Rf "${src}/." "${dst}/"
}

# Copy a file list into <dst>, cloning when possible. Unmatched globs still
# reach cp verbatim, so callers keep their existing `|| true` semantics.
bundle_clone_files() {
  local dst="$1"
  shift
  mkdir -p "${dst}" || return 1
  cp -cf "$@" "${dst}/" 2>/dev/null && return 0
  cp -f "$@" "${dst}/"
}

# BSD stat and GNU stat disagree on the format flag *and* silently misinterpret
# each other's ('-f' means --file-system to GNU), so detect once instead of
# guessing from an exit code that is always 0.
_bundle_stat_kind() {
  if stat --version >/dev/null 2>&1; then printf 'gnu'; else printf 'bsd'; fi
}

# Fingerprint the *inputs* of a bundle (name + size + mtime of every file).
#
# This is what lets an unchanged cache skip packing entirely: the alternative
# is to copy the whole cache into staging and let cmp decide, which costs
# minutes on document-parser and proves the same thing. mtime is included on
# purpose -- a re-download that leaves bytes identical still only costs one
# wasted pack, never a stale bundle.
#
# Files are fed to stat through `xargs -0` rather than `find -exec stat -f ...`:
# with -exec, the format string never reaches stat here and it falls back to
# printing filesystem stats instead, which produced a fingerprint that changed
# on every run (i.e. never matched). Verified: -exec broken, xargs correct.
bundle_fingerprint() {
  local kind p
  kind="$(_bundle_stat_kind)"
  for p in "$@"; do
    [[ -e "${p}" ]] || continue
    if [[ "${kind}" == 'gnu' ]]; then
      find "${p}" -mindepth 1 -type f -print0 2>/dev/null \
        | xargs -0 stat -c '%n %s %Y' 2>/dev/null || true
    else
      find "${p}" -mindepth 1 -type f -print0 2>/dev/null \
        | xargs -0 stat -f '%N %z %m' 2>/dev/null || true
    fi
  done | LC_ALL=C sort | shasum -a 256 | cut -d' ' -f1
}

# Where the fingerprint of <out> is remembered. Keyed on the bundle's path
# relative to the repo (flattened), because several services ship a bundle with
# the same basename.
bundle_fp_path() {
  local rel="${1#"${ROOT_DIR:-.}"/}"
  printf '%s/%s.fp' "${BUNDLE_FP_DIR}" "${rel//\//__}"
}

# The compression level belongs to the recipe, so it is folded into the key:
# changing it must force a re-pack even when the inputs are untouched.
bundle_fp_key() {
  printf '%s gz=%s' "$1" "${BUNDLE_GZIP_LEVEL}"
}

# bundle_fp_hit <out.tar.gz> <fingerprint> -- true when the bundle on disk is
# already the product of exactly these inputs.
#
# Callers test this *before* staging, which is the whole point: an unchanged
# cache must cost one stat pass, not a copy of every file. The recorded size is
# checked too, so a bundle swapped in behind our back (e.g. restored from
# .local-bundles/) invalidates the fingerprint rather than masking it.
bundle_fp_hit() {
  local out="$1" fp="$2" recorded
  [[ -n "${fp}" && -f "${out}" ]] || return 1
  recorded="$(cat "$(bundle_fp_path "${out}")" 2>/dev/null || true)"
  [[ "${recorded}" == "$(bundle_fp_key "${fp}") $(wc -c < "${out}" | tr -d ' ')" ]]
}

# bundle_pack <out.tar.gz> <src-dir> [fingerprint]
#
# Writes a reproducible .tar.gz of <src-dir>'s contents (paths relative to it,
# identical layout to `tar -czf <out> -C <src-dir> .`).
#
# When <fingerprint> (from bundle_fingerprint) is given and matches what the
# last successful pack recorded -- and <out> is still the file that pack wrote
# -- the whole copy+tar pass is skipped.
#
# Returns 0 when <out> was written, 1 when it already held identical bytes and
# was left untouched, 2 on failure.
bundle_pack() {
  local out="$1" src="$2" fp="${3:-}"

  # Short-circuit before touching the disk (callers normally test this even
  # earlier, before staging; this is the backstop for direct calls).
  bundle_fp_hit "${out}" "${fp}" && return 1

  if [[ ! -d "${src}" ]]; then
    printf 'bundle_pack: %s is not a directory\n' "${src}" >&2
    return 2
  fi

  # Normalise mtimes before hashing the tree into the archive. `cp` does not
  # preserve mtime, so without this every pack carries a fresh timestamp even
  # when the file set is byte-identical.
  if ! find "${src}" -exec touch -h -t "${BUNDLE_MTIME}" {} + 2>/dev/null; then
    find "${src}" -exec touch -t "${BUNDLE_MTIME}" {} + || return 2
  fi

  # The temp archive goes next to the staging area, i.e. on <out>'s volume, so
  # the mv below is a rename rather than a second full copy of the archive.
  local tmp
  mkdir -p "${BUNDLE_STAGE_ROOT}" || return 2
  tmp="$(mktemp "${BUNDLE_STAGE_ROOT}/tar.XXXXXX")" || return 2

  # Recursive traversal (`-C <src> .`) rather than `--files-from` fed by
  # `find | sort`: bsdtar 3.5.3 (the macOS default) emits the last entry of a
  # stdin list twice, which would duplicate files in the archive. readdir order
  # is stable for an untouched directory, so the reproducibility guarantee
  # holds; the cmp below is the backstop if it ever does not.
  #
  # --uid/--gid/--numeric-owner drop the building user from the headers so a
  # bundle packed on a laptop and one packed in CI still match.
  if ! tar --format=gnutar --uid 0 --gid 0 --numeric-owner \
        -cf - -C "${src}" . 2>/dev/null \
      | gzip "-${BUNDLE_GZIP_LEVEL}" -n > "${tmp}"; then
    rm -f "${tmp}"
    return 2
  fi

  if [[ -f "${out}" ]] && cmp -s "${tmp}" "${out}"; then
    rm -f "${tmp}"
    # Bytes matched, so the cache really is already packed: remember that, or
    # the next run pays the full copy+tar again to reach the same conclusion.
    _bundle_write_fp "${out}" "${fp}"
    return 1
  fi

  mv -f "${tmp}" "${out}" || { rm -f "${tmp}"; return 2; }
  _bundle_write_fp "${out}" "${fp}"
  return 0
}

# Record <fingerprint> + the archive size for <out>. Best-effort: a read-only
# or missing fingerprint dir must never fail a pack that already succeeded.
_bundle_write_fp() {
  local out="$1" fp="$2"
  [[ -n "${fp}" ]] || return 0
  mkdir -p "${BUNDLE_FP_DIR}" 2>/dev/null || return 0
  printf '%s %s\n' "$(bundle_fp_key "${fp}")" "$(wc -c < "${out}" | tr -d ' ')" \
    > "$(bundle_fp_path "${out}")" 2>/dev/null || true
  return 0
}
