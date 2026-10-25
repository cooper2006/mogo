#!/usr/bin/env bash
# 024 T022 (FR-011)：配置清单键 ↔ 代码读取点双向一致性校验。
#
# 校验目标：deploy/config/{dev,staging,prod}.yml 中登记的每条配置键，
#   1) schema 字段齐全（key/env/purpose/required/source/default/allowed/codeRef）；
#   2) codeRef 指向 services/<svc>/app/core/config.py 中**真实存在**的字段声明行，
#      且该字段名与清单 key（去 env_prefix、不区分大小写）一致 —— 防止 codeRef 漂移；
#   3) required: true 的键必须填 codeRef（未登记必填键 = 部署漏配风险，退出非零并输出键名）；
#   4) 生产环境（--env prod）敏感键（env 名含 SECRET/PASSWORD/KEY/TOKEN）的
#      source 必须是 deployment-secrets（不允许来源明文）。
#
# 用法：
#   deploy/cli/config-lint.sh [--env all|dev|staging|prod] [--services a,b,c]
# 退出码：0 = 通过；1 = 发现不一致（输出明细到 stdout）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${ROOT_DIR}/deploy/config"

ENV_SELECT="all"
SERVICE_SELECT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_SELECT="$2"
      shift 2
      ;;
    --services)
      SERVICE_SELECT="$2"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "${CONFIG_DIR}" ]]; then
  echo "config-lint: 配置清单目录不存在: ${CONFIG_DIR}" >&2
  exit 2
fi

export CONFIG_DIR ENV_SELECT SERVICE_SELECT
python3 - <<'PY'
import os, re, sys, pathlib
import yaml

config_dir = pathlib.Path(os.environ["CONFIG_DIR"])
env_select = os.environ["ENV_SELECT"]
service_select = (os.environ["SERVICE_SELECT"].split(",") if os.environ["SERVICE_SELECT"] else None)
root = config_dir.parents[1]

REQUIRED_FIELDS = ["key","env","purpose","required","source","default","allowed","codeRef"]
SENSITIVE_SUFFIXES = ("_SECRET","_PASSWORD","_KEY","_TOKEN")
SENSITIVE_MARKERS = ("API_KEY","ACCESS_KEY_ID","PRIVATE_KEY")

env_files = [p for p in sorted(config_dir.glob("*.yml")) if p.stem in ("dev","staging","prod")]
if env_select != "all":
    env_files = [p for p in env_files if p.stem == env_select]
if not env_files:
    print(f"config-lint: 无匹配环境清单 (--env={env_select})", file=sys.stderr)
    sys.exit(2)

problems, warnings, checked = [], [], 0

def declared_field(lineno):
    """取 codeRef 行号所在行的字段声明名；不是字段声明行则返回 None。"""
    m = re.match(r"\s{2,}([A-Za-z_][A-Za-z0-9_]*)\s*:", lineno)
    return m.group(1) if m else None

for env_file in env_files:
    env_name = env_file.stem
    try:
        data = yaml.safe_load(env_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"[{env_name}] {env_file.name}: YAML 解析失败 {exc}")
        continue
    if not isinstance(data, dict):
        problems.append(f"[{env_name}] {env_file.name}: 顶层不是映射")
        continue
    if data.get("version") != 1:
        problems.append(f"[{env_name}] {env_file.name}: 缺 version: 1")
    services = data.get("services") or {}
    if not isinstance(services, dict):
        problems.append(f"[{env_name}] {env_file.name}: 缺 services 段")
        continue
    for svc, svc_def in services.items():
        if service_select and svc not in service_select:
            continue
        if not isinstance(svc_def, dict):
            problems.append(f"[{env_name}] services.{svc}: 非映射")
            continue
        settings = svc_def.get("settings") or []
        prefix = svc_def.get("env_prefix", "") or ""
        if not isinstance(settings, list):
            problems.append(f"[{env_name}] services.{svc}.settings: 非列表")
            continue
        for item in settings:
            checked += 1
            if not isinstance(item, dict):
                problems.append(f"[{env_name}] services.{svc}: 条目非映射")
                continue
            missing = [f for f in REQUIRED_FIELDS if f not in item]
            if missing:
                problems.append(
                    f"[{env_name}] services.{svc} key={item.get('key','?')}: 缺字段 {missing}")
                continue
            key, env_name_full = item["key"], item["env"]
            required = bool(item["required"])
            # 3) required 必填键必须有 codeRef
            code_ref = str(item.get("codeRef") or "").strip()
            if required and not code_ref:
                problems.append(
                    f"[{env_name}] services.{svc} {key}: required=true 但 codeRef 为空（未登记必填键）")
                continue
            if not code_ref:
                continue
            # 2) codeRef 指向真实字段
            if ":" not in code_ref:
                problems.append(f"[{env_name}] services.{svc} {key}: codeRef 格式应为 path:line -> {code_ref}")
                continue
            rel_path, _, line_str = code_ref.rpartition(":")
            target = root / rel_path
            if not target.exists():
                problems.append(f"[{env_name}] services.{svc} {key}: codeRef 文件不存在 {rel_path}")
                continue
            try:
                lineno = int(line_str)
            except ValueError:
                problems.append(f"[{env_name}] services.{svc} {key}: codeRef 行号非法 {line_str}")
                continue
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            if lineno < 1 or lineno > len(lines):
                problems.append(
                    f"[{env_name}] services.{svc} {key}: codeRef 行号越界 {rel_path}:{lineno} (共 {len(lines)} 行)")
                continue
            field = declared_field(lines[lineno - 1])
            if field is None:
                problems.append(
                    f"[{env_name}] services.{svc} {key}: codeRef 指向非字段声明行 {rel_path}:{lineno} -> {lines[lineno-1].strip()[:60]}")
                continue
            # 字段名与 key（去 env_prefix，不区分大小写）一致
            normalized = field.lower()
            if prefix:
                if not env_name_full.startswith(prefix):
                    problems.append(
                        f"[{env_name}] services.{svc} {key}: env {env_name_full} 缺少声明前缀 {prefix}")
                    continue
                suffix = env_name_full[len(prefix):].lower()
            else:
                suffix = env_name_full.lower()
            if normalized != suffix:
                problems.append(
                    f"[{env_name}] services.{svc} {key}: 字段名 {field}({rel_path}:{lineno}) 与 env 后缀 {suffix} 不一致")
            # 4) 生产敏感键 source 必须是 deployment-secrets
            upper_env = env_name_full.upper()
            is_sensitive = (upper_env.endswith(SENSITIVE_SUFFIXES)
                            or any(m in upper_env for m in SENSITIVE_MARKERS))
            if env_name == "prod" and is_sensitive:
                src = str(item.get("source") or "").lower()
                if "secret" not in src and "vault" not in src and "deployment-secrets" not in src:
                    problems.append(
                        f"[{env_name}] services.{svc} {key}: 敏感键 source={item.get('source')} 不是 deployment-secrets")
    # required 键数量统计
    req_count = sum(
        1 for sd in services.values()
        if isinstance(sd, dict) for s in (sd.get("settings") or []) if isinstance(s, dict) and s.get("required"))
    print(f"config-lint: [{env_name}] {len(services)} 服务 / {req_count} 个 required 键")

print(f"config-lint: 共校验 {checked} 条配置条目")
for p in problems:
    print(f"  FAIL  {p}")
for w in warnings:
    print(f"  WARN  {w}")
if problems:
    print(f"config-lint: FAIL — {len(problems)} 处不一致")
    sys.exit(1)
print("config-lint: OK — 配置清单与代码读取点一致")
PY
exit $?