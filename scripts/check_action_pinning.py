#!/usr/bin/env python3
"""022 FR-26 (T050)：校验发布关键 GitHub Actions 固定到不可变版本。

背景
----
GitHub Marketplace 的 tag（`@v6`、`@v4`）是**可移动的引用**：上游可以重打 tag，
或被 `gh action edit` 替换指向。对**产生发布产物或推送凭据**的动作来说，
一个被篡改的 tag 等于一次供应链入侵（参考 log4j、event-stream、codecov）。

本脚本把「哪些动作必须用不可变 SHA」变成一条**可执行的政策**，而不是
只写在文档里。策略：

- **必须 SHA 固定**（`MUST_PIN`）：构建 / 推送 / 登录 / 证明镜像来源的动作。
  这些动作直接决定发布产物的字节内容与去向。
- **允许 tag 固定**（`TAG_OK`）：只读源码、装运行时、跑通用工具的动作。
  它们无法修改产物；风险由 dependabot 的 `github-actions` 周更兜住。
- 其余动作一律失败，逼着新增时显式归类（fail-closed）。

用法
----
    python scripts/check_action_pinning.py                 # 扫描 .github/workflows/*.yml
    python scripts/check_action_pinning.py --json          # 机器可读输出

退出码 0 = 全部达标；1 = 存在未固定到 SHA 的发布关键动作。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# SHA 固定：40 位十六进制 commit（或 7–40 位短 SHA 也接受，但推荐完整）。
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")

# ── 必须 SHA 固定的动作 ─────────────────────────────────────────────────
# 判断标准：这个动作的输出会成为发布产物，或它持有推送产物所需的凭据。
MUST_PIN: dict[str, str] = {
    "docker/build-push-action": "构建并推送镜像 —— 决定发布产物的字节",
    "docker/login-action": "持有 GHCR 推送凭据",
    "docker/setup-buildx-action": "提供 buildx 后端，影响构建结果",
    "docker/setup-qemu-action": "提供交叉编译平台，影响多架构产物",
    "docker/metadata-action": "决定镜像 tag / label 归属",
    "actions/attest-build-provenance": "签发供应链证明",
    "aquasecurity/trivy-action": "安全扫描结论决定放行与否",
}

# ── 允许 tag 固定的动作（并说明理由）────────────────────────────────────
TAG_OK: dict[str, str] = {
    "actions/checkout": "只读拉取仓库内容，dependabot 周更",
    "actions/setup-python": "安装 Python 解释器，无法影响产物",
    "actions/setup-node": "安装 Node 运行时，无法影响产物",
    "pnpm/action-setup": "安装 pnpm CLI，无法影响产物",
    "actions/cache": "只读写缓存",
    "actions/upload-artifact": "上传构建中间产物，不进入发布路径",
    "actions/download-artifact": "下载构建中间产物",
    "actions/upload-pages-artifact": "上传静态站点，不进入容器发布路径",
    "actions/deploy-pages": "部署静态站点，与容器发布分离",
    "actions/stale": "关闭长期无活动的 issue",
    "actions/github-script": "通用脚本，需单独审计",
    "softprops/action-gh-release": "创建 release，dependabot 跟踪",
    "pypa/gh-action-pypi-publish": "PyPI 发布，仓库已无 Python 包发布",
    "dawidd6/action-download-artifact": "下载跨仓库产物",
}

# 第三方自托管动作：必须 SHA（它们不受 GitHub Marketplace 审阅约束）。
SELF_HOSTED = ("docker/", "aquasecurity/", "softprops/", "dawidd6/", "pypa/", "grafana/")

# ── 迁移期豁免 ─────────────────────────────────────────────────────────
# 记录**已知且已评审**的未达标动作。CI 只阻断「不在豁免表里」的违规，
# 所以新增一个未固定的发布动作会立即失败，而存量欠债可按节奏清。
#
# 每条豁免必须写明：为什么现在还不能固定、以及固定的阻塞原因。
# 当前阻塞：仓库环境无法访问 GitHub API 解析 tag → commit 的映射，
# 需要在有网络的环境运行 `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`
# 拿到 SHA 后再固定。跟踪项见 docs/security/VULNERABILITY_POLICY.md §5。
PINNING_EXCEPTIONS: dict[str, str] = {
    "docker/build-push-action@v6": "待解析 v6 → commit SHA；发布路径产物字节",
    "docker/setup-buildx-action@v4": "待解析 v4 → commit SHA；构建后端",
    "docker/login-action@v4": "待解析 v4 → commit SHA；持有 GHCR 凭据",
    "docker/setup-qemu-action@v4": "待解析 v4 → commit SHA；多架构产物",
    "docker/metadata-action@v5": "待解析 v5 → commit SHA；tag/label 归属",
    "actions/attest-build-provenance@v4": "待解析 v4 → commit SHA；证明签发",
    "sigstore/cosign-installer@v3": "待解析 v3 → commit SHA；keyless 签名工具安装",
}


def extract_uses(path: Path) -> list[tuple[int, str]]:
    """返回 [(行号, owner/repo@ref)]。"""
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = USES_RE.match(line)
        if m:
            out.append((lineno, m.group(1).strip()))
    return out


def classify(ref: str) -> tuple[str, str | None]:
    """返回 (判定, 理由)。判定 ∈ {ok-sha, ok-tag, fail}。"""
    if "@" not in ref:
        return "fail", "缺少 @ref"
    name, _, rev = ref.rpartition("@")
    # 去掉 URL 片段（不合法但宽容解析）
    rev = rev.split("#", 1)[0]

    verdict = "fail"
    reason = None
    if SHA_RE.match(rev):
        verdict = "ok-sha"
        reason = "已固定到 commit SHA"
    elif ref in PINNING_EXCEPTIONS:
        verdict = "exception"
        reason = f"迁移期豁免：{PINNING_EXCEPTIONS[ref]}"
    else:
        reason = MUST_PIN.get(name)
        if reason:
            reason = f"发布关键动作必须 SHA 固定：{reason}"
        elif name in TAG_OK:
            verdict = "ok-tag"
            reason = TAG_OK[name]
        elif name.startswith(SELF_HOSTED):
            reason = f"第三方自托管动作 {name} 必须 SHA 固定"
        else:
            reason = f"{name} 未归类：请加入 MUST_PIN 或 TAG_OK"
    return verdict, reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if not WORKFLOWS_DIR.is_dir():
        print(f"错误：{WORKFLOWS_DIR} 不存在", file=sys.stderr)
        return 2

    findings: list[dict] = []
    counts = {"ok-sha": 0, "ok-tag": 0, "exception": 0, "fail": 0}

    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml")):
        for lineno, ref in extract_uses(wf):
            verdict, reason = classify(ref)
            counts[verdict] += 1
            if verdict in ("exception", "fail"):
                findings.append(
                    {
                        "file": wf.relative_to(REPO_ROOT).as_posix(),
                        "line": lineno,
                        "ref": ref,
                        "verdict": verdict,
                        "reason": reason,
                    }
                )

    failures = [f for f in findings if f["verdict"] == "fail"]
    exceptions = [f for f in findings if f["verdict"] == "exception"]

    if args.json:
        print(json.dumps({"counts": counts, "findings": findings}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    for f in exceptions:
        print(f"⚠  {f['file']}:{f['line']}  {f['ref']}")
        print(f"    {f['reason']}")

    for f in failures:
        print(f"✗ {f['file']}:{f['line']}  {f['ref']}")
        print(f"    原因：{f['reason']}")

    print(f"\n合计：{counts['ok-sha']} 个 SHA 固定，{counts['ok-tag']} 个 tag 固定（已归类），"
          f"{len(exceptions)} 个迁移期豁免，{len(failures)} 个未达标")

    if exceptions:
        print("\n迁移期豁免（已评审，不阻断 CI）：")
        for ref, why in sorted(PINNING_EXCEPTIONS.items()):
            print(f"  - {ref}：{why}")

    if failures:
        print("\n修复：把发布关键动作固定到 commit SHA，例如")
        print("  docker/build-push-action@v6  →  docker/build-push-action@<40位SHA>（= v6 指向的 commit）")
        print("或把新动作加入 check_action_pinning.py 的 MUST_PIN / TAG_OK 分类表。")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
