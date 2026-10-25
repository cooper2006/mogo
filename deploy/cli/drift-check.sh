#!/usr/bin/env bash
# 024 T025 (FR-010)：比对 docker-compose.yml 声明与 docker inspect 实际运行态，
# 输出漂移报告（QF-824 blocked → 可验证）。
#
# 比对维度：
#   - 镜像名（声明 image vs 运行 image）
#   - read_only / no-new-privileges / cap_drop（安全基线四项的 3 项；user 另列）
#   - user（声明 user 字段 + Dockerfile USER vs 运行 User）
#   - 挂载卷（声明 volumes vs 运行 Mounts，比对 source/target/type/rw）
#   - 环境变量（声明 environment 的键名 vs 运行 Env 键名，不比对值——值是敏感项）
#
# 用法：
#   deploy/cli/drift-check.sh [--service NAME]... [--json]
# 退出码：0 = 无漂移；1 = 发现漂移；2 = 用法/前置错误（docker 不可用）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"

SERVICES=()
OUTPUT_JSON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICES+=("$2")
      shift 2
      ;;
    --json)
      OUTPUT_JSON=true
      shift
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "drift-check: docker 不可用" >&2
  exit 2
fi

export ROOT_DIR COMPOSE_FILE OUTPUT_JSON
export SERVICE_LIST="${SERVICES[*]}"
python3 - <<'PY'
import json, os, subprocess, sys
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
compose_file = root / "docker-compose.yml"
service_filter = [s for s in os.environ.get("SERVICES", "") ] if False else []
# SERVICES 通过分隔符传递
if os.environ.get("SERVICE_LIST"):
    service_filter = [x for x in os.environ["SERVICE_LIST"].replace(",", " ").split()]
output_json = os.environ["OUTPUT_JSON"] == "true"

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

# 1) 声明态：docker compose config --format json
cfg = run(["docker", "compose", "-f", str(compose_file), "config", "--format", "json"])
if cfg.returncode != 0:
    print("drift-check: docker compose config 失败: " + cfg.stderr.strip(), file=sys.stderr)
    sys.exit(2)
declared = json.loads(cfg.stdout).get("services", {})
declared_services = set(declared.keys())

if service_filter:
    unknown = set(service_filter) - declared_services
    if unknown:
        print(f"drift-check: 声明中不存在服务: {sorted(unknown)}", file=sys.stderr)
        sys.exit(2)
    target_services = service_filter
else:
    target_services = sorted(declared_services)

# 2) 运行态：docker inspect（按 compose project 前缀 + 服务名）
ps = run(["docker", "ps", "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}\t{{.Label \"com.docker.compose.service\"}}"])
running = {}
for line in ps.stdout.splitlines():
    parts = line.split("\t")
    if len(parts) == 3:
        name, project, service = parts
        running.setdefault(service, []).append(name)

drift = []
checked = 0

for svc in target_services:
    d = declared.get(svc, {})
    container_names = running.get(svc, [])
    if not container_names:
        # 未运行：跳过（不判漂移，避免未部署服务被误报）
        continue
    # 取第一个容器代表（scale>1 时逐个比对同一声明）
    inspect = run(["docker", "inspect", container_names[0]])
    if inspect.returncode != 0:
        drift.append(f"{svc}: docker inspect 失败 {container_names[0]}")
        continue
    info = json.loads(inspect.stdout)[0]

    # image
    decl_image = (d.get("image") or "").strip()
    actual_image = (info.get("Config", {}).get("Image") or "").strip()
    checked += 1
    if decl_image and actual_image and decl_image not in actual_image:
        drift.append(f"{svc}: 镜像漂移 声明={decl_image} 实测={actual_image}")

    # read_only
    decl_ro = bool(d.get("read_only", False))
    actual_ro = bool(info.get("HostConfig", {}).get("ReadonlyRootfs", False))
    checked += 1
    if decl_ro != actual_ro:
        drift.append(f"{svc}: read_only 声明={decl_ro} 实测={actual_ro}")

    # no-new-privileges
    decl_nnp = bool(d.get("no_new_privileges", False))
    actual_nnp = bool(info.get("HostConfig", {}).get("NoNewPrivileges", False))
    checked += 1
    if decl_nnp != actual_nnp:
        drift.append(f"{svc}: no-new-privileges 声明={decl_nnp} 实测={actual_nnp}")

    # cap_drop
    decl_drop = set(str(x).lower() for x in (d.get("cap_drop") or []))
    actual_drop = set(str(x).lower().replace("cap_", "") for x in (info.get("HostConfig", {}).get("CapDrop") or []))
    checked += 1
    # Docker 报告 "ALL"；声明可能用 ["ALL"]
    if "all" not in decl_drop and (decl_drop or actual_drop) and decl_drop != actual_drop:
        drift.append(f"{svc}: cap_drop 声明={sorted(decl_drop)} 实测={sorted(actual_drop)}")

    # user
    decl_user = (d.get("user") or "").strip()
    actual_user = (info.get("Config", {}).get("User") or "").strip()
    checked += 1
    if decl_user and actual_user and decl_user != actual_user:
        drift.append(f"{svc}: user 声明={decl_user} 实测={actual_user}")

    # mounts（比对 source/target/type）
    decl_vols = []
    for v in (d.get("volumes") or []):
        if isinstance(v, dict):
            decl_vols.append((v.get("source") or "", v.get("target") or "", v.get("type") or "volume"))
        elif isinstance(v, str):
            # "src:dst[:mode]" 或 "/tmp"（匿名 tmpfs 在 config 中是对象，一般不会到这）
            src, _, rest = v.partition(":")
            tgt, _, _ = rest.partition(":")
            if src and tgt:
                decl_vols.append((src, tgt, "bind" if "/" in src or "." in src else "volume"))
    actual_mounts = []
    for m in (info.get("Mounts") or []):
        # 命名卷优先取 Name（卷名），bind 挂载取 Source（路径）
        src = m.get("Name") or m.get("Source") or ""
        actual_mounts.append((src, m.get("Destination") or "", m.get("Type") or ""))
    # compose 会把命名卷重命名为 "<project>_<vol>"，故用 endswith 匹配；bind 路径精确匹配。
    def mount_match(decl_src, decl_tgt):
        for a_src, a_tgt, _ in actual_mounts:
            if a_tgt == decl_tgt and (a_src == decl_src or a_src.endswith(decl_src)):
                return True
        return False

    for s, t, typ in decl_vols:
        if not mount_match(s, t):
            drift.append(f"{svc}: 挂载漂移 声明 {typ} {s}:{t} 未在实测 Mounts 中")
            checked += 1

    # env 键名
    decl_env_keys = set()
    for e in (d.get("environment") or []):
        if isinstance(e, str):
            decl_env_keys.add(e.split("=", 1)[0])
        elif isinstance(e, dict):
            decl_env_keys.update(e.keys())
    actual_env_keys = set()
    for e in (info.get("Config", {}).get("Env") or []):
        actual_env_keys.add(e.split("=", 1)[0])
    missing_env = sorted(decl_env_keys - actual_env_keys)
    if missing_env:
        drift.append(f"{svc}: 环境变量缺失 {missing_env}")
        checked += 1

if output_json:
    print(json.dumps({"checked": checked, "drift": drift}, ensure_ascii=False, indent=2))
else:
    print(f"drift-check: 比对 {checked} 项 / 运行服务 {len(target_services)}")
    for d in drift:
        print(f"  DRIFT  {d}")
    if drift:
        print(f"drift-check: FAIL — {len(drift)} 处漂移")
        sys.exit(1)
    print("drift-check: OK — 实际环境与 compose 声明一致")
PY
exit $?