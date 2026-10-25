"""T040 OpenAPI 自动生成（FR-25, QF-253）。

三个服务（admin-api / chat-api / document-parser）的 OpenAPI 3.1 由 FastAPI 自动生成，
输出 `<service>-openapi.json` 到指定目录（默认 `specs/025-api-contract-hardening/openapi/`），
供 CI 作为 artifact 保存并 diff（`--check`）。

三个服务都使用顶层包名 `app`，**必须各自在独立子进程内 import**（否则模块互相污染），
因此 `--all` 通过 subprocess 逐个调用自身。

依赖隔离：document-parser 依赖 celery（仅 worker 启动时使用），OpenAPI 生成不启动
worker，因此注入轻量 celery stub（`Celery`/`Task`/`shared_task`），使 schema 生成不依赖
真实 broker / worker。

用法:
  python3 tools/openapi/generate.py --all
  python3 tools/openapi/generate.py --service admin-api --out /tmp/oapi
  python3 tools/openapi/generate.py --all --check   # 与已提交 artifact 比对，变化则 rc=1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "specs" / "025-api-contract-hardening" / "openapi"
ARTIFACT_DIR = DEFAULT_OUT

SERVICES = ["admin-api", "chat-api", "document-parser"]

# 需要 celery stub 的服务（worker-only 依赖，OpenAPI 生成不启动 worker）
CELERY_STUB_SERVICES = {"document-parser"}


def _install_celery_stub() -> None:
    """注入 celery 模块 stub，使 OpenAPI 生成不依赖真实 broker/worker。"""
    celery = types.ModuleType("celery")

    class _Conf:
        def update(self, **kw):
            return None

    class _Insp:
        def ping(self):
            return []

    class _Ctrl:
        def inspect(self, timeout=0):
            return _Insp()

    def _decorate(f):
        f.celery_stub = True
        return f

    class FakeCeleryApp:
        def __init__(self, *a, **kw):
            self.conf = _Conf()
            self.control = _Ctrl()

        def task(self, *a, **kw):
            return _decorate

        def send_task(self, *a, **kw):
            return None

    class Task:
        pass

    celery.Celery = FakeCeleryApp
    celery.Task = Task
    celery.shared_task = _decorate
    celery.task = _decorate
    sys.modules["celery"] = celery


def _build_openapi(service: str) -> dict:
    """在当前进程内生成某服务的 OpenAPI schema（须在独立子进程调用）。"""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "services" / service))
    if service in CELERY_STUB_SERVICES:
        _install_celery_stub()
    try:
        # 工厂模式（admin-api / document-parser）
        from app.main import create_app  # type: ignore[import-not-found]

        spec = create_app().openapi()
    except ImportError:
        # 模块级 app（chat-api）
        from app.main import app  # type: ignore[import-not-found]

        spec = app.openapi()
    if not isinstance(spec, dict) or not spec.get("openapi"):
        raise RuntimeError(f"{service}: openapi 生成失败")
    return spec


def _run_service(service: str, out_dir: Path, check: bool) -> int:
    """在子进程内生成单服务 OpenAPI 并写出 artifact。"""
    out = out_dir / f"{service}-openapi.json"
    code = (
        "import json, sys, pathlib\n"
        f"sys.argv = ['generate.py', '--service', {service!r}]\n"
        "sys.path.insert(0, 'tools')\n"
        "from tools.openapi.generate import _build_openapi\n"
        f"spec = _build_openapi({service!r})\n"
        f"pathlib.Path({str(out)!r}).write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\\n', encoding='utf-8')\n"
        "print('generated', len(spec.get('paths', {})))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        print(f"{service}: 生成失败\n{proc.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"{service}: {proc.stdout.strip()} -> {_rel(out)}")
    if not out.exists():
        print(f"{service}: 未生成 artifact: {out}", file=sys.stderr)
        return 1
    if check:
        return _diff_check(service, out)
    return 0


def _rel(path: Path) -> Path:
    """把路径显示为相对 REPO（临时目录下不强制 relative）。"""
    try:
        return path.relative_to(REPO)
    except ValueError:
        return path


def _diff_check(service: str, out: Path) -> int:
    """比对生成结果与已提交的 artifact（FR-25 CI diff）。"""
    # 重新生成到临时文件再比对，避免把本地改动当作 artifact
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fresh = tmp / f"{service}-openapi.json"
        code = (
            "import json, sys, pathlib\n"
            f"sys.argv = ['generate.py', '--service', {service!r}]\n"
            "sys.path.insert(0, 'tools')\n"
            "from tools.openapi.generate import _build_openapi\n"
            f"spec = _build_openapi({service!r})\n"
            f"pathlib.Path({str(fresh)!r}).write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\\n', encoding='utf-8')\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            print(f"{service}: 重新生成失败\n{proc.stderr.strip()}", file=sys.stderr)
            return 1
        committed = out.read_text(encoding="utf-8")
        current = fresh.read_text(encoding="utf-8")
        if committed == current:
            print(f"{service}: artifact 与当前实现一致")
            return 0
        print(f"{service}: artifact 与当前实现不一致（需提交新的 openapi.json）", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T040 OpenAPI 自动生成")
    ap.add_argument("--service", choices=SERVICES)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="生成后与已提交 artifact 比对")
    args = ap.parse_args(argv)

    out_dir = args.out or DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    services = SERVICES if args.all else ([args.service] if args.service else SERVICES)

    rc = 0
    for svc in services:
        rc = max(rc, _run_service(svc, out_dir, args.check))
    return rc


if __name__ == "__main__":
    sys.exit(main())
