#!/usr/bin/env python3
"""阶段 2：把 MongoDB 中的 ObjectId / 24-hex 主键与引用统一为 32-hex 字符串。

设计要点（见 docs/id-unification-hex32-runbook.md）：

* **停机执行**：脚本要求显式 ``--confirm-stopped``，否则拒绝写库。写路径必须
  先停服，否则服务会继续用旧代码写入 ObjectId 主键。
* **事件流截断**：``kernel_event_inbox`` / ``kernel_event_projections`` 不迁移，
  原集合 ``rename`` 成库内备份（可回滚），再建空集合并恢复索引。
* **其余集合**：整集合 ``rename`` 成库内备份 → 以转换后的文档重建同名集合 →
  恢复索引。库内备份全程保留，``rollback`` 可一键回退。
* **磁盘备份**：每个集合另存一份 BSON 快照 + 索引定义 + ID 映射表，独立于
  库内备份，防止误删库内备份后无法回滚。
* **时间有序 32-hex**：新 ID = 12 位 hex 毫秒时间戳 + 20 位 hex 随机数，字典序
  即时间序，保留 ``_id`` 作为高水位游标 / 分页游标的既有语义。存量 ObjectId
  用其 ``generation_time`` 作为时间戳前缀，顺序不倒退。

用法::

    python3 scripts/migrate_ids_to_hex32.py --db mogo_dev plan
    python3 scripts/migrate_ids_to_hex32.py --db mogo_dev --confirm-stopped apply
    python3 scripts/migrate_ids_to_hex32.py --db mogo_dev verify
    python3 scripts/migrate_ids_to_hex32.py --db mogo_dev rollback

    所有子命令共用同一个 ``--out`` 目录（默认 backups/id-hex32-<时间戳>）；
    apply / verify / rollback 需显式复用 plan 生成的目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bson
from bson import ObjectId
from pymongo import MongoClient

EVENT_COLLECTIONS = frozenset({"kernel_event_inbox", "kernel_event_projections"})

#: 使用「业务自然键」的集合：_id 不是 ObjectId 派生，不强制 32-hex。
#: 例如组织编码 "13000"、项目键 "web-project-..."、状态单例 _id 等。
#: 这些集合内部若出现 24-hex 子串仍会被替换（复合键前缀），但整体形态保留。
NATURAL_KEY_COLLECTIONS = frozenset({
    "business_entity_index",
    "bw_probe2",
    "bw_probe3",
    "bw_probe_dbg",
    "bw_probe_dbg2",
    "employees",
    "knowledge_document_chunks",
    "mesc_ontology_perm_audit",
    "org_units",
    "position_roles",
    "projects",
    "skill_quality_collector_state",
    "sys_config",
    "system_bootstrap",
    "trust_rating_scan_state",
    "skill_quality_metrics",
})

# 匹配文档文本内嵌的 24-hex ObjectId 子串。
# lookbehind 必须排除「前缀 + hex」的业务自然键（如 tenant_id 的
# `org-<hex>` / `bonc-<hex>` 这类「前缀-dash-hex」复合键）：其 hex 段
# 左侧是字母或 `-`（如 `org-` 结尾是 g，dash 紧贴 hex），不能当作
# ObjectId 替换，否则会把多租户逻辑隔离键改坏。
# 排除左侧为 hex / 字母 / `-` 的情形，只保留「裸 24-hex」(左侧是串首、
# 空白、引号、逗号、冒号等分隔符) 的匹配；lookahead 同理排除右侧 hex。
_HEX24_IN_TEXT = re.compile(r"(?<![0-9a-zA-Z-])([0-9a-fA-F]{24})(?![0-9a-fA-F])")
_HEX24_FULL = re.compile(r"^[0-9a-fA-F]{24}$")
_HEX32_FULL = re.compile(r"^[0-9a-fA-F]{32}$")


# ── 32-hex 生成 ────────────────────────────────────────────────────────────
def _seed_ms_from_hex24(text: str) -> int:
    """ObjectId 前 8 位 hex 即 Unix 秒；用它保留时间序。"""
    try:
        return int(text[:8], 16) * 1000
    except ValueError:
        return int(time.time() * 1000)


def _seed_ms_from_oid(oid: ObjectId) -> int:
    try:
        return int(oid.generation_time.timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def _new_hex32(seed_ms: int) -> str:
    """12-hex 毫秒时间戳 + 20-hex 随机数 = 32-hex，字典序≈时间序。"""
    ms = max(0, min(int(seed_ms), (1 << 48) - 1))
    return f"{ms:012x}{secrets.token_hex(10)}"


def _fallback_hex32(text: str) -> str:
    """映射表缺项时的确定性兜底（不引入随机、可重复执行）。"""
    ms = _seed_ms_from_hex24(text)
    digest = hashlib.sha256(text.encode("ascii")).hexdigest()[:20]
    return f"{ms:012x}{digest}"


# ── 备份 ───────────────────────────────────────────────────────────────────
def _manifest_path(out: Path) -> Path:
    return out / "manifest.json"


def _map_path(out: Path) -> Path:
    return out / "id_map.json"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup(db: Any, out: Path, suffix: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    names = sorted(db.list_collection_names())
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "backup_suffix": suffix,
        "event_collections": sorted(EVENT_COLLECTIONS),
        "natural_key_collections": sorted(NATURAL_KEY_COLLECTIONS),
        "collections": {},
    }
    for name in names:
        coll = db[name]
        indexes = coll.index_information()
        count = 0
        with (out / f"{name}.bson").open("wb") as fh:
            for doc in coll.find({}, no_cursor_timeout=True).batch_size(2000):
                fh.write(bson.encode(doc))
                count += 1
        manifest["collections"][name] = {
            "count": count,
            "indexes": indexes,
            "is_event": name in EVENT_COLLECTIONS,
        }
        print(f"  backup {name:45s} {count:7d} docs, {len(indexes)} indexes", flush=True)
    _manifest_path(out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return manifest


def _load_manifest(out: Path) -> dict[str, Any]:
    path = _manifest_path(out)
    if not path.exists():
        sys.exit(f"缺少 {path}：请先执行 plan（apply / verify / rollback 复用同一 --out 目录）")
    return json.loads(path.read_text(encoding="utf-8"))


# ── 映射表 ─────────────────────────────────────────────────────────────────
def _collect_hex24_values(value: Any, found: set[str]) -> None:
    if isinstance(value, ObjectId):
        found.add(str(value))
    elif isinstance(value, str):
        if _HEX32_FULL.match(value):
            return
        found.update(m.group(1) for m in _HEX24_IN_TEXT.finditer(value))
    elif isinstance(value, dict):
        for item in value.values():
            _collect_hex24_values(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_hex24_values(item, found)


def _build_map(db: Any, manifest: dict[str, Any], out: Path) -> dict[str, str]:
    path = _map_path(out)
    if path.exists():
        print(f"  复用已有映射表 {path}", flush=True)
        return json.loads(path.read_text(encoding="utf-8"))

    found: set[str] = set()
    oid_seeds: dict[str, int] = {}
    for name, meta in manifest["collections"].items():
        if meta["is_event"]:
            continue  # 事件流被截断，不参与映射
        for doc in db[name].find({}, no_cursor_timeout=True).batch_size(2000):
            oid = doc.get("_id")
            if isinstance(oid, ObjectId):
                oid_seeds[str(oid)] = _seed_ms_from_oid(oid)
            _collect_hex24_values(doc, found)

    mapping: dict[str, str] = {}
    for old in sorted(found):
        mapping[old] = _new_hex32(oid_seeds.get(old, _seed_ms_from_hex24(old)))
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  映射表 {len(mapping)} 条（ObjectId 主键 {len(oid_seeds)} 条）→ {path}", flush=True)
    return mapping


# ── 文档转换 ───────────────────────────────────────────────────────────────
class Converter:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.refs = 0
        self.misses: set[str] = set()

    def _lookup(self, old: str) -> str:
        new = self.mapping.get(old)
        if new is None:
            new = _fallback_hex32(old)
            self.mapping[old] = new
            self.misses.add(old)
        return new

    def value(self, value: Any) -> Any:
        if isinstance(value, ObjectId):
            self.refs += 1
            return self._lookup(str(value))
        if isinstance(value, str):
            if _HEX32_FULL.match(value):
                return value
            if _HEX24_IN_TEXT.search(value):
                def sub(match: re.Match[str]) -> str:
                    self.refs += 1
                    return self._lookup(match.group(1))
                return _HEX24_IN_TEXT.sub(sub, value)
            return value
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        return value

    def doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        converted = {key: self.value(item) for key, item in doc.items() if key != "_id"}
        oid = doc.get("_id")
        if isinstance(oid, ObjectId):
            converted["_id"] = self._lookup(str(oid))
        elif isinstance(oid, str):
            converted["_id"] = self.value(oid)
        else:
            converted["_id"] = oid
        return converted


# ── 索引 ───────────────────────────────────────────────────────────────────
def _restore_indexes(coll: Any, indexes: dict[str, Any], conv: Converter) -> None:
    for name, spec in indexes.items():
        if name == "_id_":
            continue
        keys = [(field, direction) for field, direction in spec["key"]]
        kwargs: dict[str, Any] = {
            key: conv.value(val) if isinstance(val, (str, dict, list)) else val
            for key, val in spec.items()
            if key not in {"key", "v", "ns", "name"}
        }
        kwargs["name"] = name
        try:
            coll.create_index(keys, **kwargs)
        except Exception as exc:  # 索引定义异常不应静默吞掉，但不能中断整库
            print(f"  !! 索引 {coll.name}.{name} 重建失败: {exc}", file=sys.stderr, flush=True)
            raise


# ── 子命令 ─────────────────────────────────────────────────────────────────
def cmd_plan(db: Any, out: Path) -> None:
    suffix = f"__hex32_bak_{_ts()}"
    print(f"[plan] 备份目录 {out}，库内备份后缀 {suffix}")
    manifest = _backup(db, out, suffix)
    mapping = _build_map(db, manifest, out)
    conv = Converter(dict(mapping))
    report: dict[str, Any] = {"collections": {}, "event_truncated": []}
    for name, meta in manifest["collections"].items():
        if meta["is_event"]:
            report["event_truncated"].append({"name": name, "docs": meta["count"]})
            print(f"  TRUNCATE {name:40s} {meta['count']:7d} docs → 0", flush=True)
            continue
        before = conv.refs
        ids_changed = 0
        for doc in db[name].find({}, {"_id": 1}, no_cursor_timeout=True).batch_size(2000):
            oid = doc.get("_id")
            if isinstance(oid, ObjectId) or (isinstance(oid, str) and _HEX24_IN_TEXT.search(oid) and not _HEX32_FULL.match(oid)):
                ids_changed += 1
        # 统计整份文档的引用替换数（含 _id）
        refs = 0
        for doc in db[name].find({}, no_cursor_timeout=True).batch_size(2000):
            n = conv.refs
            conv.doc(doc)
            refs += conv.refs - n
        report["collections"][name] = {
            "docs": meta["count"],
            "ids_rewritten": ids_changed,
            "refs_rewritten": refs,
            "natural_key": name in NATURAL_KEY_COLLECTIONS,
        }
        print(f"  CONVERT  {name:40s} {meta['count']:7d} docs, _id={ids_changed:6d}, refs={refs:6d}", flush=True)
    total_ids = sum(v["ids_rewritten"] for v in report["collections"].values())
    total_refs = sum(v["refs_rewritten"] for v in report["collections"].values())
    report["summary"] = {
        "collections": len(manifest["collections"]),
        "event_docs_dropped": sum(v["docs"] for v in report["event_truncated"]),
        "ids_rewritten": total_ids,
        "refs_rewritten": total_refs,
        "mapping_entries": len(conv.mapping),
        "fallback_entries": len(conv.misses),
    }
    (out / "plan.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[plan] 汇总 " + json.dumps(report["summary"], ensure_ascii=False))
    if conv.misses:
        _map_path(out).write_text(json.dumps(conv.mapping, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print("[plan] 只读完成，未改动数据库。确认无误后执行 apply --confirm-stopped。")


def cmd_apply(db: Any, out: Path, confirm_stopped: bool) -> None:
    if not confirm_stopped:
        sys.exit("拒绝执行：阶段 2 必须在停机窗口内运行，请显式传入 --confirm-stopped")
    manifest = _load_manifest(out)
    suffix = manifest["backup_suffix"]
    existing = [n for n in db.list_collection_names() if n.endswith(suffix)]
    if existing:
        sys.exit(f"拒绝执行：库内已存在备份集合（{existing[:3]}），说明 apply 已跑过；请先 rollback 或换 --out")
    mapping = _build_map(db, manifest, out)
    conv = Converter(dict(mapping))
    started = time.time()
    applied: list[dict[str, Any]] = []
    try:
        for name, meta in manifest["collections"].items():
            bak = f"{name}{suffix}"
            db[name].rename(bak)
            # 显式重建同名集合：既覆盖事件流的「截断」，也保证 39 个空集合
            # 不会因为没有二级索引而在迁移后消失。
            db.create_collection(name)
            if meta["is_event"]:
                # 截断重建：只恢复索引，不写回任何文档
                _restore_indexes(db[name], meta["indexes"], conv)
                applied.append({"name": name, "mode": "truncate", "docs": 0})
                print(f"  [truncate] {name:40s} {meta['count']:7d} → 0", flush=True)
                continue
            docs = [conv.doc(doc) for doc in db[bak].find({}, no_cursor_timeout=True).batch_size(2000)]
            if docs:
                db[name].insert_many(docs, ordered=False, bypass_document_validation=True)
            _restore_indexes(db[name], meta["indexes"], conv)
            applied.append({"name": name, "mode": "convert", "docs": len(docs)})
            print(f"  [convert]  {name:40s} {len(docs):7d} docs", flush=True)
    except Exception as exc:
        print(f"\n!! apply 中断：{exc}\n已处理 {len(applied)} 个集合；库内备份 {suffix} 完整，请执行 rollback。", file=sys.stderr)
        raise

    _map_path(out).write_text(json.dumps(conv.mapping, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 2),
        "backup_suffix": suffix,
        "mapping_entries": len(conv.mapping),
        "fallback_entries": sorted(conv.misses),
        "collections": applied,
    }
    (out / "apply-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[apply] 完成，用时 {report['elapsed_seconds']}s；自动执行 verify…")
    cmd_verify(db, out)


def cmd_verify(db: Any, out: Path) -> None:
    manifest = _load_manifest(out)
    problems: list[str] = []
    stats: dict[str, Any] = {"collections": 0, "docs": 0, "objectid_ids": 0,
                             "hex24_ids": 0, "hex32_ids": 0, "natural_key_ids": 0,
                             "residual_hex24_values": 0, "event_docs": 0}
    details: dict[str, Any] = {}
    for name in sorted(db.list_collection_names()):
        if name.endswith(manifest["backup_suffix"]):
            continue  # 库内备份不参与终态校验
        coll = db[name]
        kinds = {"objectid": 0, "hex24": 0, "hex32": 0, "other": 0}
        residual = 0
        count = 0
        for doc in coll.find({}, no_cursor_timeout=True).batch_size(2000):
            count += 1
            oid = doc.get("_id")
            if isinstance(oid, ObjectId):
                kinds["objectid"] += 1
            elif isinstance(oid, str) and _HEX24_FULL.match(oid):
                kinds["hex24"] += 1
            elif isinstance(oid, str) and _HEX32_FULL.match(oid):
                kinds["hex32"] += 1
            else:
                kinds["other"] += 1
            found: set[str] = set()
            _collect_hex24_values(doc, found)
            residual += len(found)
        stats["collections"] += 1
        stats["docs"] += count
        stats["objectid_ids"] += kinds["objectid"]
        stats["hex24_ids"] += kinds["hex24"]
        stats["hex32_ids"] += kinds["hex32"]
        stats["natural_key_ids"] += kinds["other"]
        stats["residual_hex24_values"] += residual
        if name in EVENT_COLLECTIONS:
            stats["event_docs"] += count
            if count:
                problems.append(f"{name} 未截断（仍有 {count} 文档）")
        if kinds["objectid"] or kinds["hex24"]:
            problems.append(f"{name} 仍有旧格式 _id（ObjectId={kinds['objectid']}, 24-hex={kinds['hex24']}）")
        if kinds["other"] and name not in NATURAL_KEY_COLLECTIONS:
            problems.append(f"{name} 有 {kinds['other']} 个非 32-hex _id，且不在自然键白名单")
        if residual:
            problems.append(f"{name} 仍含 {residual} 个 24-hex 引用值")
        details[name] = {"docs": count, **kinds, "residual_hex24": residual}
    report = {"stats": stats, "problems": problems, "collections": details}
    (out / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[verify] " + json.dumps(stats, ensure_ascii=False))
    if problems:
        print("[verify] FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        sys.exit(1)
    print("[verify] PASS：无 ObjectId / 24-hex 主键，无 24-hex 引用残留，事件流为空。")


def cmd_rollback(db: Any, out: Path, confirm_stopped: bool) -> None:
    if not confirm_stopped:
        sys.exit("拒绝执行：rollback 同样需要停机，请显式传入 --confirm-stopped")
    manifest = _load_manifest(out)
    suffix = manifest["backup_suffix"]
    restored = 0
    for name in manifest["collections"]:
        bak = f"{name}{suffix}"
        if bak not in db.list_collection_names():
            print(f"  skip {name}（无库内备份）", flush=True)
            continue
        if name in db.list_collection_names():
            db.drop_collection(name)
        db[bak].rename(name)
        restored += 1
        print(f"  restored {name}", flush=True)
    print(f"[rollback] 已从 {suffix} 恢复 {restored} 个集合；索引随原集合一起恢复。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default="mongodb://127.0.0.1:27017", help="MongoDB URI（默认本机 ServeBay Mongo）")
    parser.add_argument("--db", default="mogo_dev", help="数据库名")
    parser.add_argument("--out", type=Path, default=None, help="备份/报告目录（apply/verify/rollback 复用 plan 的目录）")
    parser.add_argument("--confirm-stopped", action="store_true", help="确认所有业务服务已停止写入")
    parser.add_argument("command", choices=["plan", "apply", "verify", "rollback"])
    args = parser.parse_args()
    out = args.out or Path(f"backups/id-hex32-{_ts()}")
    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[args.db]
    print(f"[mongo] {args.uri} / {args.db}  command={args.command}  out={out}")
    if args.command == "plan":
        cmd_plan(db, out)
    elif args.command == "apply":
        cmd_apply(db, out, args.confirm_stopped)
    elif args.command == "verify":
        cmd_verify(db, out)
    else:
        cmd_rollback(db, out, args.confirm_stopped)
    client.close()


if __name__ == "__main__":
    main()
