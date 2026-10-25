#!/usr/bin/env bash
# 024 T031 (FR-012)：部署前比对线上容器镜像 digest 与流水线发布记录。
#
# 数据源（按优先级）：
#   1) 流水线发布记录 `deploy/releases/latest.json`（T030 产出 SHA256SUMS/发布记录时写入）：
#        { "git_sha": "...", "built_at": "...", "images": { "<service>": "repo@sha256:..." } }
#   2) 无发布记录时回退到 compose 声明（docker compose config）作为"预期产物"，
#      比对运行容器实际镜像，保证至少声明与运行一致。
#
# 用法：
#   deploy/cli/verify-artifact.sh [--service NAME] [--json]
# 退出码：0 = 一致；1 = 不一致/记录缺失且无回退；2 = 用法错误。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
RELEASE_FILE="${ROOT_DIR}/deploy/releases/latest.json"

SERVICE_SELECT=""
OUTPUT_JSON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE_SELECT="$2"; shift 2 ;;
    --json) OUTPUT_JSON=true; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "verify-artifact: docker 不可用" >&2
  exit 2
fi

export ROOT_DIR COMPOSE_FILE RELEASE_FILE SERVICE_SELECT OUTPUT_JSON
python3 - <<'PY'
import json, os, subprocess, sys

root = os.environ["ROOT_DIR"]
compose_file = os.path.join(root, "docker-compose.yml")
release_file = os.environ["RELEASE_FILE"]
service_filter = [s for s in os.environ["SERVICE_SELECT"].split(",") if s]
output_json = os.environ["OUTPUT_JSON"] == "true"

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

# 1) 解析 compose 声明（预期产物）
cfg = run(["docker", "compose", "-f", compose_file, "config", "--format", "json"])
if cfg.returncode != 0:
    print("verify-artifact: compose config 失败: " + cfg.stderr.strip(), file=sys.stderr)
    sys.exit(2)
declared = json.loads(cfg.stdout).get("services", {})
target_services = service_filter or sorted(declared.keys())

# 2) 运行容器实际镜像
ps = run(["docker", "ps", "--format", "{{.Names}}\t{{.Label \"com.docker.compose.service\"}}"])
running = {}
for line in ps.stdout.splitlines():
    parts = line.split("\t")
    if len(parts) == 2:
        running.setdefault(parts[1], []).append(parts[0])

# 3) 尝试读发布记录
release = None
import os as _os
if _os.path.exists(release_file):
    try:
        with open(release_file, encoding="utf-8") as fh:
            release = json.load(fh)
    except Exception:
        release = None

problems, checked, notes = [], 0, []
source = "compose-declaration"
if release and isinstance(release.get("images"), dict):
    source = "release-record"

for svc in target_services:
    decl_img = (declared.get(svc) or {}).get("image") or ""
    names = running.get(svc, [])
    if not names:
        continue
    inspect = run(["docker", "inspect", names[0]])
    if inspect.returncode != 0:
        problems.append(f"{svc}: docker inspect 失败")
        continue
    actual_img = (json.loads(inspect.stdout)[0].get("Config", {}).get("Image") or "")
    expected = decl_img
    if source == "release-record" and svc in release["images"]:
        expected = release["images"][svc]
    checked += 1
    if not expected:
        notes.append(f"{svc}: 无声明镜像（可能是本地构建 image 未固定），跳过比对")
        continue
    # 镜像引用可能带 repo:tag@sha256 或 repo@sha256，取 digest 段比对
    def digest_of(ref):
        return ref.split("@")[1] if "@" in ref else ref
    if digest_of(expected) not in digest_of(actual_img) and expected.split("@")[0] not in actual_img:
        problems.append(f"{svc}: 镜像不一致 预期={expected} 实测={actual_img}")

if output_json:
    print(json.dumps({"source": source, "checked": checked,
                      "problems": problems, "notes": notes}, ensure_ascii=False, indent=2))
else:
    print(f"verify-artifact: 比对 {checked} 个服务（依据 {source}）")
    for n in notes:
        print(f"  NOTE  {n}")
    for p in problems:
        print(f"  FAIL  {p}")
    if problems:
        print(f"verify-artifact: FAIL — {len(problems)} 处不一致（建议 drift-check.sh 复核运行态漂移）")
        sys.exit(1)
    print("verify-artifact: OK — 运行镜像与预期产物一致")
PY
exit $?