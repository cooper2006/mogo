#!/usr/bin/env python3
"""023 — vendored 共享模块字节一致性校验（CI 门禁，纯 stdlib）。

权威源 `services/common/{observability_base,dependency_guard,slo}.py` 必须与三服务
副本 `services/<svc>/app/common/<name>.py` 逐字节一致。漂移即失败——防止"只改副本"
或"只改权威源忘了同步"（镜像按服务目录构建，运行时用的是副本）。

退出码：0 一致；1 漂移（列明细）。
用法：python3 scripts/check_common_sync.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMON = REPO / "services" / "common"
SERVICES = ("admin-api", "chat-api", "document-parser")
MODULES = ("observability_base.py", "dependency_guard.py", "slo.py")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> int:
    problems: list[str] = []
    for module in MODULES:
        source = COMMON / module
        if not source.exists():
            problems.append(f"[missing] 权威源缺失: services/common/{module}")
            continue
        src_hash = _sha(source)
        for svc in SERVICES:
            copy = REPO / "services" / svc / "app" / "common" / module
            if not copy.exists():
                problems.append(f"[missing] {svc} 副本缺失: app/common/{module}")
                continue
            if _sha(copy) != src_hash:
                problems.append(
                    f"[drift] {svc}/app/common/{module} 与权威源不一致 "
                    f"(copy={_sha(copy)} vs source={src_hash})"
                )
    if problems:
        print("common module sync check FAILED:")
        for p in problems:
            print("  " + p)
        print("修复：改 services/common/ 后 cp 到三个 services/<svc>/app/common/。")
        return 1
    print(f"common module sync check OK — {len(MODULES)} modules x {len(SERVICES)} services")
    return 0


if __name__ == "__main__":
    sys.exit(main())
