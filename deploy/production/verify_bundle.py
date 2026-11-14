#!/usr/bin/env python3
"""校验离线镜像包，并把结果写回 bundle.json。

用法：
    verify_bundle.py <bundle_dir> [--quiet]

读 <bundle_dir>/bundle.json（由 prepare-release.sh 生成的计划），逐包校验：

  1. tar 里每条 manifest 条目的 RepoTags 是否与预期完全一致；
  2. 该条目的 config 里 architecture/os 是否为 linux/amd64；
  3. len(Layers) == len(rootfs.diff_ids) —— 经典 docker load 的硬性前提，
     不相等会被生产端的 load 直接拒绝；
  4. 计算 sha256（用于上传后核对传输完整性）。

把 size / sha256 / archs / ok 写回 bundle.json。有失败项时退出码为 1。

依赖：只用标准库。本机受管 Python 没有 pyyaml，所以这里不解析 YAML。
"""
import hashlib
import json
import pathlib
import sys
import tarfile

EXPECTED_ARCH = "amd64/linux"


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt_size(n: int) -> str:
    """与 render_deploy_doc.py 保持同一口径，免得控制台和 DEPLOY.md 数字对不上。"""
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f}GB"
    return f"{n / 1024 ** 2:.0f}MB"


def inspect_package(path: pathlib.Path):
    """从 tar 里读出所有镜像条目，返回 (tags, archs, layers_ok)。"""
    tags, archs, layers_ok = [], set(), True
    with tarfile.open(path) as t:
        try:
            manifest = json.load(t.extractfile("manifest.json"))
        except KeyError:
            raise SystemExit(
                f"{path.name}: 归档里没有 manifest.json，不是 docker 归档"
                f"（可能是纯 OCI 布局，经典 docker load 读不了）"
            )
        for entry in manifest:
            tags.extend(entry.get("RepoTags") or [])
            cfg = json.load(t.extractfile(entry["Config"]))
            archs.add(f"{cfg.get('architecture')}/{cfg.get('os')}")
            if len(entry["Layers"]) != len(cfg["rootfs"]["diff_ids"]):
                layers_ok = False
    return tags, archs, layers_ok


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    bundle = pathlib.Path(sys.argv[1])
    quiet = "--quiet" in sys.argv

    plan_path = bundle / "bundle.json"
    if not plan_path.exists():
        raise SystemExit(f"找不到 {plan_path}")

    plan = json.loads(plan_path.read_text())
    failures = 0

    if not quiet:
        print(f"{'文件':24s} {'体积':>9s} {'镜像':>4s}  架构          状态")
        print("-" * 76)

    for pkg in plan["packages"]:
        p = bundle / pkg["file"]
        if not p.exists():
            pkg["ok"] = False
            pkg["error"] = "文件不存在"
            failures += 1
            if not quiet:
                print(f"{pkg['file']:24s} {'-':>9s} {'-':>4s}  {'-':12s} 文件不存在")
            continue

        tags, archs, layers_ok = inspect_package(p)
        expected = list(pkg["images"])
        missing = [x for x in expected if x not in tags]
        extra = [x for x in tags if x not in expected]

        problems = []
        if missing:
            problems.append(f"缺少标签 {missing}")
        if extra:
            problems.append(f"多出标签 {extra}")
        if archs != {EXPECTED_ARCH}:
            problems.append(f"架构不是 {EXPECTED_ARCH}，实际 {sorted(archs)}")
        if not layers_ok:
            problems.append("Layers 与 rootfs.diff_ids 数量不一致")

        pkg["size"] = p.stat().st_size
        pkg["sha256"] = sha256_of(p)
        pkg["archs"] = sorted(archs)
        pkg["image_count"] = len(tags)
        pkg["ok"] = not problems
        if problems:
            pkg["error"] = "；".join(problems)
            failures += 1

        if not quiet:
            status = "OK" if pkg["ok"] else "FAIL " + pkg["error"]
            print(
                f"{pkg['file']:24s} {fmt_size(pkg['size']):>9s} "
                f"{pkg['image_count']:>4d}  {','.join(pkg['archs']):12s} {status}"
            )

    total = sum(p.get("size", 0) for p in plan["packages"])
    plan["total_size"] = total
    plan["verified"] = failures == 0
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")

    if not quiet:
        print("-" * 76)
        print(
            f"合计 {total / 1024 / 1024 / 1024:.2f} GB，"
            f"镜像 {sum(p.get('image_count', 0) for p in plan['packages'])} 个"
        )
        print("结论:", "全部通过" if failures == 0 else f"{failures} 个包失败")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
