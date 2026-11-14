"""Runtime for the ``customer_feedback_triage`` case (single-agent batch triage).

This module implements the eight step contracts declared in
``app/skills_specs/customer_feedback_triage/SKILL.md`` as ordinary callables so
the pipeline is testable without an LLM or network access. The LLM-shaped parts
(summary prose, report composition) go through the injectable ``TriageNarrator``
protocol; tests supply a fake.

See ``docs/cases/single-agent-customer-feedback-triage.md`` for the scenario and
its acceptance criteria, and ``validation.yaml`` for the criterion-to-test map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import csv
import hashlib
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Protocol, Sequence

from app.skills_specs.customer_feedback_triage.scripts.severity_heuristics import (
    P0,
    P1,
    P2,
    P3,
    SEVERITY_ORDER,
    HeuristicConfig,
    classify_severity,
    rank_score,
    sentiment_score,
)

_UTC8 = timezone(timedelta(hours=8))

P0_APPROVAL_THRESHOLD = 3
ACTION_ITEM_LIMIT = 20
REQUIRED_SECTIONS = (
    "Executive Summary",
    "P0 P1 Items",
    "Trend Analysis",
    "Recommended Actions",
)
REQUIRED_FIELDS = (
    "来源批次",
    "分类时间",
    "条目总数",
)


# --------------------------------------------------------------------------
# Injectable boundaries
# --------------------------------------------------------------------------


class TriageNarrator(Protocol):
    """LLM-shaped narration boundary; a fake is used in tests."""

    def executive_summary(
        self,
        *,
        total_items: int,
        counts: Mapping[str, int],
        top_categories: Sequence[tuple[str, int]],
    ) -> str: ...

    def trend_analysis(
        self,
        *,
        counts: Mapping[str, int],
        category_deltas: Sequence[tuple[str, int, int]],
    ) -> str: ...


class PiiRedactor(Protocol):
    """PII redaction boundary, aligned with admin-api ``governance/pii.py``."""

    def redact(self, text: str) -> tuple[str, dict[str, str]]: ...


class ApprovalSink(Protocol):
    """Approval-event boundary (R1 grading) for the P0 threshold rule."""

    def emit(self, event: Mapping[str, Any]) -> str: ...


class AuditSink(Protocol):
    """Audit boundary (001 gatekeeper)."""

    def record(self, event: Mapping[str, Any]) -> None: ...


class TokenUsageSink(Protocol):
    """Cost-metering boundary feeding the 008 ops dashboard."""

    def record_usage(self, event: Mapping[str, Any]) -> None: ...


# --------------------------------------------------------------------------
# Local PII redaction (kept in-service on purpose; see AGENTS.md boundaries)
# --------------------------------------------------------------------------

_ID_CARD = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_BANK_CARD = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


@dataclass
class DefaultPiiRedactor:
    """Deterministic redactor implementing mask/remove/hash/abstract.

    The strategy table mirrors ``services/admin-api/app/governance/pii.py`` so a
    deployment that wires the real governance service just swaps this object out.
    """

    strategies: Mapping[str, str] = field(
        default_factory=lambda: {
            "private_key": "remove",
            "id_card": "hash",
            "bank_card": "mask",
            "phone": "mask",
            "email": "abstract",
        }
    )

    def redact(self, text: str) -> tuple[str, dict[str, str]]:
        """Return ``(redacted_text, placeholder_map)``.

        The placeholder map is reversible within the session but never written to
        disk by this module.
        """
        placeholders: dict[str, str] = {}
        counter = {"n": 0}

        def replace(match: re.Match[str], pii_type: str) -> str:
            value = match.group(0)
            strategy = self.strategies.get(pii_type, "mask")
            rendered = self._apply(value, pii_type, strategy)
            counter["n"] += 1
            token = f"[{pii_type.upper()}_{counter['n']}]"
            placeholders[token] = value
            return token if strategy == "remove" else f"{token}{rendered}"

        result = text
        result = _PRIVATE_KEY.sub(lambda m: replace(m, "private_key"), result)
        result = _ID_CARD.sub(lambda m: replace(m, "id_card"), result)
        result = _BANK_CARD.sub(lambda m: replace(m, "bank_card"), result)
        result = _PHONE.sub(lambda m: replace(m, "phone"), result)
        result = _EMAIL.sub(lambda m: replace(m, "email"), result)
        return result, placeholders

    @staticmethod
    def _apply(value: str, pii_type: str, strategy: str) -> str:
        if strategy == "remove":
            return ""
        if strategy == "hash":
            return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        if strategy == "abstract":
            if pii_type == "email":
                return "[EMAIL]"
            return f"[{pii_type.upper()}]"
        # mask: keep a short readable tail.
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 4:
            return f"***{digits[-4:]}"
        return "***"


# --------------------------------------------------------------------------
# Step 1 — load_feedback
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackItem:
    id: str
    source_channel: str
    timestamp: str | None
    subject: str
    body: str
    user_id: str | None = None
    attachments: tuple[str, ...] = ()
    affected_users: int = 1

    @property
    def text(self) -> str:
        return f"{self.subject} {self.body}".strip()


def load_feedback(
    source: str | Sequence[Mapping[str, Any]] | None = None,
    *,
    pasted_text: str | None = None,
    source_channel: str = "unknown",
    reader: "SpreadsheetReader | None" = None,
) -> list[FeedbackItem]:
    """Load raw feedback from a table path, records, or pasted text.

    Excel/CSV reading is delegated to an injectable ``reader`` so the pipeline
    stays free of heavyweight parsers in tests. A list of mappings (or pasted
    text) is handled directly.
    """
    if pasted_text is not None:
        return _items_from_text(pasted_text, source_channel=source_channel)

    if isinstance(source, str):
        if reader is None:
            raise ValueError(
                "load_feedback needs a reader for file sources (inject a SpreadsheetReader)"
            )
        records = reader.read_table(source)
        return _items_from_records(records, source_channel=source_channel)

    if source is None:
        return []

    return _items_from_records(list(source), source_channel=source_channel)


class SpreadsheetReader(Protocol):
    def read_table(self, path: str) -> list[Mapping[str, Any]]: ...


def _items_from_records(
    records: Sequence[Mapping[str, Any]],
    *,
    source_channel: str,
) -> list[FeedbackItem]:
    items: list[FeedbackItem] = []
    for index, record in enumerate(records):
        row = dict(record)
        body = _first_text(row, ("body", "content", "feedback", "text", "描述", "反馈内容"))
        subject = _first_text(row, ("subject", "title", "标题", "主题"))
        if not body and not subject:
            continue
        raw_id = _first_text(row, ("id", "item_id", "编号"))
        items.append(
            FeedbackItem(
                id=str(raw_id or f"item-{index + 1}"),
                source_channel=str(
                    _first_text(row, ("source_channel", "channel", "来源")) or source_channel
                ),
                timestamp=_first_text(row, ("timestamp", "created_at", "time", "时间")),
                subject=subject,
                body=body,
                user_id=_first_text(row, ("user_id", "用户", "uid")) or None,
                affected_users=_to_int(
                    _first_text(row, ("affected_users", "影响人数")), default=1
                ),
            )
        )
    return items


def _items_from_text(text: str, *, source_channel: str) -> list[FeedbackItem]:
    """Split pasted text into one item per non-empty line."""
    items: list[FeedbackItem] = []
    for index, line in enumerate(str(text).splitlines()):
        value = line.strip().lstrip("-*•").strip()
        if not value:
            continue
        items.append(
            FeedbackItem(
                id=f"pasted-{index + 1}",
                source_channel=source_channel,
                timestamp=None,
                subject="",
                body=value,
            )
        )
    return items


def _first_text(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _to_int(value: Any, *, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Step 2 — normalize_batch
# --------------------------------------------------------------------------


def normalize_batch(items: Sequence[FeedbackItem]) -> list[FeedbackItem]:
    """Drop empties, de-duplicate by body hash, and normalise timestamps to UTC+8."""
    seen: set[str] = set()
    normalized: list[FeedbackItem] = []
    for item in items:
        if not item.text.strip():
            continue
        digest = hashlib.sha256(item.text.strip().encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        normalized.append(
            FeedbackItem(
                id=item.id,
                source_channel=item.source_channel,
                timestamp=_normalize_timestamp(item.timestamp),
                subject=item.subject,
                body=item.body,
                user_id=item.user_id,
                attachments=item.attachments,
                affected_users=item.affected_users,
            )
        )
    return normalized


def _normalize_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for parser in (
        lambda item: datetime.fromisoformat(item),
        lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
        lambda item: datetime.strptime(item, "%Y/%m/%d %H:%M"),
        lambda item: datetime.strptime(item, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(text)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_UTC8)
        return parsed.astimezone(_UTC8).isoformat()
    return None


# --------------------------------------------------------------------------
# Steps 3 & 4 — classify_severity / categorize_issue
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifiedItem:
    item: FeedbackItem
    severity: str
    category: str
    score: float
    sentiment: float
    reasons: tuple[str, ...] = ()


def classify_and_categorize(
    items: Sequence[FeedbackItem],
    *,
    config: HeuristicConfig | None = None,
) -> list[ClassifiedItem]:
    """Run ``classify_severity`` + ``categorize_issue`` over the batch."""
    cfg = config or HeuristicConfig()
    classified: list[ClassifiedItem] = []
    for item in items:
        assessment = classify_severity(
            item.text,
            config=cfg,
            timestamp=item.timestamp,
            affected_users=item.affected_users,
        )
        classified.append(
            ClassifiedItem(
                item=item,
                severity=assessment.severity,
                category=assessment.category,
                score=assessment.score,
                sentiment=sentiment_score(item.text, cfg),
                reasons=assessment.reasons,
            )
        )
    return classified


def severity_counts(classified: Sequence[ClassifiedItem]) -> dict[str, int]:
    counts = {level: 0 for level in SEVERITY_ORDER}
    for entry in classified:
        counts[entry.severity] = counts.get(entry.severity, 0) + 1
    return counts


def category_counts(classified: Sequence[ClassifiedItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in classified:
        counts[entry.category] = counts.get(entry.category, 0) + 1
    return counts


# --------------------------------------------------------------------------
# Step 5 — detect_pii_and_redact
# --------------------------------------------------------------------------


@dataclass
class RedactionOutcome:
    classified: list[ClassifiedItem]
    placeholders: dict[str, str] = field(default_factory=dict)


def detect_pii_and_redact(
    classified: Sequence[ClassifiedItem],
    *,
    redactor: PiiRedactor | None = None,
) -> RedactionOutcome:
    """Redact PII from every item's text; the raw text never enters the report."""
    engine = redactor or DefaultPiiRedactor()
    redacted: list[ClassifiedItem] = []
    placeholders: dict[str, str] = {}
    for entry in classified:
        redacted_text, mapping = engine.redact(entry.item.text)
        placeholders.update(mapping)
        redacted.append(
            ClassifiedItem(
                item=FeedbackItem(
                    id=entry.item.id,
                    source_channel=entry.item.source_channel,
                    timestamp=entry.item.timestamp,
                    subject="",
                    body=redacted_text,
                    user_id=None,
                    attachments=entry.item.attachments,
                    affected_users=entry.item.affected_users,
                ),
                severity=entry.severity,
                category=entry.category,
                score=entry.score,
                sentiment=entry.sentiment,
                reasons=entry.reasons,
            )
        )
    return RedactionOutcome(classified=redacted, placeholders=placeholders)


# --------------------------------------------------------------------------
# Step 6 — rank_action_items
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionItem:
    rank: int
    item_id: str
    severity: str
    category: str
    reported_at: str | None
    summary: str
    suggested_action: str
    owner: str
    source_channel: str
    score: float


_ACTION_BY_CATEGORY: Mapping[str, str] = {
    "登录账号": "联系值班 SRE 核查登录链路",
    "数据同步": "检查同步任务与数据一致性",
    "性能": "排查接口与慢查询",
    "计费": "核对账单与支付流水",
    "集成": "核对接口契约与 webhook 投递",
    "内容": "复核内容生成与导出链路",
    "权限": "审计角色与可见范围配置",
}

_DEFAULT_OWNER = "值班组"


def rank_action_items(
    classified: Sequence[ClassifiedItem],
    *,
    limit: int = ACTION_ITEM_LIMIT,
    now_epoch: float | None = None,
) -> list[ActionItem]:
    """Rank P0+P1 items by (urgency × impact × sentiment), take the top ``limit``."""
    candidates = [e for e in classified if e.severity in (P0, P1)]
    scored: list[tuple[float, ClassifiedItem]] = []
    for entry in candidates:
        value = rank_score(
            severity=entry.severity,
            timestamp=entry.item.timestamp,
            affected_users=entry.item.affected_users,
            sentiment=entry.sentiment,
            now_epoch=now_epoch,
        )
        scored.append((value, entry))

    # Stable ordering: score desc, then item id for determinism.
    scored.sort(key=lambda pair: (-pair[0], pair[1].item.id))

    items: list[ActionItem] = []
    for index, (value, entry) in enumerate(scored[: max(0, limit)], start=1):
        items.append(
            ActionItem(
                rank=index,
                item_id=entry.item.id,
                severity=entry.severity,
                category=entry.category,
                reported_at=entry.item.timestamp,
                summary=_truncate(entry.item.body, 120),
                suggested_action=_ACTION_BY_CATEGORY.get(entry.category, "人工核查并跟进"),
                owner=_DEFAULT_OWNER,
                source_channel=entry.item.source_channel,
                score=value,
            )
        )
    return items


def _truncate(text: str, limit: int) -> str:
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


# --------------------------------------------------------------------------
# Step 7 — compose_report
# --------------------------------------------------------------------------


@dataclass
class TriageReport:
    batch_id: str
    classified_at: str
    total_items: int
    counts: Mapping[str, int]
    action_items: Sequence[ActionItem]
    markdown: str
    action_items_csv: str


class _DefaultNarrator:
    """Deterministic fallback narrator used when no LLM narrator is injected."""

    def executive_summary(
        self,
        *,
        total_items: int,
        counts: Mapping[str, int],
        top_categories: Sequence[tuple[str, int]],
    ) -> str:
        top = "、".join(f"{name}（{count} 条）" for name, count in top_categories[:2]) or "无"
        return (
            f"本批共 {total_items} 条反馈，识别出 {counts.get(P0, 0)} 条 P0、"
            f"{counts.get(P1, 0)} 条 P1、{counts.get(P2, 0)} 条 P2、"
            f"{counts.get(P3, 0)} 条 P3。主要集中在：{top}。"
            f"建议优先处理 P0 项，并按类别分派责任人。"
        )

    def trend_analysis(
        self,
        *,
        counts: Mapping[str, int],
        category_deltas: Sequence[tuple[str, int, int]],
    ) -> str:
        lines = ["- 本批类别分布环比："]
        for name, current, previous in category_deltas:
            if previous:
                pct = (current - previous) / previous * 100.0
                lines.append(f"  - {name}：{previous} → {current}（{pct:+.0f}%）")
            else:
                lines.append(f"  - {name}：{previous} → {current}（新增）")
        p0 = counts.get(P0, 0)
        lines.append(f"- P0 合计 {p0} 条。")
        return "\n".join(lines)


def compose_report(
    *,
    batch_id: str,
    total_items: int,
    counts: Mapping[str, int],
    action_items: Sequence[ActionItem],
    category_deltas: Sequence[tuple[str, int, int]] = (),
    narrator: TriageNarrator | None = None,
    classified_at: str | None = None,
) -> TriageReport:
    """Render ``triage_report.md`` + ``action_items.csv`` per the templates."""
    voice = narrator or _DefaultNarrator()
    stamp = classified_at or datetime.now(tz=_UTC8).isoformat()
    top_categories = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    # Category breakdown comes from the action items' categories when available.
    category_breakdown = _category_breakdown(action_items)

    summary = voice.executive_summary(
        total_items=total_items,
        counts=counts,
        top_categories=category_breakdown or top_categories,
    )
    trend = voice.trend_analysis(counts=counts, category_deltas=category_deltas)

    immediate = [a for a in action_items if a.severity == P0][:5]
    weekly = [a for a in action_items if a.severity == P1][:5]

    lines = [
        f"# 客户反馈分诊报告 · {stamp[:10]}",
        "",
        f"> 来源批次：`{batch_id}`",
        f"> 分类时间：{stamp}（UTC+8）",
        f"> 条目总数：{total_items} ｜ P0：{counts.get(P0, 0)} ｜ P1：{counts.get(P1, 0)} "
        f"｜ P2：{counts.get(P2, 0)} ｜ P3：{counts.get(P3, 0)}",
        "",
        "## Executive Summary",
        "",
        summary,
        "",
        "## P0 / P1 Items",
        "",
        "| # | 严重度 | 类别 | 时间 | 摘要（已脱敏） | 建议动作 |",
        "|---|--------|------|------|----------------|----------|",
    ]
    for action in action_items:
        lines.append(
            f"| {action.rank} | {action.severity} | {action.category} | "
            f"{action.reported_at or '—'} | {action.summary} | {action.suggested_action} |"
        )
    if not action_items:
        lines.append("| — | — | — | — | 本批无 P0/P1 项 | — |")

    lines.extend(["", "## Trend Analysis", "", trend, "", "## Recommended Actions", "", "### 立即响应", ""])
    lines.extend([f"- {a.summary} → {a.suggested_action}" for a in immediate] or ["- 无需立即响应"])
    lines.extend(["", "### 周度跟进", ""])
    lines.extend([f"- {a.summary} → {a.suggested_action}" for a in weekly] or ["- 无"])

    markdown = "\n".join(lines) + "\n"
    return TriageReport(
        batch_id=batch_id,
        classified_at=stamp,
        total_items=total_items,
        counts=dict(counts),
        action_items=list(action_items),
        markdown=markdown,
        action_items_csv=render_action_items_csv(action_items),
    )


def _category_breakdown(action_items: Sequence[ActionItem]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for action in action_items:
        counts[action.category] = counts.get(action.category, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def render_action_items_csv(action_items: Sequence[ActionItem]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "item_id",
            "severity",
            "category",
            "reported_at",
            "summary_redacted",
            "suggested_action",
            "owner",
            "source_channel",
        ]
    )
    for action in action_items:
        writer.writerow(
            [
                action.item_id,
                action.severity,
                action.category,
                action.reported_at or "",
                action.summary,
                action.suggested_action,
                action.owner,
                action.source_channel,
            ]
        )
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Step 8 — trigger_approval_if_p0
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalOutcome:
    triggered: bool
    reason: str
    event: Mapping[str, Any] | None = None
    event_id: str | None = None


def trigger_approval_if_p0(
    *,
    counts: Mapping[str, int],
    batch_id: str,
    sink: ApprovalSink | None = None,
    threshold: int = P0_APPROVAL_THRESHOLD,
    assignee: str | None = None,
) -> ApprovalOutcome:
    """Emit an R1 approval event when the batch contains >= ``threshold`` P0 items.

    This mirrors the case's ``skip_condition`` semantics: below the threshold the
    step is skipped rather than emitting a no-op approval.
    """
    p0_count = int(counts.get(P0, 0))
    if p0_count < threshold:
        return ApprovalOutcome(
            triggered=False,
            reason=f"p0_count={p0_count} < threshold={threshold}",
        )

    event = {
        "type": "approval_request",
        "risk_level": "R1",
        "batch_id": batch_id,
        "p0_count": p0_count,
        "assignee": assignee or "P0 值班组",
        "reason": f"本批包含 {p0_count} 条 P0 反馈，需要立即响应审批",
    }
    event_id = sink.emit(event) if sink is not None else None
    return ApprovalOutcome(triggered=True, reason=event["reason"], event=event, event_id=event_id)


# --------------------------------------------------------------------------
# End-to-end orchestration of the eight steps
# --------------------------------------------------------------------------


@dataclass
class TriageResult:
    report: TriageReport
    approval: ApprovalOutcome
    counts: Mapping[str, int]
    audit_events: list[Mapping[str, Any]] = field(default_factory=list)


def run_triage(
    *,
    batch_id: str,
    source: str | Sequence[Mapping[str, Any]] | None = None,
    pasted_text: str | None = None,
    source_channel: str = "unknown",
    tenant_context: Mapping[str, Any] | None = None,
    reader: SpreadsheetReader | None = None,
    redactor: PiiRedactor | None = None,
    narrator: TriageNarrator | None = None,
    approval_sink: ApprovalSink | None = None,
    audit_sink: AuditSink | None = None,
    token_usage_sink: TokenUsageSink | None = None,
    now_epoch: float | None = None,
) -> TriageResult:
    """Execute steps 1–8 and return the report plus side-channel events."""
    audit_events: list[Mapping[str, Any]] = []

    def audit(event: Mapping[str, Any]) -> None:
        audit_events.append(dict(event))
        if audit_sink is not None:
            audit_sink.record(event)

    audit({"step": "load_feedback", "batch_id": batch_id})
    raw = load_feedback(
        source, pasted_text=pasted_text, source_channel=source_channel, reader=reader
    )

    audit({"step": "normalize_batch", "batch_id": batch_id, "count": len(raw)})
    normalized = normalize_batch(raw)

    config = HeuristicConfig.from_tenant_context(tenant_context)
    audit({"step": "classify_severity", "batch_id": batch_id})
    classified = classify_and_categorize(normalized, config=config)
    counts = severity_counts(classified)

    audit({"step": "categorize_issue", "batch_id": batch_id, "categories": category_counts(classified)})

    audit({"step": "detect_pii_and_redact", "batch_id": batch_id})
    outcome = detect_pii_and_redact(classified, redactor=redactor)

    audit({"step": "rank_action_items", "batch_id": batch_id})
    actions = rank_action_items(outcome.classified, now_epoch=now_epoch)

    audit({"step": "compose_report", "batch_id": batch_id})
    report = compose_report(
        batch_id=batch_id,
        total_items=len(normalized),
        counts=counts,
        action_items=actions,
        narrator=narrator,
    )

    audit({"step": "trigger_approval_if_p0", "batch_id": batch_id, "p0_count": counts.get(P0, 0)})
    approval = trigger_approval_if_p0(
        counts=counts, batch_id=batch_id, sink=approval_sink
    )

    if token_usage_sink is not None:
        token_usage_sink.record_usage(
            {
                "batch_id": batch_id,
                "skill": "customer_feedback_triage",
                "item_count": len(normalized),
                "node_id": "customer_feedback_triage",
            }
        )

    return TriageResult(
        report=report,
        approval=approval,
        counts=counts,
        audit_events=audit_events,
    )
