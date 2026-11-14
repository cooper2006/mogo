#!/usr/bin/env python3
"""024 T071 (FR-037)：恢复后业务校验。

恢复演练（`./mogo restore --verify` 或 DR 流程）之后对关键业务能力做冒烟校验，
产出 PASS/FAIL 报告。校验维度：核心可读写、对话、文档、知识检索、网关可达。

用法：
  verify_restore_business.py --base-url http://localhost:8080 [--endpoints-file <yaml>] [--timeout 10] [--json]

默认端点（可用 --endpoints-file 覆盖，格式 YAML：列表 {name, method, path, expect_status, expect_substring}）：
  - GET  /health                      期待 200
  - GET  /api/health                  期待 200
  - POST /api/chat                    期待 200（可空 body，仅冒烟）
  - GET  /api/documents                期待 200
  - GET  /api/knowledge-base/search   期待 200
  - GET  /api/admin/system/status     期待 200

退出码：0 全部 PASS；1 存在 FAIL；2 参数/依赖错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINTS = [
    {"name": "gateway_health", "method": "GET", "path": "/health",
     "expect_status": 200, "expect_substring": ""},
    {"name": "api_health", "method": "GET", "path": "/api/health",
     "expect_status": 200, "expect_substring": ""},
    {"name": "chat_smoke", "method": "POST", "path": "/api/chat",
     "expect_status": 200, "expect_substring": ""},
    {"name": "documents_list", "method": "GET", "path": "/api/documents",
     "expect_status": 200, "expect_substring": ""},
    {"name": "knowledge_search", "method": "GET", "path": "/api/knowledge-base/search",
     "expect_status": 200, "expect_substring": ""},
    {"name": "admin_status", "method": "GET", "path": "/api/admin/system/status",
     "expect_status": 200, "expect_substring": ""},
]


def _call(base: str, method: str, path: str, timeout: float):
    url = base.rstrip("/") + (path if path.startswith("/") else "/" + path)
    body = b"{}" if method == "POST" else None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        headers["Content-Length"] = str(len(body))
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # network / DNS / refused
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description="024 T071 恢复后业务校验（FR-037）")
    ap.add_argument("--base-url", required=True, help="网关/服务基础 URL")
    ap.add_argument("--endpoints-file", help="端点清单 YAML（可选）")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = ap.parse_args()

    endpoints = list(DEFAULT_ENDPOINTS)
    if args.endpoints_file:
        try:
            import yaml
            with open(args.endpoints_file, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if data.get("endpoints"):
                endpoints = data["endpoints"]
        except Exception as exc:
            print(f"FAIL: 无法读取 --endpoints-file: {exc}", file=sys.stderr)
            return 2

    results = []
    for ep in endpoints:
        status, text = _call(args.base_url, ep.get("method", "GET"),
                             ep.get("path", "/"), args.timeout)
        checks = {"status": status == ep.get("expect_status", 200)}
        if ep.get("expect_substring"):
            checks["substring"] = ep["expect_substring"] in text
        ok = all(checks.values())
        results.append({
            "name": ep.get("name", ep.get("path")),
            "path": ep.get("path"),
            "method": ep.get("method", "GET"),
            "status": status,
            "expect_status": ep.get("expect_status", 200),
            "checks": checks,
            "ok": ok,
        })

    ok_count = sum(1 for r in results if r["ok"])
    passed = ok_count == len(results)
    report = {
        "base_url": args.base_url,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(results),
        "passed": ok_count,
        "failed": len(results) - ok_count,
        "verdict": "PASS 恢复后业务校验全部通过（FR-037）" if passed else
                   "FAIL 存在未通过的业务校验（FR-037）",
        "results": results,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"恢复后业务校验：{ok_count}/{len(results)} 通过")
        for r in results:
            mark = "OK  " if r["ok"] else "FAIL"
            print(f"  {mark} {r['name']:24s} {r['method']:4s} {r['path']:30s} "
                  f"status={r['status']}/{r['expect_status']}")
        print("结论: " + report["verdict"])

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())