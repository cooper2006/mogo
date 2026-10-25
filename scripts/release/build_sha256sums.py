#!/usr/bin/env python3
"""024 T030 (FR-019)：汇总发布镜像 digest，产出可签名校验的 SHA256SUMS。

每次 push tag 触发的 container-release.yml 在 promote 之后调用本脚本：
  1. build 模式：对 ALL_IMAGES_JSON 里每个 suffix 用 `docker buildx imagetools
     inspect` 取 manifest digest，写成 SHA256SUMS（`<hex>  <image_ref>`，
     GNU sha256sum 兼容格式），供发布附件下载校验。
  2. verify 模式：读已发布的 SHA256SUMS，对每行重查 registry digest，
     不一致即退出码 1（线上 digest 与发布记录不符 = 完整性校验失败）。

环境变量：
  ALL_IMAGES_JSON    release plan 的 images 段（JSON，每项含 suffix）
  GITHUB_REF_NAME    发布 tag（如 v1.4.0）
  GITHUB_REPOSITORY_OWNER   GitHub owner（决定 ghcr.io/<owner> 前缀）
用法：
  python scripts/release/build_sha256sums.py [build|verify] [--file PATH] [--json]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REQUIRED_ENV = ("ALL_IMAGES_JSON", "GITHUB_REF_NAME", "GITHUB_REPOSITORY_OWNER")


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"build_sha256sums: 缺少环境变量 {name}（要求: {', '.join(REQUIRED_ENV)}）")
    return value


def _hex(digest: str) -> str:
    """从 sha256:<hex>（或已含 @ 的引用）中取出纯 hex。"""
    return digest.split("@")[-1].removeprefix("sha256:")


def image_ref(suffix: str, owner: str, tag: str) -> str:
    return f"ghcr.io/{owner.lower()}/{suffix}:{tag}"


def resolve_digest(ref: str) -> str:
    """用 buildx 查 manifest digest，返回 sha256:<hex>。"""
    proc = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest.Digest}}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        sys.exit(f"build_sha256sums: 无法解析 {ref} 的 digest: {proc.stderr.strip()}")
    digest = json.loads(proc.stdout)
    if not digest or "@" not in digest:
        sys.exit(f"build_sha256sums: {ref} 未返回合法 digest: {proc.stdout.strip()}")
    return digest


def build(sha_file: str, images: list[dict]) -> list[dict]:
    owner = _env("GITHUB_REPOSITORY_OWNER")
    tag = _env("GITHUB_REF_NAME")
    entries = []
    for image in images:
        suffix = image["suffix"]
        ref = image_ref(suffix, owner, tag)
        digest = resolve_digest(ref)
        entries.append({"suffix": suffix, "ref": ref, "digest": digest})
    lines = [f"{_hex(e['digest'])}  {e['ref']}" for e in entries]
    with open(sha_file, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return entries


def verify(sha_file: str) -> tuple[list[str], list[str]]:
    """校验 SHA256SUMS 与实际 registry digest 一致。返回 (ok, problems)。"""
    problems, ok = [], []
    if not os.path.exists(sha_file):
        sys.exit(f"build_sha256sums: 找不到 {sha_file}")
    with open(sha_file, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            hex_digest, _, ref = raw.partition("  ")
            try:
                actual = resolve_digest(ref)
            except SystemExit:
                problems.append(f"{ref}: registry 无法解析 digest")
                continue
            actual = _hex(actual)
            if actual == hex_digest:
                ok.append(ref)
            else:
                problems.append(f"{ref}: SHA256SUMS={hex_digest} 线上={actual}")
    return ok, problems


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode not in ("build", "verify"):
        sys.exit("用法: build_sha256sums.py [build|verify] [--file PATH]")
    sha_file = "SHA256SUMS"
    if "--file" in sys.argv:
        idx = sys.argv.index("--file")
        sha_file = sys.argv[idx + 1]
    try:
        images = json.loads(_env("ALL_IMAGES_JSON"))
    except json.JSONDecodeError as exc:
        sys.exit(f"build_sha256sums: ALL_IMAGES_JSON 非法 JSON: {exc}")

    if mode == "build":
        entries = build(sha_file, images)
        print(f"build_sha256sums: 已生成 {sha_file}，共 {len(entries)} 个镜像 digest")
        for e in entries:
            print(f"  {e['digest']}  {e['ref']}")
    else:
        ok, problems = verify(sha_file)
        print(f"build_sha256sums: 校验 {len(ok) + len(problems)} 项，一致 {len(ok)} 项")
        for problem in problems:
            print(f"  FAIL  {problem}")
        if problems:
            sys.exit(1)
        print("build_sha256sums: OK — 线上 digest 与 SHA256SUMS 一致")


if __name__ == "__main__":
    main()