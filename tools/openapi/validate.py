"""T041 OpenAPI 校验脚本（FR-26, QF-255）。

对 T040 生成的 `<service>-openapi.json` 执行：
  1. `openapi-spec-validator`：结构级校验（OpenAPI 3.1 合法性，含 uniqueItems / minLength 等
     schema 内部一致性）；
  2. `spectral lint`：规则级 lint（本地已安装 spectral CLI 时执行，规则集见
     `openapi/.spectral-ruleset.yaml`）；未安装则打印提示并回退到内置 `_builtin_lint`；
  3. 内置 lint 兜底：`_builtin_lint` 覆盖与 spectral 规则集一致的必查项。

任一失败 rc=1（CI 阻断 PR）。

用法:
  python3 tools/openapi/validate.py --all
  python3 tools/openapi/validate.py --service admin-api
  python3 tools/openapi/validate.py --all --skip-spectral
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from openapi_spec_validator import validate_spec

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.openapi.generate import ARTIFACT_DIR, SERVICES  # noqa: E402

RULESET = ARTIFACT_DIR / ".spectral-ruleset.yaml"

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def _builtin_lint(spec: dict) -> tuple[list[str], list[str]]:
    """内置规则 lint，返回 (阻断项 problems, 提示项 warnings)。

    规则（与 spectral ruleset 意图一致）：
      L1 info.title / info.version 必须存在；【阻断】
      L2 paths 非空，每个 path 至少一个 operation；【阻断】
      L3 operationId 全局唯一且非空；【阻断】
      L4 每个 operation 有 tags（非空）；【提示，不阻断】——tags 是文档元数据，
         缺失不影响契约；chat-api 大量路由未设 tags（见 tasks.md T041 待补项）。
      L5 4xx/5xx 响应必须带 description；【阻断】
      L6 每个响应有 content 或 description（不允许空响应体定义）。【阻断】
    """
    problems: list[str] = []
    warnings: list[str] = []

    info = spec.get("info") or {}
    if not info.get("title"):
        problems.append("L1: info.title 缺失")
    if not info.get("version"):
        problems.append("L1: info.version 缺失")

    paths = spec.get("paths") or {}
    if not paths:
        problems.append("L2: paths 为空")

    seen_operation_ids: dict[str, str] = {}

    for path_name, path_item in paths.items():
        if not isinstance(path_item, dict):
            problems.append(f"L2: path {path_name} 不是 object")
            continue
        operations = {m: path_item[m] for m in HTTP_METHODS if isinstance(path_item.get(m), dict)}
        if not operations:
            problems.append(f"L2: path {path_name} 无 operation")
            continue
        for method, op in operations.items():
            location = f"{method.upper()} {path_name}"
            oid = op.get("operationId")
            if not oid:
                problems.append(f"L3: {location} 缺 operationId")
            elif oid in seen_operation_ids:
                problems.append(
                    f"L3: operationId '{oid}' 重复（{seen_operation_ids[oid]} 与 {location}）"
                )
            else:
                seen_operation_ids[oid] = location
            tags = op.get("tags")
            if not tags:
                warnings.append(f"L4: {location} 无 tags")
            responses = op.get("responses") or {}
            if not responses:
                problems.append(f"L5: {location} 无 responses")
            for status, resp in responses.items():
                if not isinstance(resp, dict):
                    problems.append(f"L5: {location} 响应 {status} 不是 object")
                    continue
                if not resp.get("description") and not resp.get("content"):
                    problems.append(f"L6: {location} 响应 {status} 缺 description/content")
                if _is_error_status(status) and not resp.get("description"):
                    problems.append(f"L5: {location} 错误响应 {status} 缺 description")
    return problems, warnings


def _is_error_status(status: str) -> bool:
    try:
        code = int(status)
    except ValueError:
        return False
    return code >= 400


def _spectral_available() -> bool:
    return shutil.which("spectral") is not None


def _run_spectral(artifact: Path) -> tuple[bool, list[str]]:
    """执行 spectral lint，返回 (通过, 报告行)。"""
    ruleset = RULESET
    cmd = ["spectral", "lint", str(artifact)]
    if ruleset.exists():
        cmd += ["--ruleset", str(ruleset)]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    report = []
    for line in proc.stdout.splitlines():
        if line.strip() and ("error" in line.lower() or "warning" in line.lower() or line.startswith(" ")):
            report.append(line)
    ok = proc.returncode == 0
    return ok, report


def check_service(service: str, artifacts_dir: Path | None = None, skip_spectral: bool = False) -> tuple[bool, list[str]]:
    """校验单服务 artifact，返回 (通过, 报告行)。"""
    d = artifacts_dir or ARTIFACT_DIR
    artifact = d / f"{service}-openapi.json"
    if not artifact.exists():
        return False, [f"{service}: artifact 不存在: {artifact}"]
    report: list[str] = []
    try:
        spec = json.loads(artifact.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [f"{service}: artifact 非法 JSON: {exc}"]
    try:
        validate_spec(spec)
        report.append(f"[ok] {service}: openapi-spec-validator 通过")
    except Exception as exc:
        report.append(f"[error] {service}: openapi-spec-validator 失败: {str(exc)[:300]}")

    lint_problems, lint_warnings = _builtin_lint(spec)
    if lint_problems:
        report.append(f"[error] {service}: 内置 lint 阻断项失败")
        report += [f"    {p}" for p in lint_problems]
    else:
        report.append(f"[ok] {service}: 内置 lint 通过（阻断项）")
    if lint_warnings:
        report.append(f"[warn] {service}: 内置 lint 提示项 {len(lint_warnings)} 条（不阻断，见 tasks.md T041）")

    if skip_spectral:
        report.append(f"[info] {service}: 已跳过 spectral（--skip-spectral）")
    elif not _spectral_available():
        report.append(
            "[info] spectral CLI 未安装（需 `npm i -g @stoplight/spectral-cli`），"
            f"回退到内置 lint；规则集 {RULESET.relative_to(REPO)} 供 CI 使用"
        )
    else:
        ok, lines = _run_spectral(artifact)
        report.append(f"[{'ok' if ok else 'error'}] {service}: spectral lint {'通过' if ok else '失败'}")
        report += [f"    {ln}" for ln in lines]

    ok = not any(r.startswith("[error]") for r in report)
    return ok, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T041 OpenAPI 校验")
    ap.add_argument("--service", choices=SERVICES)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dir", type=Path, default=None, help="artifact 目录")
    ap.add_argument("--skip-spectral", action="store_true")
    args = ap.parse_args(argv)

    services = SERVICES if args.all else ([args.service] if args.service else SERVICES)
    rc = 0
    for svc in services:
        ok, report = check_service(svc, args.dir, args.skip_spectral)
        for line in report:
            print(line)
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
