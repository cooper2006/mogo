#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/test_mongo_backup.sh — 备份行为测试（T109）
# ═══════════════════════════════════════════════════════════════════════
#
# 覆盖：
#   1. 全量/小时级两种模式的产物命名、清单字段、校验和文件
#   2. 加密真的用了口令（错口令解不开、对口令能解出原文）
#   3. 没配口令时直接失败、且**不调用 mongodump**（避免白跑十分钟）
#   4. mongodump 产出为空时拒绝入库
#   5. 异地上传：配置了就传、没配就告警但仍成功
#   6. 定时配置（T096）里小时级与每日全量的频率、清理与演练任务存在
#
# 依赖假 mongodump/mongosh（scripts/testlib/fake_mongo.sh），不需要真 MongoDB。
# 运行：bash scripts/test_mongo_backup.sh
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

assert_file_exists() {
  [[ -e "$1" ]] || fail "$2: 期望文件存在，实际缺失（$1）"
}

assert_file_missing() {
  [[ ! -e "$1" ]] || fail "$2: 期望文件不存在，实际存在（$1）"
}

# 从清单取字段（顶层或 "a.b" 形式）
manifest_field() {
  python3 - "$1" "$2" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
value = data
for part in sys.argv[2].split("."):
    if not isinstance(value, dict):
        value = None
        break
    value = value.get(part)
print("" if value is None else value)
PY
}

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mogo-backup-test.XXXXXX")"
export MOGO_BACKUP_DIR="${WORK}/backups"
export MOGO_BACKUP_OFFSITE_DIR="${WORK}/offsite"
export MOGO_MONGODB_URI="mongodb://mongo:27017"
export MOGO_BACKUP_PASSPHRASE="test-passphrase-do-not-use-in-prod"

cleanup() {
  fake_mongo_cleanup
  rm -rf "${WORK}"
}
trap cleanup EXIT

fake_mongo_init
PATH="${FAKE_MONGO_BIN}:${PATH}"
export PATH

# ── 1. 全量备份：产物、清单、校验和、异地上传 ───────────────────────────
printf '== 全量备份 ==\n'
out="$(bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full 2>&1)" || fail "全量备份失败：${out}"
archive_path="$(printf '%s\n' "${out}" | tail -1)"
full_dump_call="$(grep "^mongodump" "${FAKE_MONGO_CALLS}" | head -1)"
assert_file_exists "${archive_path}" "全量备份归档"
case "${archive_path}" in
  */mongo-mogo-full-*.archive.gz.enc) : ;;
  *) fail "备份文件命名不符合 mongo-<db>-<mode>-<stamp>.archive.gz.enc：${archive_path}" ;;
esac
manifest="${archive_path%.enc}.json"
assert_file_exists "${manifest}" "备份清单"
assert_file_exists "${archive_path}.sha256" "校验和文件"

assert_eq "$(manifest_field "${manifest}" mode)" "full" "清单 mode"
assert_eq "$(manifest_field "${manifest}" db)" "mogo" "清单 db"
assert_eq "$(manifest_field "${manifest}" encryption.cipher)" "aes-256-cbc" "清单 cipher"
assert_eq "$(manifest_field "${manifest}" encryption.kdf)" "pbkdf2" "清单 kdf"
assert_eq "$(manifest_field "${manifest}" encryption.passphrase_source)" "env" "清单记录密钥来源"
assert_eq "$(manifest_field "${manifest}" offsite_status)" "uploaded" "清单记录异地上传状态"

collections="$(python3 - "$manifest" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(",".join(f'{item["name"]}:{item["count"]}' for item in data["collections"]))
PY
)"
assert_eq "${collections}" "posts:2,users:3" "清单集合与文档数"

# 校验和真的对应密文
expected_sha="$(awk '{print $1}' "${archive_path}.sha256")"
actual_sha="$(mogo_backup_sha256 "${archive_path}")"
assert_eq "${actual_sha}" "${expected_sha}" "校验和与密文一致"

# 异地副本存在且与本地一致
offsite_archive="${MOGO_BACKUP_OFFSITE_DIR}/$(basename "${archive_path}")"
assert_file_exists "${offsite_archive}" "异地副本"
assert_eq "$(mogo_backup_sha256 "${offsite_archive}")" "${actual_sha}" "异地副本校验和"
assert_file_exists "${MOGO_BACKUP_OFFSITE_DIR}/$(basename "${manifest}")" "异地清单"

# ── 2. 加密确实用了口令 ────────────────────────────────────────────────
printf '== 加密强度 ==\n'
good_pass="$(mktemp "${TMPDIR:-/tmp}/good.XXXXXX")"
bad_pass="$(mktemp "${TMPDIR:-/tmp}/bad.XXXXXX")"
printf '%s' "${MOGO_BACKUP_PASSPHRASE}" >"${good_pass}"
printf '%s' "wrong-passphrase" >"${bad_pass}"

if mogo_backup_decrypt "${archive_path}" "${WORK}/bad.out" "${bad_pass}" 2>/dev/null; then
  fail "错误口令竟然解密成功：加密形同虚设"
fi
mogo_backup_decrypt "${archive_path}" "${WORK}/good.out" "${good_pass}"
assert_contains "$(head -1 "${WORK}/good.out")" "FAKE-MONGO-DUMP" "对口令解出的明文"

# 明文里不应出现口令本身（AES 之外的最低要求：没有把口令写进密文）
if grep -q "test-passphrase-do-not-use-in-prod" "${archive_path}" 2>/dev/null; then
  fail "密文里出现明文口令"
fi
rm -f "${good_pass}" "${bad_pass}"

# ── 3. 没配口令：失败且不调用 mongodump ────────────────────────────────
printf '== 缺少口令 ==\n'
before_calls="$(grep -c '^mongodump' "${FAKE_MONGO_CALLS}" || true)"
set +e
no_pass_out="$(env -u MOGO_BACKUP_PASSPHRASE -u MOGO_BACKUP_PASSPHRASE_FILE \
  bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full 2>&1)"
no_pass_status=$?
set -e
[[ "${no_pass_status}" != "0" ]] || fail "缺少口令时备份应失败，实际退出码 0"
assert_contains "${no_pass_out}" "未提供备份口令" "缺少口令的报错文案"
after_calls="$(grep -c '^mongodump' "${FAKE_MONGO_CALLS}" || true)"
assert_eq "${after_calls}" "${before_calls}" "缺口令时不应调用 mongodump"

# ── 4. 空 dump 被拒绝 ──────────────────────────────────────────────────
printf '== 空 dump ==\n'
set +e
empty_out="$(FAKE_DUMP_EMPTY=1 bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full 2>&1)"
empty_status=$?
set -e
[[ "${empty_status}" != "0" ]] || fail "空 dump 应失败"
assert_contains "${empty_out}" "拒绝写入空备份" "空 dump 的报错文案"
if ls "${MOGO_BACKUP_DIR}"/mongo-mogo-full-*.archive.gz.enc >/dev/null 2>&1; then
  count_enc="$(ls "${MOGO_BACKUP_DIR}"/mongo-mogo-full-*.archive.gz.enc | wc -l | tr -d ' ')"
  assert_eq "${count_enc}" "1" "空 dump 不应留下第二份归档"
fi

# ── 5. 小时级模式带 --oplog ────────────────────────────────────────────
printf '== oplog 模式 ==\n'
: >"${FAKE_MONGO_CALLS}"
oplog_out="$(bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode oplog 2>&1)" || fail "oplog 备份失败：${oplog_out}"
oplog_archive="$(printf '%s\n' "${oplog_out}" | tail -1)"
case "${oplog_archive}" in
  */mongo-mogo-oplog-*) : ;;
  *) fail "oplog 备份命名错误：${oplog_archive}" ;;
esac
calls="$(fake_mongo_calls)"
assert_contains "${calls}" "--oplog" "oplog 模式应带 --oplog"
# 全量模式那次不应该带 --oplog（上面第 1 步已把这次调用留存下来）
case "${full_dump_call}" in
  *--oplog*) fail "全量模式不应带 --oplog" ;;
esac

# ── 6. 未配置异地：告警但成功 ──────────────────────────────────────────
printf '== 未配置异地 ==\n'
env -u MOGO_BACKUP_OFFSITE_DIR -u MOGO_BACKUP_OFFSITE_RCLONE_REMOTE \
  bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full >"${WORK}/no-offsite.out" 2>&1 \
  || fail "未配置异地时备份应仍然成功"
assert_contains "$(cat "${WORK}/no-offsite.out")" "跳过异地上传" "未配置异地的告警"
no_offsite_archive="$(tail -1 "${WORK}/no-offsite.out")"
assert_eq "$(manifest_field "$(mogo_backup_manifest_name "${no_offsite_archive}")" offsite_status)" \
  "not-configured" "未配置异地时的清单状态"

# ── 7. dry-run 不写文件 ────────────────────────────────────────────────
printf '== dry-run ==\n'
count_before="$(ls "${MOGO_BACKUP_DIR}"/mongo-*.archive.gz.enc | wc -l | tr -d ' ')"
dry_out="$(bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full --dry-run 2>&1)" || fail "dry-run 失败：${dry_out}"
count_after="$(ls "${MOGO_BACKUP_DIR}"/mongo-*.archive.gz.enc | wc -l | tr -d ' ')"
assert_eq "${count_after}" "${count_before}" "dry-run 不产生新备份"

# ── 8. 定时配置（T096） ────────────────────────────────────────────────
printf '== 定时配置 ==\n'
cron="${ROOT_DIR}/scripts/backup/crontab.example"
assert_file_exists "${cron}" "crontab 示例"
cron_body="$(cat "${cron}")"
assert_contains "${cron_body}" "backup_mongo.sh --mode oplog" "小时级任务"
assert_contains "${cron_body}" "backup_mongo.sh --mode full" "每日全量任务"
assert_contains "${cron_body}" "rotate_backups.sh" "清理任务"
assert_contains "${cron_body}" "drill_recovery.sh --from-offsite" "演练任务"
assert_contains "${cron_body}" "*/15 * * * *" "小时级频率为每 15 分钟"
assert_contains "${cron_body}" "30 2 * * *" "每日全量频率"
if printf '%s' "${cron_body}" | grep -q "PASSPHRASE="; then
  fail "crontab 示例里出现了口令赋值"
fi

printf 'Backup behaviour is valid.\n'
