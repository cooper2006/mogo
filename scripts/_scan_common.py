"""静态扫描脚本共享工具：Python 文件遍历 + --staged 支持。

背景（059/057 CI 接线时发现）：
- 各服务目录存在 ``.venv`` / ``.venv-qa`` / ``.venv-p2`` 等多个虚拟环境，
  旧实现只精确排除 ``.venv``，导致扫描命中第三方库（41 个假违规）且
  ``rglob`` 遍历数十万文件而超时。这里改为**目录名前缀剪枝**。
- pre-commit 需要只检查本次暂存的 ``.py``（--staged），CI 跑全量。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterator

#: 精确排除的目录名
SKIP_DIR_NAMES = frozenset({
    "tests", "__pycache__", ".git", "node_modules", "site-packages",
    "migrations", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
    # vendored skill 包附带的 Office 打包/转换工具脚本（docx/pptx/xlsx），
    # 不是服务治理代码；其 `except: return True` 是「需要 shim / 跳过校验」，
    # 与 fail-closed 准入无关，纳入扫描只会产生噪声。
    "skills_specs",
})

#: 前缀排除（虚拟环境 / 工具缓存），按前缀匹配以覆盖 .venv-qa、.venv-p2 等
SKIP_DIR_PREFIXES = (".venv", "venv", ".tox", ".nox", ".eggs")


def should_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in SKIP_DIR_PREFIXES)


def has_skipped_part(path: Path) -> bool:
    return any(should_skip_dir(part) for part in path.parts)


def staged_python_files() -> list[Path]:
    """返回本次提交中暂存（新增/复制/修改）且存在的 .py 文件。"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, check=False,
    )
    files: list[Path] = []
    for line in result.stdout.splitlines():
        rel = line.strip()
        if not rel or not rel.endswith(".py"):
            continue
        path = Path(rel)
        if has_skipped_part(path) or not path.is_file():
            continue
        files.append(path)
    return files


def iter_python_files(root_dir: str, *, staged: bool = False) -> Iterator[Path]:
    """遍历待扫描的 Python 文件。

    staged=True  → 只扫 git 暂存区中的 .py（pre-commit 用）。
    staged=False → os.walk 遍历 root_dir，剪枝掉虚拟环境/测试/缓存目录（CI 全量用）。
    """
    if staged:
        yield from staged_python_files()
        return

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # 就地剪枝：不让 os.walk 进入虚拟环境/缓存目录，避免遍历数十万文件超时
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def parse_scan_args(argv: list[str], default_root: str) -> tuple[str, bool]:
    """解析 CLI：位置参数 root_dir + 可选 --staged / --full。

    返回 (root_dir, staged)。--full 显式表示全量（等价于不给 --staged）。
    """
    staged = "--staged" in argv
    positional = [a for a in argv if not a.startswith("-")]
    root_dir = positional[0] if positional else default_root
    return root_dir, staged
