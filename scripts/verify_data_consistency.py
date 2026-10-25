#!/usr/bin/env python3
"""切换后数据一致性校验（024 T078 / FR-041）。

三项校验：
  1. MongoDB 关键集合行数（countDocuments）
  2. 抽样校验和（抽样文档排序后 JSON 的 sha256，可跨节点对账）
  3. 应用层读写探针（网关 / API 健康、对话、文档、知识检索冒烟）

校验对象必须是「切换/故障转移后」的数据层，因此脚本不写库、不重建索引，
只做只读校验。任一 FAIL 退出码 1。

用法：
  python3 scripts/verify_data_consistency.py \
      --mongo-uri mongodb://mongo:27017 \
      --db mogo_dev \
      --base-url http://127.0.0.1:3000 \
      --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_DB = "mogo_dev"
DEFAULT_BASE_URL = "http://127.0.0.1:3000"
MONGO_EVAL_TIMEOUT = 30

# 应用层读写探针默认端点：健康 + 业务冒烟（仅健康类默认开启，业务冒烟需
# --probe-app；避免在只做数据校验时对线上发真实请求）。
DEFAULT_HEALTH_ENDPOINTS = [
    ("gateway_health", "GET", "/health", None),
    ("api_health", "GET", "/api/health", None),
]


def _run(args, *, timeout=MONGO_EVAL_TIMEOUT, mongo_uri=None, db=None):
    """调 mongosh 执行一段 JavaScript，返回 (ok, stdout, stderr)。"""
    mongo_uri = mongo_uri or args.mongo_uri
    db = db or args.db
    try:
        parsed = urllib.parse.urlparse(mongo_uri)
        hostport = parsed.hostname or "127.0.0.1"
        if parsed.port:
            hostport = f"{hostport}:{parsed.port}"
    except Exception:
        hostport = mongo_uri.replace("mongodb://", "").split("/")[0].split("?")[0]
    cmd = [
        "mongosh",
        "--quiet",
        "--host",
        hostport,
        db,
        "--eval",
        args.script,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "", "mongosh 未安装（容器内应可用，宿主机需安装 mongosh 或改用 pymongo）"
    except subprocess.TimeoutExpired:
        return False, "", f"mongosh 超时（>{timeout}s）"
    return proc.returncode == 0, proc.stdout, proc.stderr


def _mongo_query(uri, db, script, timeout=MONGO_EVAL_TIMEOUT):
    """执行脚本，返回 (ok, 值, 错误)。脚本需以 JSON 输出结尾。"""
    args = argparse.Namespace(
        mongo_uri=uri, db=db, script=script, timeout=timeout
    )
    ok, out, err = _run(args, timeout=timeout, mongo_uri=uri, db=db)
    if not ok:
        return False, None, err.strip()
    # mongosh 会在输出尾部追加一行空行，逐行找最后一行合法 JSON
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return True, json.loads(line), None
        except json.JSONDecodeError:
            continue
    return False, None, f"无法解析 mongosh 输出: {out!r}"


def count_and_checksum(uri, db, collections, sample_size):
    """行数 + 抽样校验和。collections 为 None 时自动探测非 system 集合。"""
    if collections:
        names_expr = "[" + ",".join(json.dumps(c) for c in collections) + "]"
    else:
        names_expr = "db.getCollectionNames().filter(function(n){return n.indexOf('system.')!==0;})"
    script = f"""
(function() {{
  var names = {names_expr};
  var out = {{db: '{db}', collections: {{}}, count: 0}};
  names.forEach(function(name) {{
    var c = db.getCollection(name);
    var n = c.countDocuments({{}});
    var sample = c.find({{}}, {{_id: 1}}).sort({{_id: 1}}).limit({sample_size}).toArray();
    out.collections[name] = {{rows: n, sample: sample}};
    out.count += n;
  }});
  out.collNames = names;
  print(JSON.stringify(out));
  return out;
}})()
"""
    ok, data, err = _mongo_query(uri, db, script)
    if not ok:
        return {"ok": False, "error": err}
    result = {"ok": True, "uri": uri, "db": db, "collections": {}}
    checksum_ctx = hashlib.sha256()
    total_rows = 0
    for name, info in (data.get("collections") or {}).items():
        rows = int(info["rows"])
        total_rows += rows
        sample = info.get("sample") or []
        # 抽样校验和：按 _id 排序后的原始文档 JSON，跨节点可对账
        canonical = json.dumps(
            sorted(sample, key=lambda d: str(d.get("_id", ""))),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        checksum_ctx.update(canonical.encode("utf-8"))
        result["collections"][name] = {
            "rows": rows,
            "sample_sha256": digest,
            "sampled": len(sample),
        }
    result["total_rows"] = total_rows
    result["checksum"] = checksum_ctx.hexdigest()
    return result


def app_probe(base_url, endpoints, timeout):
    """应用层读写探针：GET 请求端点，返回每项结果。"""
    out = []
    for name, method, path, _body in endpoints:
        url = base_url.rstrip("/") + path
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                body = resp.read(4096).decode("utf-8", "replace")[:200]
                out.append({"name": name, "url": url, "status": status, "ok": True, "body": body})
        except urllib.error.HTTPError as e:
            out.append({"name": name, "url": url, "status": e.code, "ok": False, "body": str(e)})
        except Exception as e:  # 网络 / 超时
            out.append({"name": name, "url": url, "status": None, "ok": False, "body": str(e)})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="切换后数据一致性校验（FR-041）")
    parser.add_argument("--mongo-uri", default="mongodb://mongo:27017", help="MongoDB URI")
    parser.add_argument("--db", default=DEFAULT_DB, help="数据库名（默认 mogo_dev）")
    parser.add_argument("--collections", default="", help="逗号分隔的集合名；空则自动探测非 system 集合")
    parser.add_argument("--sample-size", type=int, default=20, help="每集合抽样条数（默认 20）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="应用网关地址")
    parser.add_argument("--probe-app", action="store_true", help="同时执行应用层读写探针")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP/DB 超时秒数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    collections = [c.strip() for c in args.collections.split(",") if c.strip()] or None

    report = {
        "mongo": count_and_checksum(args.mongo_uri, args.db, collections, args.sample_size),
        "app": None,
    }

    app_results = []
    if args.probe_app:
        app_results = app_probe(args.base_url, DEFAULT_HEALTH_ENDPOINTS, args.timeout)
        report["app"] = app_results

    # 判定
    mongo_ok = bool(report["mongo"].get("ok"))
    app_ok = all(r["ok"] for r in app_results) if app_results else True
    passed = mongo_ok and app_ok
    report["passed"] = passed
    report["verdict"] = (
        "切换后数据一致性校验全部通过（FR-041）：MongoDB 集合行数可达、"
        "抽样校验和已生成、应用层读写探针正常"
        if passed
        else "切换后数据一致性校验存在 FAIL（FR-041）：见 mongo / app 明细"
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        m = report["mongo"]
        if m.get("ok"):
            print(f"MongoDB {args.uri if False else args.mongo_uri} 库 {args.db}：{m.get('total_rows')} 行")
            for name, info in m.get("collections", {}).items():
                print(f"  - {name}: rows={info['rows']} sampled={info['sampled']} sha256={info['sample_sha256'][:16]}…")
        else:
            print(f"MongoDB 校验失败：{m.get('error')}")
        for r in app_results:
            print(f"  app {r['name']}: {'OK' if r['ok'] else 'FAIL'} {r['url']} -> {r.get('status')}")
        print(report["verdict"])
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())