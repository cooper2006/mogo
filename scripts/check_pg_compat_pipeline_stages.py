#!/usr/bin/env python3
"""扫描仓库内所有 aggregate( 调用点的管道阶段，报告 unsupported。

行为：
- 遍历所有 .py 文件（剪枝排除 tests/、__pycache__、所有 .venv* 虚拟环境）
- 用正则查找 aggregate([...]) 语法
- 提取管道中的每个阶段 key（$match → match，$unwind → unwind 等）
- 若阶段不在 SUPPORTED_AGGREGATION_STAGES 中，记录违规行
- 输出：JSON 格式违规清单 + 人类可读摘要
- Exit code：0 = 全绿，1 = 有违规

用法：
    python3 scripts/check_pg_compat_pipeline_stages.py                  # 全量扫 services/
    python3 scripts/check_pg_compat_pipeline_stages.py services/admin-api
    python3 scripts/check_pg_compat_pipeline_stages.py --staged          # 只扫暂存的 .py
"""

import ast
import json
import re
import sys

from _scan_common import iter_python_files, parse_scan_args


# 支持的聚合阶段清单 - 必须与 pg_compat.py 中 SUPPORTED_AGGREGATION_STAGES 保持同步
SUPPORTED_AGGREGATION_STAGES = frozenset({
    "match", "sort", "limit", "skip", "count", "group", "project",
})


def find_aggregate_calls(root_dir: str, *, staged: bool = False) -> list[dict]:
    """扫描 Python 文件中的 aggregate() 调用（staged=True 只扫暂存文件）。"""
    violations = []

    for py_file in iter_python_files(root_dir, staged=staged):
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                source = f.read()
        except (UnicodeDecodeError, PermissionError):
            continue

        # 方法 1：使用 AST 解析查找直接的 aggregate() 调用
        # 方法 2：使用正则查找 aggregate(...) 模式（覆盖更广，包括字符串构造的 pipeline）
        # 我们使用兼容两种方法的混合方式

        # 正则模式查找 aggregate([...) - 这涵盖了大多数真实用法
        pattern = re.compile(
            r"aggregate\s*\(\s*\[",
            re.IGNORECASE,
        )

        for match in pattern.finditer(source):
            start_pos = match.start()
            # 找到对应的右括号位置，提取括号内的内容
            bracket_count = 0
            extract_start = match.end() - 1  # 跳过 [
            in_string = False
            string_char = None

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
                        # 找到匹配的右括号
                        bracket_content = source[extract_start:i]
                        # 提取阶段名称
                        found_stages = extract_stages(bracket_content)
                        for stage_info in found_stages:
                            if stage_info["stage"] not in SUPPORTED_AGGREGATION_STAGES:
                                violations.append({
                                    "file": str(py_file),
                                    "line": stage_info.get("line", 0),
                                    "stage": stage_info["stage"],
                                    "call_site": stage_info.get("context", ""),
                                })
                        break
                elif ch == "{" and not in_string:
                    # 跳过字典键值对中的花括号，只关注阶段模式
                    pass

        # 方法 2：AST 方法 - 查找 Call 节点，其中函数名是 aggregate
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr

                    if func_name.lower() == "aggregate" and isinstance(node.args, list):
                        # 这个 aggregate 调用有位置参数
                        for arg in node.args:
                            if isinstance(arg, ast.List):
                                for elt in arg.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        pipeline_str = elt.value
                                        found_stages = extract_stages_from_string(pipeline_str)
                                        for stage_info in found_stages:
                                            if stage_info["stage"] not in SUPPORTED_AGGREGATION_STAGES:
                                                # 找到对应的行号
                                                line = getattr(elt, "lineno", 0)
                                                violations.append({
                                                    "file": str(py_file),
                                                    "line": line,
                                                    "stage": stage_info["stage"],
                                                    "call_site": stage_info.get("context", ""),
                                                })
        except SyntaxError:
            # 如果文件语法错误，跳过 AST 解析
            pass

    return violations


def extract_stages_from_string(pipeline_str: str) -> list[dict]:
    """从管道字符串中提取阶段名称。"""
    stages = []

    # 匹配 $match → match，$unwind → unwind 等模式
    stage_pattern = re.compile(r"\$(\w+)", re.IGNORECASE)
    for m in stage_pattern.finditer(pipeline_str):
        stage_name = m.group(1).lower()
        # 只保留已知的阶段名称，跳过其他
        if stage_name in {
            "match", "sort", "limit", "skip", "count", "group", "project",
            "unwind", "facet", "lookup", "replaceRoot", "skip", "bulkWrite",
        }:
            stages.append({"stage": stage_name})

    return stages


def extract_stages(bracket_content: str) -> list[dict]:
    """从括号内容中提取阶段名称（兼容正则提取方式）。"""
    stages = []

    # 匹配 $match → match 等模式
    stage_pattern = re.compile(r"\$(\w+)", re.IGNORECASE)
    for m in stage_pattern.finditer(bracket_content):
        stage_name = m.group(1).lower()
        if stage_name in {
            "match", "sort", "limit", "skip", "count", "group", "project",
            "unwind", "facet", "lookup", "replaceRoot", "skip", "bulkWrite",
        }:
            stages.append({"stage": stage_name})

    return stages


def get_call_context(source: str, position: int) -> str:
    """获取调用点的上下文信息（前50个字符）。"""
    # 简单地返回源码片段作为上下文
    context_start = max(0, position - 40)
    context_end = min(len(source), position + 40)
    return source[context_start:context_end].replace("\n", " ")


def main():
    root_dir, staged = parse_scan_args(sys.argv[1:], default_root="services")

    violations = find_aggregate_calls(root_dir, staged=staged)

    if not violations:
        print("✅ All aggregate stages are supported or no aggregate calls found.")
        sys.exit(0)

    # 分组统计
    unsupported_by_file = {}
    for v in violations:
        file_path = v["file"]
        if file_path not in unsupported_by_file:
            unsupported_by_file[file_path] = []
        unsupported_by_file[file_path].append(v)

    # 输出人类可读摘要
    print(f"🚨 Found {len(violations)} unsupported aggregate stage(s):")
    print("=" * 60)

    for file_path, file_violations in sorted(unsupported_by_file.items()):
        print(f"\nFile: {file_path}")
        for v in file_violations:
            print(f"  Line {v['line']}: unsupported stage '{v['stage']}'")
            # 打印简短的上下文
            # print(f"       Context: {v.get('call_site', '')[:80]}...")

    # 输出 JSON 格式的违规清单
    json_output = {
        "total_violations": len(violations),
        "supported_stages": sorted(list(SUPPORTED_AGGREGATION_STAGES)),
        "violations": violations,
    }
    print("\n" + "=" * 60)
    print("JSON output for CI:")
    print(json.dumps(json_output, ensure_ascii=False, indent=2))

    print("=" * 60)
    sys.exit(1)


if __name__ == "__main__":
    main()