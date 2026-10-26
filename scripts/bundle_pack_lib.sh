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

# bundle_pack <out.tar.gz> <src-dir>
#
# Writes a reproducible .tar.gz of <src-dir>'s contents (paths relative to it,
# identical layout to `tar -czf <out> -C <src-dir> .`).
#
# Returns 0 when <out> was written, 1 when it already held identical bytes and
# was left untouched, 2 on failure.
bundle_pack() {
  local out="$1" src="$2"

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

  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/mogo-bundle.XXXXXX")" || return 2

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
    return 1
  fi

  mv -f "${tmp}" "${out}" || { rm -f "${tmp}"; return 2; }
  return 0
}
