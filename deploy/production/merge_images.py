"""把多个镜像合并成一个 docker 归档 tar，并按映射改写 RepoTags。

用法：
    python3 merge_images.py <输出tar> <源镜像>@<目标标签> [<源镜像>@<目标标签> ...]

例：
    python3 merge_images.py 01-base.tar \
        staging/alpine_3.21:amd64@alpine:3.21 \
        staging/redis_7.4.2-alpine:amd64@redis:7.4.2-alpine

做法：
  1. docker save 一次性导出全部源镜像到一个临时 tar；
  2. 读临时 tar 里的 manifest.json，按条目现有的 RepoTags 反查目标标签并改写；
  3. 重新打包（layers / config 原样拷贝，不重新压缩）。

注意：源镜像若只有单平台，不要在 docker save 上加 --platform，否则会
"no suitable export target found"。多平台标签请先用 buildx 生成单平台 staging 标签。
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile


def parse_pairs(argv):
    """解析 <源镜像>@<目标标签> 参数。"""
    pairs = []
    for a in argv:
        if "@" not in a:
            raise SystemExit(f"参数需要 <源镜像>@<目标标签> 形式，收到 {a!r}")
        src, dst = a.rsplit("@", 1)
        pairs.append((src, dst))
    return pairs


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    dst_tar = sys.argv[1]
    pairs = parse_pairs(sys.argv[2:])
    mapping = dict(pairs)
    sources = [src for src, _ in pairs]

    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "raw.tar")
        print(f"  导出 {len(sources)} 个镜像 ...")
        subprocess.run(["docker", "save", "-o", raw, *sources], check=True)

        with tarfile.open(raw, "r") as tin:
            members = tin.getmembers()
            mm = next((m for m in members if m.name == "manifest.json"), None)
            if mm is None:
                raise SystemExit("临时 tar 里找不到 manifest.json")
            manifest = json.load(tin.extractfile(mm))

            for entry in manifest:
                tags = entry.get("RepoTags") or []
                if not tags:
                    raise SystemExit(f"有条目没有 RepoTags，无法定位：{entry.get('Config')}")
                src_tag = tags[0]
                if src_tag not in mapping:
                    raise SystemExit(f"manifest 里的标签 {src_tag!r} 不在映射表里")
                entry["RepoTags"] = [mapping[src_tag]]
                print(f"    {src_tag} -> {mapping[src_tag]}")

            payload = json.dumps(manifest).encode("utf-8")
            with tarfile.open(dst_tar, "w") as tout:
                for m in members:
                    if m.name == "manifest.json":
                        m.size = len(payload)
                        tout.addfile(m, io.BytesIO(payload))
                    else:
                        f = tin.extractfile(m)
                        if f is None:
                            tout.addfile(m)
                        else:
                            tout.addfile(m, f)

    size = os.path.getsize(dst_tar)
    print(f"  ✅ {dst_tar}  {size / 1024 / 1024:.0f}MB")


if __name__ == "__main__":
    main()
