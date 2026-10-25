#!/usr/bin/env python3
"""024 T032 (FR-018)：把容器晋级动作写入发布记录，供审计回溯。

每次 promote（候选 tag → 版本/latest tag）都会追加一条记录到
`deploy/releases/promotions.jsonl`，并更新 `deploy/releases/latest.json` 的
`last_promotion` 段。记录字段：action / source_sha / source_tag / suffixes /
target_tag / actor / occurred_at / github_run_id。

用法：
  python scripts/release/record_promotion.py --action promote \
      --source-sha <sha> --source-tag candidate-<sha> --suffixes a,b \
      --target-tag v1.4.0 --actor <actor>

环境变量（可选）：GITHUB_RUN_ID。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMOTIONS = REPO_ROOT / "deploy" / "releases" / "promotions.jsonl"
DEFAULT_LATEST = REPO_ROOT / "deploy" / "releases" / "latest.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_promotions(record: dict, promotions_file: Path) -> None:
    promotions_file.parent.mkdir(parents=True, exist_ok=True)
    with promotions_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_latest(record: dict, latest_file: Path) -> None:
    if latest_file.exists():
        with latest_file.open(encoding="utf-8") as fh:
            latest = json.load(fh)
    else:
        latest = {"git_sha": "", "built_at": "", "images": {}, "last_promotion": {}}
    latest.setdefault("last_promotion", {})
    latest["last_promotion"] = {
        "action": record["action"],
        "actor": record["actor"],
        "occurred_at": record["occurred_at"],
        "source_sha": record["source_sha"],
        "source_tag": record["source_tag"],
        "target_tag": record["target_tag"],
        "suffixes": record["suffixes"],
        "github_run_id": record["github_run_id"],
    }
    latest_file.parent.mkdir(parents=True, exist_ok=True)
    with latest_file.open("w", encoding="utf-8") as fh:
        json.dump(latest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="记录容器晋级动作到发布记录")
    parser.add_argument("--action", default="promote")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--suffixes", required=True)
    parser.add_argument("--target-tag", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--promotions", default=str(DEFAULT_PROMOTIONS))
    parser.add_argument("--latest", default=str(DEFAULT_LATEST))
    args = parser.parse_args()

    if not args.source_sha.isalnum() or len(args.source_sha) < 7:
        raise SystemExit(f"record_promotion: 非法 source_sha: {args.source_sha}")

    record = {
        "action": args.action,
        "source_sha": args.source_sha,
        "source_tag": args.source_tag,
        "suffixes": [s.strip() for s in args.suffixes.split(",") if s.strip()],
        "target_tag": args.target_tag,
        "actor": args.actor,
        "occurred_at": _now(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }
    write_promotions(record, Path(args.promotions))
    update_latest(record, Path(args.latest))
    print(f"record_promotion: 已记录 {args.action} {args.source_tag} -> "
          f"{args.target_tag}（actor={args.actor}, suffixes={len(record['suffixes'])} 个）")


if __name__ == "__main__":
    main()