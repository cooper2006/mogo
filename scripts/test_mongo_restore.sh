#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/test_mongo_restore.sh — 恢复行为测试（T110）
# ═══════════════════════════════════════════════════════════════════════
#
# 覆盖：
#   1. 从本地备份恢复到独立演练库，文档数与清单一致 → 成功
#   2. 密文被篡改 → 校验和不匹配，拒绝恢复（不调用 mongorestore）
#   3. 口令错误 → 解密失败，拒绝恢复
#   4. 目标库非空且未加 --drop --yes → 拒绝（防止 mongorestore 静默合并）
#   5. 恢复出来的数据少一条 → 一致性校验必须失败（不能让"恢复成功"蒙混过关）
#   6. --consistency-only 只校验不写库
#   7. --from-offsite 从异地副本取回后恢复
#
# 运行：bash scripts/test_mongo_restore.sh
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./testlib/fake_mongo.sh
source "${ROOT_DIR}/scripts/testlib/fake_mongo.sh"
# shellcheck source=./backup/lib.sh
source "${ROOT_DIR}/scripts/backup/lib.sh"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_eq() {
  local actual="$1" expected="$2" label="$3"
  [[ "${actual}" == "${expected}" ]] || fail "${label}: expected '${expected}', got '${actual}'"
}

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "${haystack}" in
    *"${needle}"*) : ;;
    *) fail "${label}: 输出里找不到 '${needle}'" ;;
  esac
}

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mogo-restore-test.XXXXXX")"
export MOGO_BACKUP_DIR="${WORK}/backups"
export MOGO_BACKUP_OFFSITE_DIR="${WORK}/offsite"
export MOGO_MONGODB_URI="mongodb://mongo:27017"
export MOGO_MONGODB_DB="mogo"
export MOGO_BACKUP_PASSPHRASE="restore-test-passphrase"

cleanup() {
  fake_mongo_cleanup
  rm -rf "${WORK}"
}
trap cleanup EXIT

fake_mongo_init
PATH="${FAKE_MONGO_BIN}:${PATH}"
export PATH

backup_out="$(bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full 2>&1)" || fail "准备备份失败：${backup_out}"
ARCHIVE="$(printf '%s\n' "${backup_out}" | tail -1)"
[[ -e "${ARCHIVE}" ]] || fail "准备备份未产出归档"

# ── 1. 正常恢复到演练库 ────────────────────────────────────────────────
printf '== 恢复到演练库 ==\n'
restore_out="$(bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" --archive "${ARCHIVE}" \
  --target-db mogo_drill --drop --yes 2>&1)" || fail "恢复失败：${restore_out}"
assert_contains "${restore_out}" "校验和一致" "恢复前校验和"
assert_contains "${restore_out}" "恢复后一致性校验通过" "恢复后一致性校验"
assert_eq "$(printf '%s\n' "${restore_out}" | tail -1)" "mogo_drill" "恢复目标库回显"

# 演练库内容与源库一致（替身把 mogo 原样复制到 mogo_drill）
drill_state="$(python3 - "${FAKE_MONGO_STATE}" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
drill = state.get("mogo_drill", {})
print(",".join(f"{name}:{len(docs)}" for name, docs in sorted(drill.items())))
PY
)"
assert_eq "${drill_state}" "posts:2,users:3" "演练库文档数"

# ── 2. 密文被篡改 → 校验和不匹配 ───────────────────────────────────────
printf '== 密文篡改 ==\n'
tampered="${WORK}/tampered.archive.gz.enc"
cp "${ARCHIVE}" "${tampered}"
cp "${ARCHIVE}.sha256" "${tampered}.sha256"
cp "$(mogo_backup_manifest_name "${ARCHIVE}")" "$(mogo_backup_manifest_name "${tampered}")"
printf 'X' >>"${tampered}"
: >"${FAKE_MONGO_CALLS}"
set +e
tamper_out="$(bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" --archive "${tampered}" --target-db mogo_tamper --drop --yes 2>&1)"
tamper_status=$?
set -e
[[ "${tamper_status}" != "0" ]] || fail "密文被篡改后仍恢复成功"
assert_contains "${tamper_out}" "校验和不匹配" "篡改的报错"
if grep -q '^mongorestore' "${FAKE_MONGO_CALLS}"; then
  fail "校验和失败后不应调用 mongorestore"
fi

# ── 3. 口令错误 → 解密失败 ─────────────────────────────────────────────
printf '== 口令错误 ==\n'
printf '%s' "wrong-passphrase" >"${WORK}/bad.pass"
set +e
MOGO_BACKUP_PASSPHRASE="" MOGO_BACKUP_PASSPHRASE_FILE="${WORK}/bad.pass" bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" \
  --archive "${ARCHIVE}" --target-db mogo_badpass --drop --yes >"${WORK}/badpass.out" 2>&1
badpass_status=$?
set -e
[[ "${badpass_status}" != "0" ]] || fail "错误口令仍恢复成功"
badpass_body="$(cat "${WORK}/badpass.out")"
assert_contains "${badpass_body}" "bad decrypt" "错误口令应卡在解密阶段"

# ── 3b. 明文摘要兜底：AES-CBC 无认证，口令对但内容对不上时必须拦下 ────
printf '== 明文摘要兜底 ==\n'
# 构造：密文与校验和都是自洽的（能通过第一步校验和），但解密出来的明文
# 不是清单里记录的那一份。这模拟"密文被换掉/写着写着写错了"的故障。
sha_case_dir="${WORK}/sha-case"
mkdir -p "${sha_case_dir}"
sha_archive="${sha_case_dir}/$(basename "${ARCHIVE}")"
pass_file="${WORK}/good.pass"
printf '%s' "${MOGO_BACKUP_PASSPHRASE}" >"${pass_file}"
printf 'TAMPERED-PLAINTEXT' >"${WORK}/tampered.raw"
MOGO_BACKUP_PASSPHRASE_FILE="${pass_file}" \
  bash -c 'source "${0}/scripts/backup/lib.sh"; mogo_backup_encrypt "${1}" "${2}" "${3}"' \
  "${ROOT_DIR}" "${WORK}/tampered.raw" "${sha_archive}" "${pass_file}"
sha_sum="$(mogo_backup_sha256 "${sha_archive}")"
printf '%s  %s\n' "${sha_sum}" "$(basename "${sha_archive}")" >"${sha_archive}.sha256"
cp "$(mogo_backup_manifest_name "${ARCHIVE}")" "$(mogo_backup_manifest_name "${sha_archive}")"
set +e
sha_out="$(bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" --archive "${sha_archive}" \
  --target-db mogo_shacheck --drop --yes 2>&1)"
sha_status=$?
set -e
[[ "${sha_status}" != "0" ]] || fail "明文摘要不匹配时仍恢复成功"
assert_contains "${sha_out}" "解密后内容校验失败" "明文摘要兜底的报错"

# ── 4. 目标库非空且未确认 → 拒绝 ───────────────────────────────────────
printf '== 目标库非空保护 ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1", "u2", "u3"], "posts": ["p1", "p2"]}}'
set +e
nonempty_out="$(bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" --archive "${ARCHIVE}" 2>&1)"
nonempty_status=$?
set -e
[[ "${nonempty_status}" != "0" ]] || fail "目标库非空且未确认时仍恢复"
assert_contains "${nonempty_out}" "目标库" "非空保护的报错"

# ── 5. 恢复少一条 → 一致性校验失败 ─────────────────────────────────────
printf '== 数据缺失被捕获 ==\n'
set +e
truncate_out="$(FAKE_RESTORE_TRUNCATE=1 bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" \
  --archive "${ARCHIVE}" --target-db mogo_short --drop --yes 2>&1)"
truncate_status=$?
set -e
[[ "${truncate_status}" != "0" ]] || fail "少恢复一条时仍报成功"
assert_contains "${truncate_out}" "一致性校验失败" "缺失数据的报错"

# ── 6. --consistency-only 只校验不写库 ─────────────────────────────────
printf '== 只校验模式 ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1", "u2", "u3"], "posts": ["p1", "p2"]}}'
: >"${FAKE_MONGO_CALLS}"
consistency_out="$(bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" --archive "${ARCHIVE}" \
  --target-db mogo --consistency-only 2>&1)" || fail "只校验模式失败：${consistency_out}"
assert_contains "${consistency_out}" "一致性校验通过" "只校验模式的结论"
if grep -q '^mongorestore' "${FAKE_MONGO_CALLS}"; then
  fail "--consistency-only 不应调用 mongorestore"
fi

# ── 7. 从异地副本恢复 ──────────────────────────────────────────────────
printf '== 异地副本恢复 ==\n'
offsite_name="$(basename "${ARCHIVE}")"
# 先把本地备份目录挪走，确保只能靠异地副本
mv "${MOGO_BACKUP_DIR}" "${WORK}/backups-away"
set +e
offsite_out="$(bash "${ROOT_DIR}/scripts/backup/restore_mongo.sh" --archive "${offsite_name}" \
  --from-offsite --target-db mogo_offsite --drop --yes 2>&1)"
offsite_status=$?
set -e
[[ "${offsite_status}" == "0" ]] || fail "从异地副本恢复失败：${offsite_out}"
assert_contains "${offsite_out}" "一致性校验通过" "异地恢复后的一致性校验"
mv "${WORK}/backups-away" "${MOGO_BACKUP_DIR}"

printf 'Restore behaviour is valid.\n'
