#!/usr/bin/env python3
"""T036 消费方侧契约证据校验（FR-16 / FR-17）。

admin-web / user-web 是 Vue + TS 前端，**当前没有 vitest / 测试目录**，因此消费方侧
验证在 Python 工具里做**静态源码证据扫描**（而非跑前端单测）：校验契约声明的
interaction / 状态码 / 字段，确实能在消费方源码中找到调用与读取证据，防止契约臆造
（FR-16「契约由消费方定义」、FR-17「契约覆盖消费方实际读取字段」）。

检查项：
1. **path 证据（硬检查）**：契约的 ``base_path + path`` 必须出现在消费方源码的
   URL 字面量中（``/api/...``，支持 ``${id}`` / ``{id}`` 参数占位规范化）。
2. **notes 文件证据（硬检查）**：契约 ``notes`` 里声明的消费方源码文件路径必须存在
   （FR-17 要求逐条立约留痕）。
3. **字段证据（警告）**：契约 200 响应字段的叶子名应在消费方源码中出现（通用短名
   如 ``id``/``total`` 命中率高，只作最低限度证据，不阻断）。

用法::

    python3 tools/contract/consumer_refs.py --all
    python3 tools/contract/consumer_refs.py --service admin-api --source apps/admin-web/src

退出码：0 = 无违规；1 = 存在违规（缺 path 证据或 notes 文件不存在）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO / "specs" / "025-api-contract-hardening" / "contracts"
SERVICES = ("admin-api", "chat-api", "document-parser")

# 各契约的消费方源码根目录（相对 REPO）。document-parser 的消费方主要是服务端内部调用方。
DEFAULT_SOURCES = {
    "admin-api": [REPO / "apps" / "admin-web" / "src"],
    "chat-api": [REPO / "apps" / "user-web" / "src"],
    "document-parser": [
        REPO / "services" / "admin-api",
        REPO / "services" / "chat-api",
        REPO / "deploy",
    ],
}

_URL_LITERAL_RE = re.compile(r"""["'`]([^"'\s`]+)["'`]""")
_PARAM_RE = re.compile(r"(\$\{|\{)[^}\s]*\}")

# 契约 notes 中声明的消费方文件路径（相对 REPO 或相对仓库根）
_FILE_REF_RE = re.compile(
    r"(?:apps|services|deploy|packages)/[A-Za-z0-9_./\-\+]+\.(?:ts|vue|py|yml|yaml|tsx|js)"
)

# 已知「无消费方证据」但契约登记保留的 interaction（白名单，降级为 warn 不阻断）。
# 用于：契约按服务端路由完整立约、但当前无前端/服务端调用方的管理端端点。
# 白名单必须配套契约 gaps 登记，删除前需确认对应端点已接线或已从契约移除。
NO_CONSUMER_ALLOWLIST: dict[str, set[str]] = {
    # chat-api 契约登记的管理端端点：apps/user-web 无直接调用 URL
    "chat-api": {
        "list_skill_updates",
        "list_skill_share_inbox",
        "fetch_personal_knowledge",
        "list_site_profiles",
        "list_scheduled_jobs",
    },
}


def normalize_url(text: str) -> str:
    """把 URL 中的路径参数占位（``${id}`` / ``{id}``）归一化为 ``<p>``，剥掉 host 与 query 前缀。"""
    text = (text or "").split("?")[0].split("#")[0]
    text = _PARAM_RE.sub("<p>", text)
    text = text.replace("$", "")
    m = re.match(r"https?://[^/]+(/.*)$", text)
    if m:
        text = m.group(1)
    return "/" + text.strip("/")


def iter_source_files(root: Path) -> list[Path]:
    """列出源码根下所有前端/相关源码文件。"""
    if not root.exists():
        return []
    exts = {".ts", ".vue", ".tsx", ".js", ".py"}
    return sorted(p for p in root.rglob("*") if p.suffix in exts and "node_modules" not in p.parts)


def _path_of(raw: str) -> str | None:
    """从任意字符串字面量中提取路径部分。

    支持 ``http://host/api/x``、``/api/x``、``{base_url}/api/x``（f-string 拼接），
    无路径段（不含 ``/``）返回 None。
    """
    if "://" in raw:
        m = re.match(r"https?://[^/]+(/.*)$", raw)
        return m.group(1) if m else None
    i = raw.find("/")
    if i < 0:
        return None
    return raw[i:]


def collect_urls(files: list[Path]) -> set[str]:
    """收集消费方源码里出现的路径 URL 字面量（已归一化，含 f-string 拼接的前缀）。"""
    urls: set[str] = set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _URL_LITERAL_RE.finditer(text):
            raw = m.group(1)
            candidate = _path_of(raw)
            if candidate is None:
                continue
            if candidate.count("/") >= 2:  # 至少两段路径，过滤无关字符串
                urls.add(normalize_url(candidate))
    return urls


def collect_identifiers(files: list[Path]) -> set[str]:
    """收集消费方源码中出现的标识符（字段名候选）。"""
    idents: set[str] = set()
    ident_re = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{1,40})\b")
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in ident_re.finditer(text):
            idents.add(m.group(1))
    return idents


def _field_leaves(resp: dict) -> list[str]:
    """提取 200 响应字段的叶子名（``data[].id`` → ``id``）。"""
    leaves: list[str] = []
    for field in (resp.get("fields") or {}):
        leaf = field.split(".")[-1].split("[")[0].replace("[]", "")
        if leaf:
            leaves.append(leaf)
    return leaves


def check_contract_consumers(
    contract: dict,
    sources: list[Path],
    service: str = "",
) -> tuple[bool, list[str]]:
    """校验单份契约在消费方源码中的证据是否齐备。

    返回 ``(是否合规, 报告行列表)``。
    """
    problems: list[str] = []
    warns: list[str] = []
    base = contract.get("base_path", "")
    files = []
    for root in sources:
        files.extend(iter_source_files(root))
    if not files:
        return False, [f"[error] 消费方源码目录为空或不存在: {[str(r) for r in sources]}"]

    urls = collect_urls(files)
    idents = collect_identifiers(files)

    for item in contract.get("interactions") or []:
        if not isinstance(item, dict):
            continue
        full = normalize_url(f"{base}{item['path']}")
        bare = normalize_url(item["path"])
        # 命中判定：相等 / 前缀更深（如 /api/knowledge/documents/{id} 命中 /api/knowledge/documents）/
        # 消费方可能带额外前缀（nginx /askai-api 或 f"{base_url}" 拼接），因此允许契约 path
        # 作为消费方 URL 的**路径后缀**命中。
        hit = full in urls or any(u == full or u.endswith(full) for u in urls)
        hit = hit or any(u.startswith(full) for u in urls)
        if not hit and len(bare) >= 5:
            hit = bare in urls or any(u == bare or u.endswith(bare) for u in urls)
        if not hit:
            line = (
                f"{item.get('id', '?')}: 契约 path {item['path']} 在消费方源码"
                f"（{len(files)} 个文件，{len(urls)} 条 URL）中无调用证据"
            )
            if _is_no_consumer(item) or item.get("id") in NO_CONSUMER_ALLOWLIST.get(service, ()):
                warns.append("[warn] " + line + "（契约已标注零消费方，不阻断）")
            else:
                problems.append("[error] " + line)
        for resp in item.get("responses") or []:
            if isinstance(resp, dict) and resp.get("status", 0) < 400:
                for leaf in _field_leaves(resp):
                    if leaf and leaf not in idents:
                        warns.append(
                            f"[warn] {item.get('id', '?')}: 字段 {leaf!r} 未在消费方源码出现"
                        )
        # notes 声明的消费方文件必须存在
        for note in _notes_of(item):
            for ref in _FILE_REF_RE.findall(note):
                candidate = REPO / ref
                # 容错：契约 notes 有时省略根目录前缀（如 deploy/docker-compose.yml 实为
                # 仓库根 docker-compose.yml），同名文件兜底
                fallback = REPO / Path(ref).name
                if not candidate.exists() and not fallback.exists():
                    problems.append(
                        f"[error] {item.get('id', '?')}: notes 声明的消费方文件不存在: {ref}"
                    )

    report = []
    if warns:
        report.append("[warn] 消费方源码未出现的字段（通用短名可能误报，仅提示）:\n  " + "\n  ".join(warns))
    report.extend(problems)
    return (not problems), report


# 契约明确标注「零消费方」的 interaction 允许跳过 path 证据（gaps 已登记，如 skills/{id}/releases）
NO_CONSUMER_MARKERS = (
    "零消费方", "无消费方", "无前端", "未消费", "零前端",
    "no consumer", "no front-end", "zero front-end", "zero consumer",
    "无消费方当前", "尚无消费方", "没有消费方",
)


def _is_no_consumer(item: dict) -> bool:
    """判断契约是否明确标注该 interaction 当前无消费方。"""
    joined = " ".join(_notes_of(item)).lower()
    return any(marker.lower() in joined for marker in NO_CONSUMER_MARKERS)


def _notes_of(item: dict) -> list[str]:
    out = []
    if isinstance(item.get("notes"), str):
        out.append(item["notes"])
    for resp in item.get("responses") or []:
        if isinstance(resp, dict) and isinstance(resp.get("notes"), str):
            out.append(resp["notes"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service", choices=SERVICES, help="只检查指定服务（默认全部）"
    )
    parser.add_argument(
        "--source",
        action="append",
        type=Path,
        help="指定消费方源码根目录（可多次；默认按服务映射）",
    )
    parser.add_argument("--all", action="store_true", help="检查全部三份契约")
    parser.add_argument("--no-fields", action="store_true", help="跳过字段证据警告")
    args = parser.parse_args(argv)

    if args.service:
        targets = [(CONTRACTS_DIR / f"{args.service}.yaml", args.service)]
        sources_map = {args.service: args.source or DEFAULT_SOURCES[args.service]}
    else:
        targets = [(CONTRACTS_DIR / f"{name}.yaml", name) for name in SERVICES]
        sources_map = {name: DEFAULT_SOURCES[name] for name in SERVICES}

    ok_all = True
    for path, service in targets:
        if not path.exists():
            print(f"{service}: 契约文件不存在: {path}")
            ok_all = False
            continue
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        ok, report = check_contract_consumers(contract, sources_map.get(service, []), service)
        ok_all = ok_all and ok
        for line in report:
            if args.no_fields and line.startswith("[warn]"):
                continue
            print(line)
        print(f"{service}: consumer-refs check {'OK' if ok else 'FAILED'}")

    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
