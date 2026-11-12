"""运行时可用的 pg_compat 聚合管线扫描（从仓库 scripts/ 移植进 app）。

spec 057 把 ``scripts/check_pg_compat_pipeline_stages.py`` 的 ``find_aggregate_calls``
封装成了 admin-api 端点。但运行时的 admin-api 容器里只有 ``/app`` 代码，没有仓库根的
``scripts/`` 包，且原脚本写死扫描仓库目录（``services/admin-api``），在容器内既 import 不到
也扫不到东西。这里把核心逻辑移植进 ``app``（随镜像自动包含），并扫描运行时代码根 ``/app``，
阶段清单复用 ``core.pg_compat`` 的 ``SUPPORTED_AGGREGATION_STAGES``，避免双份定义不同步。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

from .pg_compat import SUPPORTED_AGGREGATION_STAGES

# 精确排除的目录名（与仓库 _scan_common.py 保持一致）
SKIP_DIR_NAMES = frozenset({
    "tests", "__pycache__", ".git", "node_modules", "site-packages",
    "migrations", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
    # vendored skill 包附带的 Office 打包/转换工具脚本，不是服务治理代码
    "skills_specs",
})
# 前缀排除（虚拟环境 / 工具缓存），按前缀匹配以覆盖 .venv-qa、.venv-p2 等
SKIP_DIR_PREFIXES = (".venv", "venv", ".tox", ".nox", ".eggs")

# 已知聚合阶段（与 SUPPORTED_AGGREGATION_STAGES 同源，仅用于从 $stage 提取时过滤噪声）
_KNOWN_STAGES = {
    "match", "sort", "limit", "skip", "count", "group", "project",
    "unwind", "facet", "lookup", "replaceroot", "bulkwrite",
}


def _should_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in SKIP_DIR_PREFIXES)


def iter_python_files(root_dir: str, *, staged: bool = False) -> Iterator[Path]:
    """遍历 root_dir 下的 .py 文件，剪枝虚拟环境/测试/缓存目录。"""
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # 就地剪枝：不让 os.walk 进入虚拟环境/缓存目录，避免遍历数十万文件超时
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def _extract_stages(text: str) -> list[str]:
    """从一段文本（如 aggregate([...] 的括号内容）中提取已知的聚合阶段。"""
    return [
        m.group(1).lower()
        for m in re.finditer(r"\$(\w+)", text, re.IGNORECASE)
        if m.group(1).lower() in _KNOWN_STAGES
    ]


def find_aggregate_calls(root_dir: str, *, staged: bool = False) -> list[dict]:
    """扫描 Python 文件中的 ``aggregate([...])`` 调用，返回不支持阶段的调用点。

    返回结构：``{"file": str, "line": int, "stage": str}``，供端点组装响应。
    """
    violations: list[dict] = []
    pattern = re.compile(r"aggregate\s*\(\s*\[", re.IGNORECASE)

    for py_file in iter_python_files(root_dir, staged=staged):
        try:
            source = Path(py_file).read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        for m in pattern.finditer(source):
            line_no = source.count("\n", 0, m.start()) + 1
            # 提取 [ 与匹配的右括号之间的内容，扫描其中的 $stage 用法
            bracket_count = 0
            extract_start = m.end() - 1  # 跳过 [
            in_string = False
            string_char: str | None = None
            for i in range(extract_start, len(source)):
                ch = source[i]
                if in_string:
                    if ch == string_char:
                        in_string = False
                    continue
                if ch in ('"', "'"):
                    in_string = True
                    string_char = ch
                    continue
                if ch == "[":
                    bracket_count += 1
                elif ch == "]":
                    bracket_count -= 1
                    if bracket_count == 0:
                        for stage in _extract_stages(source[extract_start:i]):
                            if stage not in SUPPORTED_AGGREGATION_STAGES:
                                violations.append({
                                    "file": str(py_file),
                                    "line": line_no,
                                    "stage": stage,
                                })
                        break

    return violations
