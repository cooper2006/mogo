#!/usr/bin/env bash
# 024 T065 (FR-035)：备份归档加解密单测。
# 用法：bash scripts/test_backup_encrypt.sh
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_BIN="${DOCKER_BIN:-docker}"
# shellcheck source=../deploy/cli/backup.sh
source "${ROOT_DIR}/deploy/cli/backup.sh"

fail=0
ok()   { echo "  OK   $1"; }
bad()  { echo "  FAIL $1"; fail=1; }

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

echo "== 1. 未配置密钥 → 不加密（兼容旧明文备份）=="
mkdir -p "${tmp}/plain"
echo "hello" > "${tmp}/plain/deployment-secrets.tar.gz"
MOGO_BACKUP_KEY="" MOGO_BACKUP_KEY_FILE="" \
  mogo_backup_encrypt_dir "${tmp}/plain" >/dev/null
if [[ -f "${tmp}/plain/deployment-secrets.tar.gz" ]]; then
  ok "明文保留（未启用加密）"
else
  bad "明文被删除（不应发生）"
fi

echo "== 2. 配置密钥 → 加密归档 =="
mkdir -p "${tmp}/src"
printf 'payload-mongo\n' > "${tmp}/src/mongo-data.tar.gz"
printf 'payload-secrets\n' > "${tmp}/src/deployment-secrets.tar.gz"
export MOGO_BACKUP_KEY="unit-test-key-123"
export MOGO_BACKUP_KEEP_PLAIN=0
mogo_backup_encrypt_dir "${tmp}/src" >/dev/null
if [[ -f "${tmp}/src/mongo-data.tar.gz.enc" && -f "${tmp}/src/deployment-secrets.tar.gz.enc" ]]; then
  ok "生成 .enc 归档"
else
  bad "缺少 .enc 归档"
fi
if [[ ! -f "${tmp}/src/mongo-data.tar.gz" ]]; then
  ok "明文归档已删除（KEEP_PLAIN=0）"
else
  bad "明文归档仍存在"
fi
if [[ "$(tr -d '\r\n' < "${tmp}/src/ENCRYPTED")" == "true" ]]; then
  ok "ENCRYPTED=true 标记"
else
  bad "ENCRYPTED 标记缺失"
fi
if [[ -s "${tmp}/src/KEY_SHA256_PREFIX" && -s "${tmp}/src/BACKUP_CIPHER" && -s "${tmp}/src/SHA256SUMS" ]]; then
  ok "密钥指纹 / 算法 / 校验和元数据齐全"
else
  bad "加密元数据不完整"
fi
if ! gzip -t "${tmp}/src/mongo-data.tar.gz.enc" 2>/dev/null; then
  ok "加密文件不再是有效 gzip（防误当明文恢复）"
else
  bad "加密文件仍是有效 gzip"
fi

echo "== 3. 正确密钥 → 解密恢复原文 =="
work="$(mktemp -d "${tmp}/work.XXXXXX")"
mogo_backup_decrypt_dir "${tmp}/src" "${work}" >/dev/null
if diff -q <(printf 'payload-mongo\n') "${work}/mongo-data.tar.gz" >/dev/null 2>&1; then
  ok "解密内容与原 payload 一致"
else
  bad "解密内容不一致"
fi
if [[ -s "${work}/SHA256SUMS" ]]; then
  ok "解密目录生成 SHA256SUMS"
else
  bad "解密目录缺 SHA256SUMS"
fi
if ( cd "${work}" && mogo_sha256_verify >/dev/null 2>&1 ); then
  ok "解密目录 SHA256SUMS 校验通过"
else
  bad "解密目录 SHA256SUMS 校验失败"
fi

echo "== 4. 错误密钥 → 解密被拒（指纹校验）=="
work2="$(mktemp -d "${tmp}/work2.XXXXXX")"
export MOGO_BACKUP_KEY="wrong-key"
if mogo_backup_decrypt_dir "${tmp}/src" "${work2}" >/dev/null 2>&1; then
  bad "错误密钥未被拒绝"
else
  ok "错误密钥导致解密失败"
fi

echo "== 5. 无密钥时恢复加密备份 → 明确失败 =="
export MOGO_BACKUP_KEY="" MOGO_BACKUP_KEY_FILE=""
work3="$(mktemp -d "${tmp}/work3.XXXXXX")"
if mogo_backup_decrypt_dir "${tmp}/src" "${work3}" >/dev/null 2>&1; then
  bad "无密钥未报错"
else
  ok "无密钥时报错退出"
fi

echo
if [[ ${fail} -eq 0 ]]; then
  echo "ALL PASS"
else
  echo "SOME FAILED"
fi
exit ${fail}