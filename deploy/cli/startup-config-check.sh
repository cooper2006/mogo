#!/usr/bin/env bash
# 024 T037 (FR-015)：启动期必填配置键校验，失败输出键名 + 期望取值范围。
#
# 依据 deploy/config/{dev,staging,prod}.yml（T020-T022 建立的权威清单）中
# `required: true` 的条目，校验对应环境变量是否已设且非空；缺失则逐条输出
# 键名 / 期望说明 / 取值范围 / 来源，并退出非零，使容器拒绝带病启动。
#
# 由 `mogo up` 在拉起容器前调用（见 deploy/cli/i18n.sh 的 up 流程），也可单独运行：
#   deploy/cli/startup-config-check.sh [--env dev|staging|prod] [--json]
# 退出码：0 = 必填键齐全；1 = 缺失必填键；2 = 用法/清单错误。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${ROOT_DIR}/deploy/config"

ENV_NAME="prod"
OUTPUT_JSON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --json) OUTPUT_JSON=true; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ "${ENV_NAME}" != "dev" && "${ENV_NAME}" != "staging" && "${ENV_NAME}" != "prod" ]]; then
  echo "startup-config-check: --env 须为 dev|staging|prod，得到 ${ENV_NAME}" >&2
  exit 2
fi

manifest="${CONFIG_DIR}/${ENV_NAME}.yml"
if [[ ! -f "${manifest}" ]]; then
  echo "startup-config-check: 未找到配置清单 ${manifest}" >&2
  exit 2
fi

export ROOT_DIR CONFIG_DIR ENV_NAME OUTPUT_JSON
python3 - <<'PY'
import json, os, sys
import yaml

manifest = os.path.join(os.environ["CONFIG_DIR"], f"{os.environ['ENV_NAME']}.yml")
output_json = os.environ["OUTPUT_JSON"] == "true"

with open(manifest, encoding="utf-8") as fh:
    doc = yaml.safe_load(fh)

required = []
for svc, svc_def in (doc.get("services") or {}).items():
    prefix = svc_def.get("env_prefix", "") or ""
    for item in (svc_def.get("settings") or []):
        if not item.get("required"):
            continue
        env_name = item.get("env") or ""
        required.append({
            "service": svc,
            "key": item.get("key"),
            "env": env_name,
            "purpose": item.get("purpose", ""),
            "allowed": item.get("allowed", ""),
            "source": item.get("source", ""),
            "prefix": prefix,
        })

missing = []
present = []
for r in required:
    value = os.environ.get(r["env"], "")
    if value == "" or value is None:
        missing.append(r)
    else:
        present.append(r)

if output_json:
    print(json.dumps({"env": os.environ["ENV_NAME"], "required_total": len(required),
                      "present": len(present), "missing": missing}, ensure_ascii=False, indent=2))
else:
    print(f"startup-config-check: [{os.environ['ENV_NAME']}] 必填键 {len(required)} 个，已满足 {len(present)} 个")
    for r in missing:
        allowed = r["allowed"] if isinstance(r["allowed"], str) else json.dumps(r["allowed"], ensure_ascii=False)
        print(f"  MISSING  {r['service']}.{r['key']}  env={r['env']}")
        print(f"          用途: {r['purpose']}")
        print(f"          取值范围: {allowed or '(未限定)'}   来源: {r['source'] or '(环境变量)'}")

if missing:
    print(f"startup-config-check: FAIL — {len(missing)} 个必填键缺失，拒绝启动。"
          f"请按上方键名设置环境变量（来源: {os.environ['ENV_NAME']} 配置清单）。")
    sys.exit(1)
print("startup-config-check: OK — 必填配置键齐全，可启动。")
PY
exit $?