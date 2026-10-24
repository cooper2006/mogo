#!/usr/bin/env bash
#
# 部署安全基线扫描（024 T016 + T018）
#
# 四项扫描（FR-001/004/005/003）：
#   1. 非 root        — 镜像 Config.User 非 root/0
#   2. 只读文件系统   — compose read_only: true
#   3. 最小能力       — compose cap_drop: ["ALL"] + no-new-privileges: true
#   4. 体积基线       — 镜像分层数与总体积不超 deploy/config/image-baseline.yml
# 外加运行层清理检查（T018）：镜像内不得含 gcc/g++/pip 缓存/*.test.py
#
# 用法：
#   baseline-check.sh                # 人类可读输出
#   baseline-check.sh --json         # JSON 输出（items[].status = pass/fail）
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

JSON_OUTPUT=false
for argument in "$@"; do
  case "${argument}" in
    --json) JSON_OUTPUT=true ;;
  esac
done

# 业务服务清单（与 docker-compose.yml 对齐）。
# 镜像级检查的去重清单：document-api/document-worker 共用 document-parser 镜像。
IMAGE_SERVICES=(chat-api admin-api document-parser gateway admin-web user-web dsh-runtime-host)
# compose 级检查清单（含 document-api/document-worker，因为它们有自己的容器配置）。
COMPOSE_SERVICES=(chat-api admin-api document-api document-worker user-web admin-web gateway)

BASELINE_FILE="${ROOT_DIR}/deploy/config/image-baseline.yml"

# --- 收集结果 ---
declare -a ITEMS=()
PASS_COUNT=0
FAIL_COUNT=0

add_item() {
  # add_item <service> <check> <status> <detail>
  local service="$1" check="$2" status="$3" detail="$4"
  ITEMS+=("$(printf '%s\t%s\t%s\t%s' "${service}" "${check}" "${status}" "${detail}")")
  if [[ "${status}" == "pass" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

# --- 镜像级检查（非 root + 体积基线 + 运行层清理）---
# 用单个 python3 调用完成全部镜像检查，避免多次 docker inspect。
check_images() {
  python3 - "${ROOT_DIR}" "${BASELINE_FILE}" "${IMAGE_SERVICES[@]}" <<'PYEOF'
import json, os, subprocess, sys

root = sys.argv[1]
baseline_file = sys.argv[2]
services = sys.argv[3:]

try:
    import yaml
except ImportError:
    print("FAIL\t__all__\tPyYAML not available")
    sys.exit(0)

# 读取基线
with open(baseline_file) as f:
    baseline = yaml.safe_load(f)
baselines = baseline.get("images", {})

# 从 compose config 解析服务 → 镜像名
compose_json = subprocess.run(
    ["docker", "compose", "-f", os.path.join(root, "docker-compose.yml"), "config", "--format", "json"],
    capture_output=True, text=True
).stdout
try:
    dc = json.loads(compose_json)
except Exception:
    dc = {}

for name in services:
    svc = dc.get("services", {}).get(name, {})
    image = svc.get("image", "")

    # 若 compose 给的镜像名在本地不存在，尝试本地已有 tag
    if not image or not subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0:
        imgs = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True, text=True
        ).stdout.splitlines()
        local = [i for i in imgs if i.startswith(name + ":")]
        if local:
            image = local[0]

    if not image:
        print(f"fail\t{name}\timage-present\tno local image")
        continue

    # docker inspect
    inspect = subprocess.run(
        ["docker", "image", "inspect", image, "--format",
         "{{.Config.User}}\t{{len .RootFS.Layers}}\t{{.Size}}"],
        capture_output=True, text=True
    )
    if inspect.returncode != 0:
        print(f"fail\t{name}\timage-present\tcannot inspect {image}")
        continue

    parts = inspect.stdout.strip().split("\t")
    image_user = parts[0] if len(parts) > 0 else ""
    layers = int(parts[1]) if len(parts) > 1 else 0
    size_bytes = int(parts[2]) if len(parts) > 2 else 0
    size_mb = size_bytes // 1048576

    # image-present
    print(f"pass\t{name}\timage-present\t{image}")

    # non-root
    if not image_user or image_user in ("0", "root"):
        print(f"fail\t{name}\tnon-root\tConfig.User='{image_user}'")
    else:
        print(f"pass\t{name}\tnon-root\tConfig.User={image_user}")

    # volume-baseline
    spec = baselines.get(name, {})
    max_layers = spec.get("max_layers")
    max_size_mb = spec.get("max_size_mb")
    problems = []
    if max_layers is not None and layers > max_layers:
        problems.append(f"layers {layers} > {max_layers}")
    if max_size_mb is not None and size_mb > max_size_mb:
        problems.append(f"size {size_mb}MB > {max_size_mb}MB")
    if problems:
        print(f"fail\t{name}\tvolume-baseline\t{'; '.join(problems)}")
    else:
        print(f"pass\t{name}\tvolume-baseline\tlayers={layers} size={size_mb}MB")

    # runtime-layer（T018）
    rt = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", image, "-c",
         "command -v gcc >/dev/null 2>&1 || command -v g++ >/dev/null 2>&1 && echo FOUND:compiler; "
         "[ -d /root/.cache/pip ] && echo FOUND:pip-cache; "
         "find / -name '*.test.py' 2>/dev/null | head -1 | grep -q . && echo FOUND:test-files; "
         "echo DONE"],
        capture_output=True, text=True, timeout=120
    )
    out = rt.stdout
    if "FOUND:" in out:
        kind = [l.split(":", 1)[1] for l in out.splitlines() if l.startswith("FOUND:")]
        print(f"fail\t{name}\truntime-layer\t{'/'.join(kind)}")
    elif "DONE" in out:
        print(f"pass\t{name}\truntime-layer\tno build tools / pip cache / *.test.py")
    else:
        print(f"skip\t{name}\truntime-layer\tno sh or docker run failed")

PYEOF
}

# --- compose 级检查（read_only + cap_drop + no-new-privileges + user）---
check_compose() {
  python3 - "${ROOT_DIR}/docker-compose.yml" "${COMPOSE_SERVICES[@]}" <<'PYEOF'
import sys, yaml

path = sys.argv[1]
services = sys.argv[2:]
with open(path) as f:
    dc = yaml.safe_load(f)

for name in services:
    svc = dc.get("services", {}).get(name)
    if svc is None:
        print(f"fail\t{name}\tcompose-present\tnot found in compose")
        continue
    print(f"pass\t{name}\tcompose-present\t")

    ro = svc.get("read_only")
    cap = svc.get("cap_drop") or []
    nnp = any(str(x).startswith("no-new-privileges:true") for x in (svc.get("security_opt") or []))
    user = svc.get("user")

    if ro is not True:
        print(f"fail\t{name}\tread-only\tread_only is not true")
    else:
        print(f"pass\t{name}\tread-only\t")

    if "ALL" not in cap:
        print(f"fail\t{name}\tcapability\tcap_drop does not drop ALL")
    else:
        print(f"pass\t{name}\tcapability\tcap_drop=ALL")

    if not nnp:
        print(f"fail\t{name}\tcapability\tno-new-privileges not enabled")
    else:
        print(f"pass\t{name}\tcapability\tno-new-privileges=true")

    if not user or user in ("0", "0:0", "root"):
        print(f"fail\t{name}\tcompose-user\tuser='{user}'")
    else:
        print(f"pass\t{name}\tcompose-user\tuser={user}")

PYEOF
}

# --- 主流程 ---
while IFS=$'\t' read -r status service check detail; do
  add_item "${service}" "${check}" "${status}" "${detail}"
done < <(check_images)

while IFS=$'\t' read -r status service check detail; do
  add_item "${service}" "${check}" "${status}" "${detail}"
done < <(check_compose)

# --- 输出 ---
if [[ "${JSON_OUTPUT}" == "true" ]]; then
  python3 - "${PASS_COUNT}" "${FAIL_COUNT}" "${ITEMS[@]}" <<'PYEOF'
import json, sys
pass_count = int(sys.argv[1])
fail_count = int(sys.argv[2])
items = []
for entry in sys.argv[3:]:
    service, check, status, detail = entry.split("\t", 3)
    items.append({"service": service, "check": check, "status": status, "detail": detail})
print(json.dumps({"items": items, "pass": pass_count, "fail": fail_count}, indent=2))
PYEOF
else
  for entry in "${ITEMS[@]}"; do
    IFS=$'\t' read -r service check status detail <<<"${entry}"
    if [[ "${status}" == "pass" ]]; then
      printf 'PASS  %-16s %-18s %s\n' "${service}" "${check}" "${detail}"
    elif [[ "${status}" == "skip" ]]; then
      printf 'SKIP  %-16s %-18s %s\n' "${service}" "${check}" "${detail}"
    else
      printf 'FAIL  %-16s %-18s %s\n' "${service}" "${check}" "${detail}"
    fi
  done
  printf '\n%d pass, %d fail\n' "${PASS_COUNT}" "${FAIL_COUNT}"
fi

[[ "${FAIL_COUNT}" -gt 0 ]] && exit 1
exit 0
