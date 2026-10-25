#!/usr/bin/env bash
# 024 T033 (FR-016)：部署计划 diff 预审。
#
# 比较两个 git ref 的 docker-compose.yml 声明，产出"新增/删除/变更"的服务、
# 镜像 digest、环境变量、挂载与端口，供预审。默认比较 HEAD 与 HEAD^。
# 实际执行与计划不一致时可配合 drift-check.sh 告警（见 README 说明）。
#
# 用法：
#   deploy/cli/deploy-dry-run.sh [--from <ref>] [--to <ref>] [--json]
#   ref 缺省：from=HEAD^（或 HEAD，若 HEAD 无父提交），to=HEAD。
# 退出码：0 = 正常输出；1 = 检测到破坏性变更（删除服务/降级镜像）——仍输出 diff，
#          由调用方决定是否阻断；2 = 用法/解析错误。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"

FROM_REF=""
TO_REF="HEAD"
OUTPUT_JSON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM_REF="$2"; shift 2 ;;
    --to) TO_REF="$2"; shift 2 ;;
    --json) OUTPUT_JSON=true; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if ! git -C "${ROOT_DIR}" rev-parse --verify --quiet "${TO_REF}^{commit}" >/dev/null 2>&1; then
  echo "deploy-dry-run: 目标 ref 不存在: ${TO_REF}" >&2
  exit 2
fi

if [[ -z "${FROM_REF}" ]]; then
  # 默认取 HEAD 的父提交
  if git -C "${ROOT_DIR}" rev-parse --verify --quiet "${TO_REF}^" >/dev/null 2>&1; then
    FROM_REF="${TO_REF}^"
  else
    FROM_REF="${TO_REF}"
  fi
fi

if ! git -C "${ROOT_DIR}" rev-parse --verify --quiet "${FROM_REF}^{commit}" >/dev/null 2>&1; then
  echo "deploy-dry-run: 基线 ref 不存在: ${FROM_REF}" >&2
  exit 2
fi

export ROOT_DIR COMPOSE_FILE FROM_REF TO_REF OUTPUT_JSON
python3 - <<'PY'
import json, os, subprocess, sys, tempfile
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
from_ref, to_ref = os.environ["FROM_REF"], os.environ["TO_REF"]
output_json = os.environ["OUTPUT_JSON"] == "true"
compose_rel = Path("docker-compose.yml")

def load(ref):
    """取指定 ref 的 docker-compose.yml 并解析为 services 声明。"""
    if ref == "WORKTREE":
        raw = Path(root / compose_rel).read_text(encoding="utf-8", errors="replace")
        tag = "worktree"
    else:
        raw = subprocess.run(
            ["git", "-C", str(root), "show", f"{ref}:{compose_rel}"],
            capture_output=True, text=True)
        if raw.returncode != 0:
            print(f"deploy-dry-run: 无法读取 {ref}:{compose_rel}: {raw.stderr.strip()}", file=sys.stderr)
            sys.exit(2)
        raw = raw.stdout
        tag = ref
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as fh:
        fh.write(raw)
        tmp = fh.name
    cfg = subprocess.run(["docker", "compose", "-f", tmp, "config", "--format", "json"],
                         capture_output=True, text=True)
    Path(tmp).unlink(missing_ok=True)
    if cfg.returncode != 0:
        print(f"deploy-dry-run: {tag} compose 解析失败: {cfg.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return json.loads(cfg.stdout).get("services", {})

def svc_summary(name, svc):
    env = {}
    for e in (svc.get("environment") or []):
        if isinstance(e, str):
            k, _, v = e.partition("=")
            env[k] = v
        elif isinstance(e, dict):
            env.update(e)
    vols = []
    for v in (svc.get("volumes") or []):
        if isinstance(v, dict):
            vols.append(f"{v.get('type','?')}:{v.get('source','?')}:{v.get('target','?')}")
        else:
            vols.append(str(v))
    ports = [f"{p}" for p in (svc.get("ports") or [])]
    return {
        "image": svc.get("image") or "",
        "env": env,
        "volumes": vols,
        "ports": ports,
        "depends_on": svc.get("depends_on") or [],
        "read_only": bool(svc.get("read_only")),
        "tmpfs": sorted(str(t) for t in (svc.get("tmpfs") or [])),
        "cap_drop": sorted(str(c) for c in (svc.get("cap_drop") or [])),
        "no_new_privileges": bool(svc.get("no_new_privileges")),
        "user": svc.get("user") or "",
    }

before = load(from_ref)
after = load(to_ref)

added = sorted(set(after) - set(before))
removed = sorted(set(before) - set(after))
common = sorted(set(before) & set(after))

changed, breaking = [], []
for name in common:
    b, a = svc_summary(name, before[name]), svc_summary(name, after[name])
    diffs = []
    if b["image"] != a["image"]:
        diffs.append(f"image: {b['image'] or '(未指定)'} -> {a['image'] or '(未指定)'}")
        # 镜像变更可能降级，标为 breaking（供预审把关）
        breaking.append(f"{name}: 镜像变更 {b['image']} -> {a['image']}")
    env_changed = {k: (b["env"].get(k), a["env"].get(k)) for k in set(b["env"]) | set(a["env"])
                   if b["env"].get(k) != a["env"].get(k)}
    for k, (ov, nv) in sorted(env_changed.items()):
        diffs.append(f"env.{k}: {ov!r} -> {nv!r}")
    if b["volumes"] != a["volumes"]:
        diffs.append(f"volumes: {b['volumes']} -> {a['volumes']}")
    if b["ports"] != a["ports"]:
        diffs.append(f"ports: {b['ports']} -> {a['ports']}")
    if b["depends_on"] != a["depends_on"]:
        diffs.append(f"depends_on: {b['depends_on']} -> {a['depends_on']}")
    for field in ("read_only", "tmpfs", "cap_drop", "no_new_privileges", "user"):
        if b[field] != a[field]:
            diffs.append(f"{field}: {b[field]!r} -> {a[field]!r}")
    if diffs:
        changed.append({"service": name, "diffs": diffs})

# 删除服务视为破坏性变更
for name in removed:
    breaking.append(f"{name}: 服务被删除")

report = {
    "from": from_ref,
    "to": to_ref,
    "summary": {
        "added": added,
        "removed": removed,
        "changed": [c["service"] for c in changed],
        "unchanged": [n for n in common if n not in {c["service"] for c in changed}],
    },
    "added_services": added,
    "removed_services": removed,
    "changed_services": changed,
    "breaking": breaking,
}

if output_json:
    print(json.dumps(report, ensure_ascii=False, indent=2))
else:
    print(f"deploy-dry-run: {from_ref} -> {to_ref}")
    print(f"  新增 {len(added)} 服务: {added or '无'}")
    print(f"  删除 {len(removed)} 服务: {removed or '无'}")
    print(f"  变更 {len(changed)} 服务:")
    for c in changed:
        print(f"    - {c['service']}")
        for d in c["diffs"]:
            print(f"        {d}")
    if breaking:
        print("  需预审（破坏性/降级风险）:")
        for b in breaking:
            print(f"    ! {b}")
    else:
        print("  无破坏性变更。")

sys.exit(1 if breaking else 0)
PY
exit $?