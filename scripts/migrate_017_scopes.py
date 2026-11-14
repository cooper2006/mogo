"""017 / D4 一次性切换：`memories` 范围模型迁移脚本（T039 / T040）。

把历史记忆从 ``personal / workspace / org`` + ``workspace_id / org_id``
一次性转换成目标态 ``personal / project / department`` +
``project_id / project_owner_id / department_id``。D4 **不设运行时兼容层**：
代码替换（B2 / M1）与数据迁移（B6 / M2）必须在同一维护窗口原子切换，
回滚必须「代码回退 + 本脚本 ``--reverse``」成对执行。

设计依据
--------
`specs/017-three-scope-memory/design-2026-11-05-project-department-scopes.md`
§10（M0–M4、S1–S7、成对回滚 SOP、R9 / R15）、§2.2（memories schema）、
§9.2（地址空间）、§11（SC-10 / SC-15）；
`tasks.md` T039 / T040 / T041 / T042。

纪律（与 `scripts/migrate_046_project_dimension.py` 同款）
---------------------------------------------------------
- 默认 **dry-run**：只打印统计与失败清单，不写任何数据库文档；``--apply`` 才落盘。
- **可重入**：所有写操作都由「当前文档状态」推导，连续第二次执行 0 条变更。
- 失败清单落 JSON 文件（``--report`` 可指定，默认
  ``services/chat-api/backups/017-scope-cutover-<mode>-<ts>.json``）。
- 全程带 ``tenant_id`` 边界：逐租户处理，每条 find / update 都带 tenant_id；
  缺 tenant_id 的历史行 fail-closed 归档，不猜测归属。
- 连接用 motor / asyncio（与 046 脚本一致）；``_get_db`` 延迟 import，
  因此 ``--help`` / ``--self-test`` 在未安装 motor 时也能运行。

T040 —— 写入边界（硬性，脚本任何路径都不得违反）
------------------------------------------------
以下集合 **只读，禁止写入**（只读查询 find / find_one / count_documents 允许）：

    projects / org_units / end_user_org_relations / chat_sessions

脚本**默认只写** ``memories``（S1–S7 与 S6 的 memories 文本字段改写）。
用户通过 ``--address-source`` 追加的其它持久化引用源默认 **只盘点不改写**；
仅当运维显式用 ``--address-allow-rewrite COLLECTION`` 授权、且该集合不在只读
白名单内时才改写，落盘前仍由 ``_assert_writable`` 强制拦截白名单集合。
049 的 ``member_user_ids`` 已在 ``projects`` 上，017 不迁移、不复制、不建镜像集合。

步骤
----
S1 scope 值 ``workspace→project`` / ``org→department``（personal 不变）。
S2 字段 ``$rename``：``workspace_id→project_id``、``org_id→department_id``，
   并 ``$unset`` 旧字段残留；新旧并存且值冲突时不覆盖新字段、进清单。
S3 按 ``{tenant_id, _id: project_id}`` 反查 ``projects.user_id`` 回填
   ``project_owner_id``；命中多行（N1 同名项目）或零行一律标 ``archived``
   进失败清单，**不得猜测性归属**。
S4 ``project_id == "default"`` 的记忆标 ``archived``（N2 兜底行）。
S5 校验 ``department_id`` 是真实 ``org_units`` 节点且 tenant_id 匹配，
   否则标 ``archived``（D3）；脚本不固化部门名单。
S6 盘点 / 改写持久化旧地址 ``mogo://memory/workspace|org/...``，
   产出「已改写 / 需人工确认 / 无法解析」三清单；无法定位只登记不重写。
S7 其它孤儿（未知 scope、缺 project_owner_id、缺归属 id）统一 ``archived``。

--reverse 边界（重要）
----------------------
还原 S1 / S2 / S6（逆映射），并 ``$unset`` 删除 S3 补的 ``project_owner_id``；
**明确不撤销 S4 / S7 写入的 ``archived`` 标记**（避免把已判定越权的记忆
重新放出），由管理员按失败清单手工决定。输出会打印 WARN。
reverse 是对 ``memories`` 的整库逆映射，仅在成对回滚窗口、已冻结写入时执行。

Usage
-----
    # 1) 永远先跑 dry-run，核对统计与失败清单，不写库
    python3 scripts/migrate_017_scopes.py

    # 2) 维护窗口内冻结写入后落盘（可重入，第二次 0 条）
    python3 scripts/migrate_017_scopes.py --apply

    # 3) 成对回滚：先回退代码，紧接着执行数据反向迁移
    python3 scripts/migrate_017_scopes.py --reverse --apply

    # 只处理单租户 / 指定报告路径 / 追加外部持久化引用盘点源
    python3 scripts/migrate_017_scopes.py --tenant-id t1 \\
        --report /tmp/017-report.json \\
        --address-source chat_sessions.context \\
        --address-source position_role_audit_logs.details

    # 不连库的纯函数自测
    python3 scripts/migrate_017_scopes.py --self-test
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

# --------------------------------------------------------------------------
# 连接与常量
# --------------------------------------------------------------------------

MONGO_URI = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("MOGO_DB_NAME") or "mogo"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPORT_DIR = os.path.join(REPO_ROOT, "services", "chat-api", "backups")

COLLECTION_MEMORIES = "memories"
COLLECTION_PROJECTS = "projects"
COLLECTION_ORG_UNITS = "org_units"

#: T040：只读集合白名单。脚本任何写入路径在落盘前都会用 _assert_writable 拦截。
READONLY_COLLECTIONS = frozenset({
    COLLECTION_PROJECTS,
    COLLECTION_ORG_UNITS,
    "end_user_org_relations",
    "chat_sessions",
})

SCOPE_MAP = {"workspace": "project", "org": "department"}
REVERSE_SCOPE_MAP = {"project": "workspace", "department": "org"}
NEW_SCOPES = frozenset({"personal", "project", "department"})
DEFAULT_PROJECT_ID = "default"
FIELD_RENAMES = (("workspace_id", "project_id"), ("org_id", "department_id"))
REVERSE_FIELD_RENAMES = (("project_id", "workspace_id"), ("department_id", "org_id"))

#: S6 默认扫描的 memories 文本字段（持久化地址可能落在分层内容里）。
MEMORY_TEXT_FIELDS = ("content", "l0_summary", "l1_overview", "l2_raw")

_ADDR_CANDIDATE_TMPL = r"mogo://memory/(?:{scopes})/[^\s\"'<>]+"
_ADDR_FULL_RE = re.compile(
    r"mogo://memory/(?P<scope>[^/\s\"'<>]+)/(?P<owner>[^/\s\"'<>]+)/"
    r"(?P<memory_id>[^/\s\"'<>]+)(?:/(?P<tier>[^/\s\"'<>]+))?"
)


def _timestamp() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log(kind: str, message: str) -> None:
    print(f"[{kind}] {message}", file=sys.stderr if kind in ("ERROR", "WARN") else sys.stdout)


def _default_report_path(mode: str) -> str:
    # 不写死任何已有备份文件名；每次执行带 UTC 时间戳。
    return os.path.join(DEFAULT_REPORT_DIR, f"017-scope-cutover-{mode}-{_timestamp()}.json")


def _get_db() -> Any:
    """Lazily import motor so the module can be imported / --help / --self-test without it."""
    from motor.motor_asyncio import AsyncIOMotorClient

    return AsyncIOMotorClient(MONGO_URI)[DB_NAME]


def _assert_writable(collection: str) -> None:
    """T040 硬约束：只读集合绝不写。"""
    if collection in READONLY_COLLECTIONS:
        raise RuntimeError(
            f"T040 violation: collection {collection!r} is read-only for this migration "
            f"(readonly={sorted(READONLY_COLLECTIONS)})"
        )


# --------------------------------------------------------------------------
# 纯函数：地址改写（S6）
# --------------------------------------------------------------------------


def _candidate_re(mapping: dict[str, str]) -> re.Pattern[str]:
    scopes = "|".join(re.escape(key) for key in mapping)
    return re.compile(_ADDR_CANDIDATE_TMPL.format(scopes=scopes))


def remap_scope_segment(uri: str, mapping: dict[str, str]) -> tuple[str | None, str | None]:
    """把 ``mogo://memory/<旧段>/<owner>/<id>/[tier]`` 的 scope 段按 mapping 改写。

    返回 ``(new_uri, memory_id)``；无法解析或 scope 段不在 mapping 中返回
    ``(None, None)``。owner 段与 tier 段保持不变（设计文档 §2.1、§9.2：
    owner 仍是归属人 id，不改成项目 / 部门 id）。
    """
    parsed = _ADDR_FULL_RE.fullmatch(uri.strip())
    if not parsed:
        return None, None
    old_scope = parsed.group("scope")
    if old_scope not in mapping:
        return None, None
    tier = parsed.group("tier")
    new_uri = (
        f"mogo://memory/{mapping[old_scope]}/{parsed.group('owner')}/"
        f"{parsed.group('memory_id')}" + (f"/{tier}" if tier else "")
    )
    return new_uri, parsed.group("memory_id")


def find_address_candidates(text: str, mapping: dict[str, str]) -> list[dict[str, Any]]:
    """从一段文本里找出所有旧地址候选，供 DB 层按 memory_id 定位后分类。

    每个候选形如 ``{"old_uri", "new_uri", "memory_id", "parse_error"}``。
    ``parse_error`` 非空表示「无法解析」清单条目。
    """
    out: list[dict[str, Any]] = []
    for match in _candidate_re(mapping).finditer(text):
        old_uri = match.group(0)
        new_uri, memory_id = remap_scope_segment(old_uri, mapping)
        if new_uri is None:
            out.append({"old_uri": old_uri, "new_uri": None, "memory_id": None,
                        "parse_error": "地址段数 / 格式无法解析"})
        else:
            out.append({"old_uri": old_uri, "new_uri": new_uri, "memory_id": memory_id,
                        "parse_error": None})
    return out


def _coerce_text(value: Any) -> tuple[str | None, str | None]:
    """把字段值转成可扫描文本：str 直接用；dict/list 用 JSON 往返。"""
    if isinstance(value, str):
        return value, "str"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False), "json"
    return None, None


def _restore_text(text: str, kind: str) -> Any:
    if kind == "json":
        return json.loads(text)
    return text


# --------------------------------------------------------------------------
# 纯函数：S1–S5 / S7 判定（Evaluation）
# --------------------------------------------------------------------------


@dataclass
class Lookup:
    """DB 层预先查好的上下文，传入纯函数，保证判定可单测。"""

    tenant_id: str = ""
    project_match_count: int = 0
    project_owner_id: str | None = None
    org_unit_valid: bool = True


@dataclass
class Evaluation:
    """一条 memories 文档需要执行的写动作与清单原因。"""

    scope_set: str | None = None
    rename: dict[str, str] = field(default_factory=dict)
    unset: dict[str, str] = field(default_factory=dict)
    set_fields: dict[str, Any] = field(default_factory=dict)
    archive_reasons: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)

    def write_count(self) -> int:
        return (
            (1 if self.scope_set else 0)
            + len(self.rename)
            + len(self.unset)
            + len(self.set_fields)
        )

    def as_update(self) -> dict[str, Any]:
        """合并成一次 MongoDB update（$set / $rename / $unset 字段互不重叠）。"""
        update: dict[str, Any] = {}
        set_ops: dict[str, Any] = {}
        if self.scope_set:
            set_ops["scope"] = self.scope_set
        set_ops.update(self.set_fields)
        if set_ops:
            update["$set"] = set_ops
        if self.rename:
            update["$rename"] = dict(self.rename)
        if self.unset:
            update["$unset"] = dict(self.unset)
        return update


def evaluate_document(doc: dict[str, Any], lookup: Lookup) -> Evaluation:
    """S1/S2/S3/S4/S5/S7 的纯判定。S6 由 DB 层处理（需要查库定位记忆）。

    基于「迁移前 doc」推导出全部动作：内部先算出迁移后的 scope 与字段视图，
    再据此做归档判定。所有判定都 fail-closed，禁止猜测性归属。
    """
    ev = Evaluation()
    old_scope = str(doc.get("scope") or "")
    new_scope = SCOPE_MAP.get(old_scope, old_scope)

    # S1：scope 值转换
    if old_scope in SCOPE_MAP:
        ev.scope_set = new_scope
        ev.steps.append("S1")

    # S2：$rename 旧字段 + $unset 残留
    for old_f, new_f in FIELD_RENAMES:
        if old_f not in doc:
            continue
        ev.steps.append("S2")
        if new_f in doc:
            if doc.get(new_f) == doc.get(old_f):
                ev.unset[old_f] = ""  # 新旧并存且值一致：只清残留
            else:
                ev.conflicts.append(
                    f"{old_f} 与 {new_f} 并存且值冲突：不覆盖 {new_f}，仅登记并清理旧字段"
                )
                ev.unset[old_f] = ""
        else:
            ev.rename[old_f] = new_f

    # 迁移后的「有效字段视图」
    pid = doc["project_id"] if "project_id" in doc else doc.get("workspace_id")
    dept = doc["department_id"] if "department_id" in doc else doc.get("org_id")
    po = doc.get("project_owner_id")

    # S3：project_owner_id 回填（N1 / D8）
    if pid and str(pid) != DEFAULT_PROJECT_ID:
        if not po:
            if lookup.project_match_count == 1 and lookup.project_owner_id:
                ev.set_fields["project_owner_id"] = lookup.project_owner_id
                ev.steps.append("S3")
            else:
                if lookup.project_match_count > 1:
                    ev.archive_reasons.append(
                        "S3: {tenant_id, _id: project_id} 命中多行（N1 同名项目），不得猜测归属"
                    )
                else:
                    ev.archive_reasons.append(
                        "S3: {tenant_id, _id: project_id} 命中零行，不得猜测归属"
                    )
                ev.steps.append("S3")

    # S4：default 兜底行（N2 / D7）
    if pid and str(pid) == DEFAULT_PROJECT_ID:
        ev.archive_reasons.append(
            f"S4: project_id == {DEFAULT_PROJECT_ID!r}（N2 租户共享兜底行，禁止承载项目记忆）"
        )
        ev.steps.append("S4")

    # S5：部门节点校验（D3）—— 所有非空 department_id 都校验，不合规归档
    if dept and str(dept).strip() and not lookup.org_unit_valid:
        ev.archive_reasons.append(
            "S5: department_id 不是本租户真实 org_units 节点（D3）"
        )
        ev.steps.append("S5")

    # S7：其它孤儿统一归档
    if new_scope not in NEW_SCOPES:
        ev.archive_reasons.append(f"S7: 未知 scope {old_scope!r}")
        ev.steps.append("S7")
    if new_scope == "project":
        if not pid:
            ev.archive_reasons.append("S7: project 记忆缺 project_id（缺归属 id）")
            ev.steps.append("S7")
        if not po and "project_owner_id" not in ev.set_fields:
            ev.archive_reasons.append("S7: project 记忆缺 project_owner_id（N1）")
            ev.steps.append("S7")
    if new_scope == "department" and not dept:
        ev.archive_reasons.append("S7: department 记忆缺 department_id（缺归属 id）")
        ev.steps.append("S7")

    # 归档 + 幂等：已 archived 的文档不重复写 archived，保证第二次 0 条变更。
    if ev.archive_reasons and doc.get("archived") is not True:
        ev.set_fields["archived"] = True
    return ev


def evaluate_reverse(doc: dict[str, Any]) -> Evaluation:
    """--reverse 的纯判定：还原 S1/S2、删除 S3 补的 project_owner_id。

    **刻意不碰 ``archived``**：S4 / S7 写入的归档标记不自动撤销。
    """
    ev = Evaluation()
    scope = str(doc.get("scope") or "")
    if scope in REVERSE_SCOPE_MAP:
        ev.scope_set = REVERSE_SCOPE_MAP[scope]
        ev.steps.append("S1-rev")

    for old_f, new_f in REVERSE_FIELD_RENAMES:
        if old_f not in doc:
            continue
        ev.steps.append("S2-rev")
        if new_f in doc:
            if doc.get(new_f) == doc.get(old_f):
                ev.unset[old_f] = ""
            else:
                ev.conflicts.append(
                    f"{new_f} 与 {old_f} 并存且值冲突（reverse）：不覆盖，仅清理 {old_f}"
                )
                ev.unset[old_f] = ""
        else:
            ev.rename[old_f] = new_f

    if "project_owner_id" in doc:
        ev.unset["project_owner_id"] = ""
        ev.steps.append("S3-rev")
    return ev


# --------------------------------------------------------------------------
# DB 层：查询（只读）+ 写入
# --------------------------------------------------------------------------


async def _tenant_ids(db: Any, only: str | None) -> list[str]:
    if only:
        return [only]
    values = await db[COLLECTION_MEMORIES].distinct("tenant_id")
    return [str(v) for v in values if v]


async def _lookup_for(db: Any, tenant_id: str, doc: dict[str, Any]) -> Lookup:
    """S3 / S5 的只读查询，全程带 tenant_id 边界。"""
    lookup = Lookup(tenant_id=tenant_id)
    pid = doc["project_id"] if "project_id" in doc else doc.get("workspace_id")
    dept = doc["department_id"] if "department_id" in doc else doc.get("org_id")

    if pid and str(pid) != DEFAULT_PROJECT_ID and not doc.get("project_owner_id"):
        # N1：唯一索引是 {tenant_id, user_id, workspace_id}，`_id` 在租户内
        # 不保证唯一（pg_compat / 双后端下同名 project_id 可有多行）。
        # 因此不能用 find_one（会掩盖多行），必须统计全部匹配行。
        rows = await db[COLLECTION_PROJECTS].find(
            {"tenant_id": tenant_id, "_id": pid}
        ).to_list(length=None)
        lookup.project_match_count = len(rows)
        if len(rows) == 1:
            lookup.project_owner_id = str(rows[0].get("user_id") or "") or None

    if dept and str(dept).strip():
        # 真实字段：org_units._id / tenant_id / path_ids / status（directory.py:284-298）。
        # S5 只校验节点存在且 tenant 匹配；path_ids 后代展开留给读取时动态重算。
        count = await db[COLLECTION_ORG_UNITS].count_documents(
            {"tenant_id": tenant_id, "_id": dept}
        )
        lookup.org_unit_valid = count > 0
    return lookup


async def _memory_exists(db: Any, tenant_id: str, memory_id: str) -> bool:
    return await db[COLLECTION_MEMORIES].count_documents(
        {"tenant_id": tenant_id, "memory_id": memory_id}
    ) > 0


async def _classify_addresses(
    db: Any,
    tenant_id: str,
    candidates: list[dict[str, Any]],
    *,
    source_label: str,
    allow_rewrite: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """S6 分类：返回 (rewritten, need_manual_review, unparseable, replaced_uris)。

    - 无法解析            -> unparseable（无法解析）
    - 无法按 memory_id 定位对应记忆 -> need_manual_review（只登记不重写）
    - 允许改写且能定位    -> rewritten（已改写）
    - 只读源 / 未授权改写  -> need_manual_review（只登记不重写）
    """
    rewritten: list[dict[str, Any]] = []
    need_review: list[dict[str, Any]] = []
    unparseable: list[dict[str, Any]] = []
    replaced: set[str] = set()

    for cand in candidates:
        base = {"tenant_id": tenant_id, "source": source_label, "old_uri": cand["old_uri"]}
        if cand["parse_error"]:
            unparseable.append({**base, "reason": cand["parse_error"]})
            continue
        located = await _memory_exists(db, tenant_id, cand["memory_id"])
        if not located:
            need_review.append({
                **base, "new_uri": cand["new_uri"], "memory_id": cand["memory_id"],
                "reason": "无法定位对应记忆（只登记不重写）",
            })
            continue
        if not allow_rewrite:
            need_review.append({
                **base, "new_uri": cand["new_uri"], "memory_id": cand["memory_id"],
                "reason": "持久化引用源只读 / 未授权改写（T040），只登记不重写",
            })
            continue
        rewritten.append({
            **base, "new_uri": cand["new_uri"], "memory_id": cand["memory_id"],
        })
        replaced.add(cand["old_uri"])
    return rewritten, need_review, unparseable, replaced


def _apply_replacements(text: str, mapping: dict[str, str], replaced: set[str]) -> str:
    """把已判定改写的旧地址字面量替换为新地址（只替换白名单内的 uri）。"""
    for old_uri in replaced:
        new_uri, _ = remap_scope_segment(old_uri, mapping)
        if new_uri:
            text = text.replace(old_uri, new_uri)
    return text


def _new_report(mode: str, dry_run: bool) -> dict[str, Any]:
    return {
        "mode": mode,
        "dry_run": dry_run,
        "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "db_name": DB_NAME,
        "tenant_ids": [],
        "stats": {
            "documents": 0,
            "changed": 0,
            "unchanged": 0,
            "archived": 0,
            "conflicts": 0,
            **{f"S{i}": 0 for i in range(1, 8)},
        },
        "addresses": {
            "rewritten": [],          # 已改写
            "need_manual_review": [],  # 需人工确认（对应设计文档「无法定位 / 已失效」）
            "unparseable": [],         # 无法解析
        },
        "failures": [],               # 失败清单：所有归档 / 冲突 / 无租户文档
        "warnings": [],
    }


def _write_report(report: dict[str, Any], path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    _log("REPORT", f"失败清单 / 三清单已写入 {path}")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


async def _scan_external_sources(
    db: Any,
    sources: Iterable[str],
    mapping: dict[str, str],
    rewrite_allowed: set[str],
    tenant_ids: list[str],
    report: dict[str, Any],
) -> None:
    """S6：盘点用户追加的持久化旧地址引用源（默认只读，不改写）。"""
    for spec in sources:
        if "." not in spec:
            report["warnings"].append(f"--address-source {spec!r} 缺少 .FIELD，已跳过")
            _log("WARN", f"--address-source {spec!r} 格式应为 COLLECTION.FIELD，已跳过")
            continue
        collection, field_name = spec.split(".", 1)
        allow = collection in rewrite_allowed and collection not in READONLY_COLLECTIONS
        if collection in READONLY_COLLECTIONS:
            _log("INFO", f"S6 盘点只读源 {spec}（T040：禁止写入，只登记清单）")
        for tid in tenant_ids:
            cursor = db[collection].find({"tenant_id": tid})
            async for doc in cursor:
                text, kind = _coerce_text(doc.get(field_name))
                if text is None:
                    continue
                candidates = find_address_candidates(text, mapping)
                if not candidates:
                    continue
                rew, review, unpars, replaced = await _classify_addresses(
                    db, tid, candidates, source_label=spec, allow_rewrite=allow
                )
                report["addresses"]["rewritten"].extend(rew)
                report["addresses"]["need_manual_review"].extend(review)
                report["addresses"]["unparseable"].extend(unpars)
                if allow and replaced:
                    _assert_writable(collection)  # 双保险
                    new_text = _restore_text(_apply_replacements(text, mapping, replaced), kind)
                    await db[collection].update_one(
                        {"_id": doc["_id"], "tenant_id": tid},
                        {"$set": {field_name: new_text}},
                    )
                    report["stats"]["changed"] += 1


async def _process_memories(
    db: Any,
    tenant_ids: list[str],
    mapping: dict[str, str],
    reverse: bool,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    """逐租户、逐文档执行 S1–S7，并把 S6(memories 文本字段) 合并进同一次写。"""
    for tid in tenant_ids:
        report["tenant_ids"].append(tid)
        cursor = db[COLLECTION_MEMORIES].find({"tenant_id": tid})
        async for doc in cursor:
            report["stats"]["documents"] += 1
            if reverse:
                ev = evaluate_reverse(doc)
            else:
                lookup = await _lookup_for(db, tid, doc)
                ev = evaluate_document(doc, lookup)

            # S6：memories 文本字段里的旧地址，允许改写（脚本唯一可写集合）。
            for text_field in MEMORY_TEXT_FIELDS:
                value = doc.get(text_field)
                text, kind = _coerce_text(value)
                if text is None:
                    continue
                candidates = find_address_candidates(text, mapping)
                if not candidates:
                    continue
                rew, review, unpars, replaced = await _classify_addresses(
                    db, tid, candidates,
                    source_label=f"{COLLECTION_MEMORIES}.{text_field}",
                    allow_rewrite=True,
                )
                report["addresses"]["rewritten"].extend(rew)
                report["addresses"]["need_manual_review"].extend(review)
                report["addresses"]["unparseable"].extend(unpars)
                if replaced:
                    ev.set_fields[text_field] = _restore_text(
                        _apply_replacements(text, mapping, replaced), kind
                    )

            for step in ev.steps:
                key = step.split("-")[0]  # S1-rev -> S1
                if key in report["stats"]:
                    report["stats"][key] += 1
            if ev.archive_reasons:
                report["stats"]["archived"] += 1
            if ev.conflicts:
                report["stats"]["conflicts"] += 1

            failure = {
                "tenant_id": tid,
                "memory_id": str(doc.get("memory_id") or doc.get("_id") or ""),
                "scope": str(doc.get("scope") or ""),
                "archive_reasons": ev.archive_reasons,
                "conflicts": ev.conflicts,
            }
            if ev.archive_reasons or ev.conflicts:
                report["failures"].append(failure)

            if ev.write_count() == 0:
                report["stats"]["unchanged"] += 1
                continue

            report["stats"]["changed"] += 1
            if not dry_run:
                _assert_writable(COLLECTION_MEMORIES)
                await db[COLLECTION_MEMORIES].update_one(
                    {"_id": doc["_id"], "tenant_id": tid}, ev.as_update()
                )

    # 缺 tenant_id 的历史行：无法带租户边界，fail-closed 归档（仅正向迁移）。
    if not reverse:
        cursor = db[COLLECTION_MEMORIES].find({
            "$or": [
                {"tenant_id": {"$exists": False}},
                {"tenant_id": None},
                {"tenant_id": ""},
            ]
        })
        async for doc in cursor:
            report["stats"]["documents"] += 1
            report["stats"]["archived"] += 1
            report["failures"].append({
                "tenant_id": None,
                "memory_id": str(doc.get("memory_id") or doc.get("_id") or ""),
                "scope": str(doc.get("scope") or ""),
                "archive_reasons": ["S7: 缺 tenant_id，无法带租户边界，fail-closed 归档"],
                "conflicts": [],
            })
            if doc.get("archived") is not True:
                report["stats"]["changed"] += 1
                if not dry_run:
                    _assert_writable(COLLECTION_MEMORIES)
                    await db[COLLECTION_MEMORIES].update_one(
                        {"_id": doc["_id"]}, {"$set": {"archived": True}}
                    )
            else:
                report["stats"]["unchanged"] += 1


async def run(args: argparse.Namespace) -> int:
    dry_run = not args.apply
    mode = "reverse" if args.reverse else "migrate"
    mapping = REVERSE_SCOPE_MAP if args.reverse else SCOPE_MAP
    report = _new_report(mode, dry_run)

    if args.reverse:
        report["warnings"].append(
            "--reverse 还原 S1/S2/S6 并删除 S3 的 project_owner_id；"
            "明确不撤销 S4/S7 写入的 archived 标记（避免重新放出已判定越权的记忆）。"
        )
        report["warnings"].append(
            "外部只读持久化引用（--address-source）从未由脚本自动改写，--reverse 对其不生效；"
            "若人工改写过请人工回退。"
        )
        report["warnings"].append(
            "--reverse 是 memories 整库逆映射，仅在成对回滚窗口、已冻结写入时执行。"
        )
        _log("WARN", "--reverse 不撤销 S4/S7 的 archived 标记；按失败清单人工决定")
        _log("WARN", "--reverse 仅还原 S1/S2/S6 并删除 project_owner_id；外部只读引用不自动还原")

    db = _get_db()
    tenant_ids = await _tenant_ids(db, args.tenant_id)
    _log("INFO", f"mode={mode} dry_run={dry_run} db={DB_NAME} tenants={len(tenant_ids)}")

    rewrite_allowed = {COLLECTION_MEMORIES, *args.address_allow_rewrite} - READONLY_COLLECTIONS
    await _process_memories(db, tenant_ids, mapping, args.reverse, dry_run, report)
    if args.address_source:
        await _scan_external_sources(
            db, args.address_source, mapping, rewrite_allowed, tenant_ids, report
        )

    stats = report["stats"]
    _log("OK", (
        f"documents={stats['documents']} changed={stats['changed']} "
        f"unchanged={stats['unchanged']} archived={stats['archived']} "
        f"conflicts={stats['conflicts']} "
        f"S1={stats['S1']} S2={stats['S2']} S3={stats['S3']} S4={stats['S4']} "
        f"S5={stats['S5']} S6={len(report['addresses']['rewritten'])} S7={stats['S7']}"
    ))
    addr = report["addresses"]
    _log("OK", (
        f"S6 三清单：已改写={len(addr['rewritten'])} "
        f"需人工确认={len(addr['need_manual_review'])} "
        f"无法解析={len(addr['unparseable'])}"
    ))
    _log("OK", f"失败清单条目={len(report['failures'])}")
    if dry_run:
        _log("DRY-RUN", "以上为预演统计，未写任何数据库文档；加 --apply 才落盘")

    _write_report(report, args.report)
    return 0


# --------------------------------------------------------------------------
# 纯函数自测（不连库、不写库）
# --------------------------------------------------------------------------


def _self_test() -> int:
    failures: list[str] = []

    def check(cond: bool, label: str) -> None:
        if not cond:
            failures.append(label)

    # S6 地址改写（正向 / 反向 / 无法解析 / 非目标段）
    check(
        remap_scope_segment("mogo://memory/workspace/u1/m1/L1", SCOPE_MAP)
        == ("mogo://memory/project/u1/m1/L1", "m1"),
        "S6 正向 workspace->project",
    )
    check(
        remap_scope_segment("mogo://memory/org/u1/m1", SCOPE_MAP)
        == ("mogo://memory/department/u1/m1", "m1"),
        "S6 正向 org->department（无 tier）",
    )
    check(
        remap_scope_segment("mogo://memory/project/u1/m1/L2", REVERSE_SCOPE_MAP)
        == ("mogo://memory/workspace/u1/m1/L2", "m1"),
        "S6 反向 project->workspace",
    )
    check(remap_scope_segment("mogo://memory/personal/u1/m1", SCOPE_MAP) == (None, None),
          "S6 非目标段不处理")
    check(remap_scope_segment("mogo://memory/workspace/u1", SCOPE_MAP) == (None, None),
          "S6 段数不足无法解析")
    cands = find_address_candidates(
        "see mogo://memory/workspace/u1/m1/L0 and mogo://memory/org/u2/m2/L2", SCOPE_MAP
    )
    check(len(cands) == 2 and all(c["parse_error"] is None for c in cands),
          "S6 文本候选提取")
    check(len(find_address_candidates("mogo://memory/workspace/u1", SCOPE_MAP)) == 1,
          "S6 无法解析候选仍被登记")

    # S1 / S2 / S3 成功路径
    doc = {"scope": "workspace", "workspace_id": "p1", "owner_id": "u1", "tenant_id": "t1"}
    ev = evaluate_document(doc, Lookup(tenant_id="t1", project_match_count=1,
                                       project_owner_id="u1"))
    check(ev.scope_set == "project", "S1 scope 值转换")
    check(ev.rename == {"workspace_id": "project_id"}, "S2 $rename")
    check(ev.set_fields.get("project_owner_id") == "u1", "S3 单行回填 project_owner_id")
    check("archived" not in ev.set_fields, "S3 成功不归档")
    upd = ev.as_update()
    check(upd.get("$set", {}).get("scope") == "project", "as_update 合并 $set")
    check("$rename" in upd, "as_update 合并 $rename")

    # S3 多行 / 零行 / S4 一律归档，且无猜测性归属
    multi = evaluate_document(dict(doc), Lookup(tenant_id="t1", project_match_count=2))
    check(multi.set_fields.get("archived") is True and "project_owner_id" not in multi.set_fields,
          "S3 命中多行归档且不猜归属")
    zero = evaluate_document(dict(doc), Lookup(tenant_id="t1", project_match_count=0))
    check(zero.set_fields.get("archived") is True and "project_owner_id" not in zero.set_fields,
          "S3 命中零行归档且不猜归属")
    default_doc = {"scope": "workspace", "workspace_id": "default", "tenant_id": "t1"}
    dflt = evaluate_document(default_doc, Lookup(tenant_id="t1", project_match_count=1,
                                                 project_owner_id="u1"))
    check(dflt.set_fields.get("archived") is True, "S4 default 归档")

    # S5 部门节点校验
    dept_doc = {"scope": "org", "org_id": "d1", "tenant_id": "t1"}
    bad = evaluate_document(dept_doc, Lookup(tenant_id="t1", org_unit_valid=False))
    check(bad.set_fields.get("archived") is True, "S5 部门节点无效归档")
    good = evaluate_document(dict(dept_doc), Lookup(tenant_id="t1", org_unit_valid=True))
    check("archived" not in good.set_fields, "S5 部门节点有效不归档")

    # S7 未知 scope / 缺归属 id
    unknown = evaluate_document({"scope": "legacy", "tenant_id": "t1"}, Lookup(tenant_id="t1"))
    check(unknown.set_fields.get("archived") is True, "S7 未知 scope 归档")
    missing = evaluate_document({"scope": "project", "tenant_id": "t1"}, Lookup(tenant_id="t1"))
    check(missing.set_fields.get("archived") is True, "S7 project 缺归属 id 归档")

    # S2 冲突不覆盖新字段
    conflict = evaluate_document(
        {"scope": "workspace", "workspace_id": "old", "project_id": "new", "tenant_id": "t1",
         "project_owner_id": "u1"},
        Lookup(tenant_id="t1"),
    )
    check(len(conflict.conflicts) == 1 and conflict.unset == {"workspace_id": ""}
          and "project_id" not in conflict.set_fields, "S2 并存冲突不覆盖新字段")

    # 可重入：已归档文档第二次不再写 archived
    again = evaluate_document(
        {"scope": "project", "project_id": "default", "archived": True, "tenant_id": "t1"},
        Lookup(tenant_id="t1"),
    )
    check("archived" not in again.set_fields and again.write_count() == 0,
          "可重入：已归档文档第二次 0 条变更")

    # --reverse 还原字段、删 project_owner_id、不碰 archived
    migrated = {"scope": "project", "project_id": "p1", "project_owner_id": "u1",
                "department_id": "d1", "archived": True, "tenant_id": "t1"}
    rev = evaluate_reverse(migrated)
    check(rev.scope_set == "workspace", "reverse 还原 S1")
    check(rev.rename.get("project_id") == "workspace_id", "reverse 还原 S2")
    check(rev.unset.get("project_owner_id") == "", "reverse 删除 project_owner_id")
    check("archived" not in rev.set_fields and "archived" not in rev.unset,
          "reverse 不撤销 archived")

    # T040 只读白名单
    check(READONLY_COLLECTIONS == frozenset(
        {"projects", "org_units", "end_user_org_relations", "chat_sessions"}
    ), "T040 只读集合白名单")
    try:
        _assert_writable("projects")
        check(False, "_assert_writable 应拦截 projects")
    except RuntimeError:
        check(True, "_assert_writable 拦截 projects")
    check(_default_report_path("migrate").endswith(".json"), "默认报告路径")

    if failures:
        for item in failures:
            _log("ERROR", f"self-test FAILED: {item}")
        return 1
    _log("OK", "self-test passed（纯函数，未连接数据库、未写入任何数据）")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    readonly = " / ".join(sorted(READONLY_COLLECTIONS))
    parser = argparse.ArgumentParser(
        description="017 D4 一次性切换：memories 范围模型迁移（T039 / T040）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "T040 写入边界（硬性）：\n"
            f"  只读、禁止写入：{readonly}\n"
            f"  默认只写入：{COLLECTION_MEMORIES}（S1–S7 与 S6 文本字段改写）\n"
            "  --address-source 追加的其它引用源默认只盘点不改写；\n"
            "  --address-allow-rewrite 可显式授权写其它集合，只读白名单仍永不可写。\n"
            "\n"
            "--reverse 边界：\n"
            "  还原 S1/S2/S6 并删除 S3 补的 project_owner_id；\n"
            "  明确不撤销 S4/S7 写入的 archived 标记（成对回滚 SOP）。\n"
            "\n"
            "顺序：先 dry-run 核对统计与失败清单 → 冻结写入 → --apply → 发布新代码/解冻。\n"
            "回滚：先回退代码 + 立刻执行 --reverse --apply（两者必须成对执行）。\n"
        ),
    )
    parser.add_argument("--apply", action="store_true",
                        help="实际落盘；缺省为 dry-run（只打印统计与失败清单，不写库）")
    parser.add_argument("--reverse", action="store_true",
                        help="反向回退：还原 S1/S2/S6 + 删 project_owner_id；不撤销 archived")
    parser.add_argument("--tenant-id", type=str, default=None,
                        help="只处理指定租户；缺省逐租户全量（所有查询仍带 tenant_id 边界）")
    parser.add_argument("--report", type=str, default=None,
                        help="JSON 失败清单 / 三清单路径；默认 "
                             "services/chat-api/backups/017-scope-cutover-<mode>-<ts>.json")
    parser.add_argument("--address-source", action="append", default=[], metavar="COLLECTION.FIELD",
                        help="追加 S6 旧地址盘点源（顶层字段，可重复）；默认只读登记，不改写")
    parser.add_argument("--address-allow-rewrite", action="append", default=[], metavar="COLLECTION",
                        help="允许自动改写该集合内旧地址（只读白名单仍强制拒绝；默认仅 memories）")
    parser.add_argument("--self-test", action="store_true",
                        help="运行不连库的纯函数自测并退出")
    return parser


async def _main() -> int:
    args = _build_parser().parse_args()
    if args.self_test:
        return _self_test()
    if args.report is None:
        args.report = _default_report_path("reverse" if args.reverse else "migrate")
    return await run(args)


def main() -> int:
    try:
        return asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001 — 与 046 同款：顶层兜底打印，不吞异常
        _log("ERROR", f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
