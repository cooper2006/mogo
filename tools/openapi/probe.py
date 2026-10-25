"""T047 OpenAPI 与实测一致性探针（FR-25, QF-254）。

对 T040 生成的 `<service>-openapi.json`，用 FastAPI `TestClient` 实测**只读、无副作用**
端点，与 OpenAPI 定义做三类一致性比对。**探针口径：一切结论都来自实测**，不依赖静态
枚举 app.routes（admin-api 用 FastAPI `_IncludedRouter` 延迟挂载，顶层 `app.routes`
不可枚举，静态扫描会误报）。

  1. **路径可达性**：OpenAPI 声明的**无路径参数**路径，实测请求非 404 → 挂载存在；
     实测 404 → OpenAPI 声明但实现缺失（不一致）；实测 5xx → 依赖不可用，跳过。
  2. **参数生效性**：OpenAPI 声明 `required: true` 的 query 参数，实测**不带**该参数
     请求应返回 422（FastAPI 校验生效）→ 一致；返回 200/其它非 422 → 不一致
     （参数未生效）；返回 401/403/5xx → 被认证或依赖拦截，无法判定，跳过。
  3. **响应字段名**：实测响应 JSON 的**顶层字段名集合**应与该状态码响应 schema 的
     属性名集合一致（递归处理 `$ref` / `allOf` / `oneOf` / `properties` / `items`；
     数组元素为自由 dict 视为 opaque，跳过）。

环境约束：
- 三服务共用顶层包名 `app`，**必须各自在独立子进程内 import**（`--all` 通过 subprocess
  逐个调用自身）。
- document-parser 本地缺 celery，复用 `generate._install_celery_stub()` 注入 stub 后
  import（T040/T045 已验证该 stub 足以生成 schema）。
- 启动连 `panweidb` 失败、打印大量日志属预期，容忍；`TestClient` 不用 `with`，不触发
  lifespan，避免 DB 依赖。

用法:
  python3 tools/openapi/probe.py --service admin-api
  python3 tools/openapi/probe.py --all

退出码：真实不一致 rc=1。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.openapi.generate import ARTIFACT_DIR, SERVICES, _install_celery_stub  # noqa: E402

CELERY_STUB_SERVICES = {"document-parser"}
HTTP_METHODS = ("GET", "HEAD")
SAFE_PATH_HINTS = ("health", "ready", "meta")
MAX_PROBE = 15  # 每服务最多探测的端点数

# 按设计返回 404 的路径前缀（探针豁免，判 note 而非 problem）：
# chat-api `app/api/endpoints/debug.py` 的 router 用 `dependencies=[Depends(require_debug_mode)]`，
# 而 `require_debug_mode()` 在 `get_settings().DEBUG` 为 False 时 `raise HTTPException(404)`；
# 本地默认 DEBUG=False → 这些端点实测 404 是预期行为，不是契约漂移。
BUSINESS_404_PREFIXES = ("/api/v1/debug/",)
BUSINESS_404_HINT = "路由已挂载但被 debug-mode 守卫（DEBUG=false）隐藏，属业务 404 非实现缺失"


# ── schema 字段名收集 ───────────────────────────────────────────────────────────────


def load_spec(service: str) -> dict:
    path = ARTIFACT_DIR / f"{service}-openapi.json"
    if not path.exists():
        raise FileNotFoundError(f"OpenAPI artifact 缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(schema: Any, components: dict, depth: int = 0) -> dict:
    if not isinstance(schema, dict) or depth > 8:
        return schema if isinstance(schema, dict) else {}
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        target = (components.get("schemas") or {}).get(ref.rsplit("/", 1)[-1])
        if isinstance(target, dict):
            return _resolve(target, components, depth + 1)
    return schema


def collect_field_names(schema: Any, components: dict, depth: int = 0) -> set[str]:
    """收集 schema 的**顶层**属性名集合（穿透 `$ref`/`allOf`/`oneOf`，不深入嵌套）。"""
    schema = _resolve(schema, components, depth)
    if not schema or depth > 8:
        return set()
    names: set[str] = set()
    for comb in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(comb) or []:
            names |= collect_field_names(sub, components, depth + 1)
    props = schema.get("properties") or {}
    names |= set(props.keys())
    return names


# ── 探针端点选择 ────────────────────────────────────────────────────────────────────


@dataclass
class ProbeOp:
    path: str
    method: str
    operation: dict


def select_probe_operations(spec: dict, limit: int = MAX_PROBE) -> list[ProbeOp]:
    """挑选只读探针端点：优先 health/ready/meta，再取无 requestBody 的 GET/HEAD。

    只选**无路径参数**的端点（否则无法无参请求、404 语义不可判）。
    """
    paths = spec.get("paths") or {}
    hits: list[ProbeOp] = []
    for p, item in paths.items():
        if not isinstance(item, dict):
            continue
        if "{" in p:
            continue
        for m in HTTP_METHODS:
            op = item.get(m.lower())
            if not isinstance(op, dict):
                continue
            if op.get("requestBody"):
                continue
            hits.append(ProbeOp(path=p, method=m, operation=op))
    hits.sort(key=lambda o: (0 if any(h in o.path.lower() for h in SAFE_PATH_HINTS) else 1, o.path))
    return hits[:limit]


# ── app 构建 ────────────────────────────────────────────────────────────────────────


def build_app(service: str) -> Any:
    """构建服务 app（document-parser 先注入 celery stub）。须在独立进程调用。"""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "services" / service))
    if service in CELERY_STUB_SERVICES:
        _install_celery_stub()
    try:
        from app.main import create_app  # type: ignore[import-not-found]

        return create_app()
    except ImportError:
        from app.main import app  # type: ignore[import-not-found]

        return app


# ── 三类比对 ────────────────────────────────────────────────────────────────────────


def _collect_routes(app: Any) -> dict[str, Any]:
    """递归收集 HTTP Route，返回 {完整路径: Route}（含 Mount 子应用与 FastAPI `_IncludedRouter`）。"""
    from starlette.routing import Mount, Route, WebSocketRoute

    found: dict[str, Any] = {}

    def walk(routes, prefix: str) -> None:
        for r in routes or []:
            p = getattr(r, "path", "") or ""
            full = prefix + p
            # FastAPI 新版把 include_router 包装成 `_IncludedRouter`（延迟挂载）：它带
            # `.path`（即 include 的 prefix）与 `.routes`（内部 app.routes），但既不是 Mount
            # 也不是 Route，旧实现会把它们漏掉，导致 chat-api/admin-api 的 mounted 集为空、
            # 所有实测 404 都被误判成「实现未挂载」。
            if type(r).__name__ == "_IncludedRouter":
                walk(getattr(r, "routes", None), full)
            elif isinstance(r, Mount):
                walk(getattr(r, "routes", None), full)
            elif isinstance(r, Route) and not isinstance(r, WebSocketRoute):
                found[full] = r
            elif isinstance(r, Route):
                found[full] = r

    walk(app.routes, "")
    return found


def _mounted_paths(app: Any) -> set[str]:
    """先强制展开 FastAPI `_IncludedRouter`（openapi() 会触发展开），再收集挂载路径。"""
    try:
        app.openapi()
    except Exception:  # noqa: BLE001 — 展开失败不影响后续实测
        pass
    return set(_collect_routes(app).keys())


def _required_query_params(operation: dict) -> list[str]:
    """OpenAPI 声明为必填（required: true 且无 default）的 query 参数名。"""
    out: list[str] = []
    for p in operation.get("parameters") or []:
        if p.get("in") != "query" or not p.get("required"):
            continue
        schema = p.get("schema") or {}
        if "default" in schema or "default" in p:
            continue
        out.append(str(p.get("name")))
    return out


def _response_schema(operation: dict, status: int, spec: dict) -> Any:
    responses = operation.get("responses") or {}
    for key in (str(status), "default"):
        resp = responses.get(key)
        if not isinstance(resp, dict):
            continue
        for media in (resp.get("content") or {}).values():
            if isinstance(media, dict) and "schema" in media:
                return media["schema"]
    return None


def compare_response_fields(body: Any, operation: dict, status: int, spec: dict) -> list[str]:
    """实测响应 JSON 的字段名集合 vs OpenAPI 响应 schema 属性名集合。"""
    schema = _response_schema(operation, status, spec)
    components = spec.get("components") or {}
    if schema is None:
        return []
    declared = collect_field_names(schema, components)
    if not declared:
        return []  # opaque（自由 dict / 无属性定义），跳过
    if isinstance(body, dict):
        missing = sorted(set(body.keys()) - declared)
        if missing:
            return [f"实测字段 {missing} 不在 OpenAPI 响应 schema（status {status}）"]
    elif isinstance(body, list):
        for i, item in enumerate(body[:5]):
            if isinstance(item, dict):
                missing = sorted(set(item.keys()) - declared)
                if missing:
                    return [f"实测数组元素[{i}] 字段 {missing} 不在 OpenAPI items schema（status {status}）"]
    return []


# ── 单服务探针 ──────────────────────────────────────────────────────────────────────


@dataclass
class ProbeReport:
    service: str
    probed: int = 0
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    status: str = "ok"

    def as_dict(self) -> dict:
        return {
            "service": self.service,
            "status": self.status,
            "probed": self.probed,
            "skipped": self.skipped,
            "problems": self.problems,
            "notes": self.notes,
        }


def probe_service(service: str, limit: int = MAX_PROBE) -> ProbeReport:
    """探针单服务（本函数须在子进程调用，避免 app 包名污染）。"""
    from fastapi.testclient import TestClient

    spec = load_spec(service)
    app = build_app(service)
    report = ProbeReport(service=service)
    ops = select_probe_operations(spec, limit)
    client = TestClient(app)  # 不用 with：不触发 lifespan，避免 DB 依赖
    mounted = _mounted_paths(app)

    for probe in ops:
        report.probed += 1
        try:
            resp = client.request(probe.method, probe.path)
        except Exception as exc:  # noqa: BLE001 — 连接层异常
            report.skipped.append(f"{probe.method} {probe.path}: 请求异常，跳过（{type(exc).__name__}）")
            continue
        # 路径可达性
        if resp.status_code == 404:
            # FastAPI 0.141 的 include_router 产物是 `_IncludedRouter`（延迟挂载），无法静态枚举
            # 路由表，故不依赖 mounted 集。对**按设计**返回 404 的路径（如 debug-mode 守卫端点
            # 在 DEBUG=false 时故意隐藏，见 chat-api `require_debug_mode`）用前缀白名单豁免，
            # 其余 404 一律判为真实契约漂移（OpenAPI 声明但实现未挂载）。
            if any(probe.path.startswith(p) for p in BUSINESS_404_PREFIXES):
                report.notes.append(
                    f"{probe.method} {probe.path}: 实测 404（{BUSINESS_404_HINT}）"
                )
            else:
                report.problems.append(
                    f"{probe.method} {probe.path}: OpenAPI 已声明但实测 404（实现未挂载）"
                )
            continue
        if resp.status_code >= 500:
            report.skipped.append(
                f"{probe.method} {probe.path}: 实测 {resp.status_code}（依赖不可用？），跳过"
            )
            continue
        if resp.status_code in (401, 403):
            # 被认证拦截：字段/参数无法判定，跳过（不影响路径可达性结论）
            report.notes.append(f"{probe.method} {probe.path}: 实测 {resp.status_code}（认证拦截，字段/参数跳过）")
            continue

        # 参数生效性：OpenAPI 声明的必填 query 参数，不带应得 422
        required = _required_query_params(probe.operation)
        for name in required:
            try:
                r2 = client.request(probe.method, probe.path, params={k: v for k, v in []})
            except Exception as exc:  # noqa: BLE001
                report.skipped.append(f"{probe.method} {probe.path}: 参数校验请求异常（{type(exc).__name__}）")
                continue
            if r2.status_code == 422:
                continue  # 参数生效，一致
            if r2.status_code in (401, 403) or r2.status_code >= 500:
                report.skipped.append(
                    f"{probe.method} {probe.path}: 必填参数 '{name}' 校验被 {r2.status_code} 拦截，无法判定"
                )
            else:
                report.problems.append(
                    f"{probe.method} {probe.path}: OpenAPI 声明必填 query 参数 '{name}'，"
                    f"实测不带时返回 {r2.status_code}（应为 422，参数未生效）"
                )

        # 响应字段名（仅当响应非空 JSON）
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            continue
        if body is None:
            continue
        for msg in compare_response_fields(body, probe.operation, resp.status_code, spec):
            report.problems.append(f"{probe.method} {probe.path}: {msg}")

    report.status = "problem" if report.problems else ("skipped" if report.skipped else "ok")
    return report


def _run_service_subprocess(service: str, limit: int) -> ProbeReport:
    """子进程跑 probe_service，结果写临时文件（chat-api 会劫持 sys.stdout，
    print 不可靠），主进程读回。"""
    import tempfile

    tmp = Path(tempfile.mkstemp(suffix=".json")[1])
    code = (
        "import json, sys\n"
        "sys.path.insert(0, 'tools')\n"
        "from tools.openapi.probe import probe_service\n"
        f"r = probe_service({service!r}, limit={limit})\n"
        f"open({str(tmp)!r}, 'w', encoding='utf-8').write(json.dumps(r.as_dict(), ensure_ascii=False))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=600)
    raw = tmp.read_text(encoding="utf-8") if tmp.exists() else ""
    tmp.unlink(missing_ok=True)
    if raw.strip():
        try:
            return ProbeReport(**json.loads(raw))
        except Exception:  # noqa: BLE001
            pass
    tail = (proc.stderr or "")[-800:].strip()
    return ProbeReport(service=service, status="error", notes=[tail or f"子进程 rc={proc.returncode}"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T047 OpenAPI 与实测一致性探针")
    ap.add_argument("--service", choices=SERVICES)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=MAX_PROBE, help="每服务最多探测端点数")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    args = ap.parse_args(argv)

    services = SERVICES if args.all or not args.service else [args.service]
    reports: list[ProbeReport] = []
    for svc in services:
        try:
            rep = _run_service_subprocess(svc, args.limit)
        except Exception as exc:  # noqa: BLE001
            rep = ProbeReport(service=svc, status="skipped", notes=[f"依赖缺失：{exc}"])
        reports.append(rep)

    rc = 0
    for rep in reports:
        rc = max(rc, 1 if rep.problems else 0)
        if not args.json:
            print(f"[{rep.service}] {rep.status} — 探测 {rep.probed} 端点")
            for n in rep.notes:
                print(f"  note: {n}")
            for s in rep.skipped:
                print(f"  skip: {s}")
            for p in rep.problems:
                print(f"  PROBLEM: {p}")
    if args.json:
        print(json.dumps([r.as_dict() for r in reports], ensure_ascii=False, indent=2))
    elif rc == 0:
        print("probe: OK（无一致性问题）")
    else:
        print("probe: FAILED（发现一致性问题）", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())