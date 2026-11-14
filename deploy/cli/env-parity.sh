#!/usr/bin/env bash
# 024 T035 (FR-014)：各环境部署一致性校验。
#
# 校验 deploy/docker-compose.prod.yml（生产覆盖）对根 docker-compose.yml 的覆盖
# 是否遵守"同一制品"约束：覆盖文件 MUST NOT 修改任何服务的 image（差异仅限配置层）。
# 同时对每个被覆盖服务输出"配置层差异"摘要，便于预审确认差异确实只在配置。
#
# 用法：
#   deploy/cli/env-parity.sh [--prod <path>] [--json]
# 退出码：0 = 一致（同制品）；1 = 覆盖文件改了 image；2 = 用法/解析错误。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_COMPOSE="${ROOT_DIR}/docker-compose.yml"
PROD_COMPOSE="${ROOT_DIR}/deploy/docker-compose.prod.yml"

OUTPUT_JSON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod) PROD_COMPOSE="$2"; shift 2 ;;
    --json) OUTPUT_JSON=true; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "${PROD_COMPOSE}" ]]; then
  echo "env-parity: 未找到生产覆盖文件 ${PROD_COMPOSE}" >&2
  exit 2
fi

export ROOT_DIR BASE_COMPOSE PROD_COMPOSE OUTPUT_JSON
python3 - <<'PY'
import json, os, subprocess, sys

base = os.environ["BASE_COMPOSE"]
prod = os.environ["PROD_COMPOSE"]
output_json = os.environ["OUTPUT_JSON"] == "true"

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

import yaml

def compose_services(path):
    """读基础 compose 的 services 段（yaml 直读，避免 profile/插值过滤掉服务）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        print(f"env-parity: {path} 解析失败: {exc}", file=sys.stderr)
        sys.exit(2)
    return doc.get("services") or {}

base_svc = compose_services(base)

# 单独解析 prod 覆盖（不能脱离 base 独立 config，因为 prod 可能引用 base 的卷/网络）
# 这里直接读 YAML 顶层，只关心 services 段
with open(prod, encoding="utf-8") as fh:
    prod_doc = yaml.safe_load(fh)
prod_services = prod_doc.get("services") or {}

# 允许的"配置层"字段（覆盖可修改）；image 必须来自基础文件（同一制品）
CONFIG_ONLY_KEYS = {
    "environment", "env_file", "replicas", "deploy", "ports", "volumes",
    "networks", "resources", "depends_on", "restart", "healthcheck",
    "logging", "labels", "extra_hosts", "dns", "secrets", "configs",
    "read_only", "tmpfs", "cap_drop", "cap_add", "no_new_privileges",
    "user", "command", "entrypoint", "working_dir", "init", "stop_grace_period",
    "platform", "privileged", "security_opt", "ulimits", "stdin_open",
    "tty", "container_name", "hostname", "domainname", "profiles",
}

problems, layer_diffs = [], []
for svc, override in prod_services.items():
    if svc not in base_svc:
        problems.append(f"{svc}: 覆盖文件新增了基础文件没有的服务（基础 compose 未声明该服务）")
        continue
    if not isinstance(override, dict):
        continue
    for key in override.keys():
        if key in ("image", "build", "pull_policy"):
            problems.append(f"{svc}: 覆盖文件修改了制品层字段 `{key}`（违反 FR-014 同一制品）")
        elif key not in CONFIG_ONLY_KEYS:
            layer_diffs.append(f"{svc}: 未知覆盖字段 `{key}`（不在配置层白名单，请复核）")

# 汇总：每个被覆盖服务列出配置层字段
covered = sorted(prod_services.keys())
for svc in covered:
    keys = sorted(k for k in (prod_services.get(svc) or {}).keys() if k in CONFIG_ONLY_KEYS)
    if keys:
        layer_diffs.append(f"{svc}: 配置层覆盖 {keys}")

if output_json:
    print(json.dumps({"covered_services": covered, "problems": problems,
                      "config_layer_diffs": layer_diffs}, ensure_ascii=False, indent=2))
else:
    print(f"env-parity: 生产覆盖涉及 {len(covered)} 服务")
    for d in layer_diffs:
        print(f"  INFO  {d}")
    for p in problems:
        print(f"  FAIL  {p}")
    if problems:
        print(f"env-parity: FAIL — 覆盖文件违反 FR-014 同一制品约束")
        sys.exit(1)
    print("env-parity: OK — 各环境使用同一制品，差异仅存在于配置层")
PY
exit $?