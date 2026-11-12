#!/usr/bin/env python3
"""058 T007 — 扫描 ``uuid4().hex`` 使用点，拦截**新增**的实体主键用法。

背景：全库主键已统一为时间有序的 32-hex（``app.core.ids.generate_hex32_id``，
见 docs/id-unification-hex32-runbook.md）。``uuid4().hex`` 无序，用作 ``_id``
会让高水位游标 / 分页游标语义倒退。

**渐进收口**：仓库存量仍有若干 ``uuid4().hex``（部分是有意保留的令牌/短ID），
一次性清零会阻断主干。因此本脚本以 ``scripts/uuid_hex_baseline.json`` 为基线，
只拦截基线之外**新增**的实体主键用法；每次替换一批后重新生成基线即可逐步收敛。

分类（决定哪些算「实体主键违规」）：
* 拦截：作为 ``_id`` / ``*_id`` / ``event_id`` 等整体赋值的完整 32-hex。
* 允许并登记：
  - 切片短 ID（``[:10]`` / ``[:12]``）——时间有序 ID 前 12 位是毫秒时间戳，
    同毫秒内前缀相同，直接替换会引入碰撞；
  - 带业务前缀的拼接、临时文件名、trace/request/call id ——非主键游标；
  - 令牌 / 密钥 / boundary / JWT jti ——时间有序会降熵，反而削弱安全性；
  - 注释与字符串字面量中的字面文本（用 ``tokenize`` 排除，不是代码调用）。

用法：
    python3 scripts/check_uuid_hex_usage.py --full                # 全量（CI）
    python3 scripts/check_uuid_hex_usage.py --staged              # 只扫暂存的 .py（pre-commit）
    python3 scripts/check_uuid_hex_usage.py --inventory           # 输出全量清单（T003）
    python3 scripts/check_uuid_hex_usage.py --update-baseline     # 重建基线（替换一批后执行）
    python3 scripts/check_uuid_hex_usage.py services/admin-api     # 限定范围

Exit code：0 = 无新增主键违规，1 = 发现新增违规。
"""
from __future__ import annotations

import io
import json
import re
import sys
import tokenize
from pathlib import Path

from _scan_common import iter_python_files, parse_scan_args

BASELINE_PATH = Path(__file__).with_name("uuid_hex_baseline.json")

#: 058 范围内需要收口的服务（sandbox-manager 等独立服务不在本特性范围）
DEFAULT_ROOT = "services"
IN_SCOPE_PREFIXES = (
    "services/admin-api/", "services/chat-api/", "services/document-parser/",
)

#: 匹配两种写法：``uuid.uuid4().hex`` 与 ``from uuid import uuid4; uuid4().hex``
CALL_RE = re.compile(r"(?:uuid\.)?uuid4\(\)\.hex\[?\s*[:0-9]*\]?")

#: 明确允许的非主键变量名 / 场景
_ALLOW_PATTERNS = (
    re.compile(r"uuid4\(\)\.hex\s*\["),                      # 切片短 ID
    re.compile(r"\b(?:token|secret|boundary|jti|nonce|salt|api_key|resume_token)\b", re.I),
    re.compile(r"\b(?:trace_id|request_id|call_id|attempt_id|scan_id|worker_id|session_id|subagent_id|recording_id|suspension_id)\b", re.I),
    re.compile(r'f["\'][^"\']*[A-Za-z_]+_["\']?\s*$'),     # f"prefix_{...}"
    re.compile(r"\.tmp|file_name|screenshot|avatar|boundary"),  # 临时文件名
)
EXEMPT_MARKER = "id-unification-hex32-exempt:"


def _code_only_lines(source: str) -> set[int]:
    """返回真正包含代码（非注释、非字符串字面量）的行号集合。"""
    code_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING):
                continue
            if tok.string.strip():
                code_lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        # 语法不完整的文件：退化到「跳过整行注释」的保守口径
        return {i for i, l in enumerate(source.split("\n"), 1)
                if l.strip() and not l.strip().startswith("#")}
    return code_lines


def _in_scope(path: Path) -> bool:
    return str(path).replace("\\", "/").startswith(IN_SCOPE_PREFIXES)


def _is_allowed(line: str) -> tuple[bool, str]:
    if EXEMPT_MARKER in line:
        return True, "显式豁免注释"
    for pattern in _ALLOW_PATTERNS:
        if pattern.search(line):
            return True, "令牌/短ID/追踪/临时文件名（非实体主键游标）"
    return False, "实体主键 / 事件 ID"


def _entry_key(entry: dict) -> str:
    """基线键：文件 + 代码文本（行号变化不会让基线失效）。"""
    return f'{entry["file"]}::{entry["code"]}'


def load_baseline() -> set[str]:
    if not BASELINE_PATH.is_file():
        return set()
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        return set(data.get("keys", []))
    except (json.JSONDecodeError, OSError):
        return set()


def scan(root_dir: str, *, staged: bool = False) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    allowed: list[dict] = []
    for py_file in iter_python_files(root_dir, staged=staged):
        if not _in_scope(py_file):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        code_lines = _code_only_lines(source)
        for lineno, line in enumerate(source.split("\n"), 1):
            if lineno not in code_lines or not CALL_RE.search(line):
                continue
            ok, reason = _is_allowed(line)
            entry = {
                "file": str(py_file), "line": lineno,
                "code": line.strip()[:160], "reason": reason,
            }
            (allowed if ok else violations).append(entry)
    return violations, allowed


def main() -> None:
    argv = sys.argv[1:]
    inventory_mode = "--inventory" in argv
    update_baseline = "--update-baseline" in argv
    root_dir, staged = parse_scan_args(argv, default_root=DEFAULT_ROOT)
    violations, allowed = scan(root_dir, staged=staged)
    all_entries = violations + allowed
    keys = sorted(_entry_key(e) for e in all_entries)

    if update_baseline:
        BASELINE_PATH.write_text(
            json.dumps({
                "note": "058 T007 基线：存量 uuid4().hex 用法。只拦截基线之外的新增；替换一批后重建。",
                "count": len(keys), "keys": keys,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"✅ 基线已写入 {BASELINE_PATH.name}（{len(keys)} 条：主键 {len(violations)} / 允许 {len(allowed)}）")
        sys.exit(0)

    if inventory_mode:
        print(json.dumps({
            "total": len(all_entries),
            "entity_primary_keys": len(violations),
            "allowed": len(allowed),
            "violations": violations,
            "allowed_usages": allowed,
        }, ensure_ascii=False, indent=2))
        sys.exit(0)

    baseline = load_baseline()
    new_violations = [v for v in violations if _entry_key(v) not in baseline]

    if not new_violations:
        print(f"✅ 无新增 uuid4().hex 实体主键用法"
              f"（存量主键 {len(violations)} 处已在基线，允许场景 {len(allowed)} 处）。")
        sys.exit(0)

    print(f"🚨 Found {len(new_violations)} NEW uuid4().hex entity primary-key usage(s):")
    print("=" * 60)
    for v in new_violations:
        print(f"\n{v['file']}:{v['line']}  [{v['reason']}]")
        print(f"    {v['code']}")
    print("\n" + "=" * 60)
    print("JSON output for CI:")
    print(json.dumps({"total_violations": len(new_violations), "violations": new_violations},
                     ensure_ascii=False, indent=2))
    print("\n修复：改用 from app.core.ids import generate_hex32_id；")
    print(f"若确属令牌/短ID 场景，请在行内加 `# {EXEMPT_MARKER} <理由>`；")
    print("若是有意保留的存量，执行 --update-baseline 重建基线。")
    sys.exit(1)


if __name__ == "__main__":
    main()
