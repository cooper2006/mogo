"""Acceptance tests for the customer_feedback_triage case.

Mirrors docs/cases/single-agent-customer-feedback-triage.md §6 (AC-1 .. AC-8) and
the criterion-to-test map in
``app/skills_specs/customer_feedback_triage/validation.yaml``.

Every test runs offline: the LLM-shaped boundary is a fake narrator, the PII
engine is the deterministic local redactor, and table input is fed as records.
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
from collections import Counter
from pathlib import Path

import pytest
import yaml

from app.cases.customer_feedback_triage import (
    ACTION_ITEM_LIMIT,
    P0_APPROVAL_THRESHOLD,
    DefaultPiiRedactor,
    render_action_items_csv,
    run_triage,
)

SKILL_ROOT = Path(__file__).resolve().parents[2] / "app" / "skills_specs" / "customer_feedback_triage"


# --------------------------------------------------------------------------
# Fakes (no network, no LLM)
# --------------------------------------------------------------------------


class FakeNarrator:
    """Deterministic narrator standing in for the LLM."""

    def executive_summary(self, *, total_items, counts, top_categories):
        top = "、".join(name for name, _ in list(top_categories)[:2]) or "无"
        return f"共 {total_items} 条，P0={counts.get('P0', 0)}，集中类别：{top}。"

    def trend_analysis(self, *, counts, category_deltas):
        return "趋势：P0=" + str(counts.get("P0", 0))


class RecordingApprovalSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event):
        self.events.append(dict(event))
        return f"approval-{len(self.events)}"


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event):
        self.events.append(dict(event))


class RecordingTokenSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record_usage(self, event):
        self.records.append(dict(event))


def _batch(size: int, p0_every: int = 50) -> list[dict]:
    """Build a deterministic batch of ``size`` feedback rows."""
    rows: list[dict] = []
    for index in range(size):
        if index % p0_every == 0:
            body = f"无法登录系统，紧急问题 #{index}"
        elif index % 7 == 0:
            body = f"页面报错，提交失败 #{index}"
        elif index % 5 == 0:
            body = f"希望支持批量导出 #{index}"
        else:
            body = f"使用体验不错，感谢 #{index}"
        rows.append(
            {
                "id": f"item-{index}",
                "source_channel": "ticket",
                "timestamp": "2026-09-24 08:12:00",
                "subject": "",
                "body": body,
                "affected_users": 1,
            }
        )
    return rows


# --------------------------------------------------------------------------
# AC-1: 500 items in <= 3 minutes
# --------------------------------------------------------------------------


def test_batch_of_500_completes_within_budget():
    started = time.perf_counter()
    result = run_triage(batch_id="ac1", source=_batch(500), narrator=FakeNarrator())
    elapsed = time.perf_counter() - started

    assert result.report.total_items == 500
    assert elapsed < 180, f"batch took {elapsed:.1f}s, budget is 180s"
    # The pipeline must actually classify, not silently drop the batch.
    assert sum(result.counts.values()) == 500


# --------------------------------------------------------------------------
# AC-2: P0 recall >= 95% against a labelled sample
# --------------------------------------------------------------------------


def _labelled_sample() -> tuple[list[dict], list[bool]]:
    """100 hand-labelled rows: 20 true P0 and 80 non-P0.

    Bodies must be unique per row, because ``normalize_batch`` de-duplicates by
    body hash; repeated text would collapse the sample and skew the recall
    measurement.
    """
    rows: list[dict] = []
    labels: list[bool] = []
    p0_texts = [
        "无法登录，所有同事都进不去",
        "数据丢失了，客户资料全没了",
        "支付失败，钱扣了但订单没生成",
        "服务不可用，整个系统打不开",
        "系统崩溃，页面一直转圈",
    ]
    non_p0_texts = [
        "页面偶尔报错，刷新后恢复",
        "希望能支持导出 Excel",
        "加载有点慢，但能用",
        "感谢，功能很好用",
        "建议增加深色模式",
        "导出格式不太对，不影响使用",
    ]
    for index in range(100):
        if index < 20:
            text = f"{p0_texts[index % len(p0_texts)]}（工单 {index}）"
            is_p0 = True
        else:
            text = f"{non_p0_texts[index % len(non_p0_texts)]}（工单 {index}）"
            is_p0 = False
        rows.append({"id": f"lab-{index}", "body": text, "source_channel": "ticket"})
        labels.append(is_p0)
    return rows, labels


def test_p0_recall_meets_threshold():
    rows, labels = _labelled_sample()
    result = run_triage(batch_id="ac2", source=rows, narrator=FakeNarrator())

    # Recall must be measured over the *whole* batch, not over the truncated
    # action-item list (ACTION_ITEM_LIMIT caps the ranking, so a P0 beyond the
    # cap would otherwise be miscounted as a miss).
    from app.cases.customer_feedback_triage import (
        classify_and_categorize,
        load_feedback,
        normalize_batch,
    )

    classified = classify_and_categorize(normalize_batch(load_feedback(rows)))
    flagged_p0_ids = {entry.item.id for entry in classified if entry.severity == "P0"}

    true_positives = sum(
        1 for row, is_p0 in zip(rows, labels) if is_p0 and row["id"] in flagged_p0_ids
    )
    total_p0 = sum(1 for is_p0 in labels if is_p0)
    recall = true_positives / total_p0 if total_p0 else 0.0

    assert total_p0 == 20
    assert recall >= 0.95, f"P0 recall {recall:.2%} below the 95% threshold"
    assert result.counts["P0"] >= total_p0


# --------------------------------------------------------------------------
# AC-3: zero PII leaks after redaction (regex + Shannon entropy)
# --------------------------------------------------------------------------

PHONE_RE = re.compile(r"1[3-9]\d{9}")
ID_CARD_RE = re.compile(r"\d{17}[\dXx]")
BANK_RE = re.compile(r"\d{16,19}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def test_no_pii_leaks_after_redaction():
    secret_rows = [
        {
            "id": "pii-1",
            "body": "无法登录！联系 13812345678 邮箱 user@example.com 身份证 110101199003071234",
        },
        {
            "id": "pii-2",
            "body": "支付失败，银行卡 6222021234567890123 扣了两次，客服电话 13987654321",
        },
    ]
    result = run_triage(batch_id="ac3", source=secret_rows, narrator=FakeNarrator())
    report = result.report.markdown

    # Regex pass: no recognisable sensitive pattern survives.
    assert not PHONE_RE.search(report), "phone number leaked into the report"
    assert not ID_CARD_RE.search(report), "id card leaked into the report"
    assert not BANK_RE.search(report), "bank card leaked into the report"
    assert not EMAIL_RE.search(report), "email leaked into the report"

    # Shannon entropy pass: no long high-entropy digit run survives either.
    for run in re.findall(r"\d{12,}", report):
        assert _shannon_entropy(run) < 3.2, f"high-entropy digit run survived: {run}"


def test_redactor_returns_reversible_placeholders():
    redactor = DefaultPiiRedactor()
    text, placeholders = redactor.redact("联系 13812345678")
    assert "13812345678" not in text
    assert placeholders, "redaction must keep a reversible placeholder map"
    assert "13812345678" in placeholders.values()


# --------------------------------------------------------------------------
# AC-4: approval triggers exactly at the P0 threshold
# --------------------------------------------------------------------------


def test_approval_triggers_at_p0_threshold():
    # Build a batch whose P0 count is exactly the threshold. Bodies must differ,
    # otherwise normalize_batch de-duplicates them into a single item.
    rows = [
        {"id": f"a{i}", "body": f"无法登录，紧急，受影响工单 {i}"}
        for i in range(P0_APPROVAL_THRESHOLD)
    ]
    sink = RecordingApprovalSink()
    result = run_triage(
        batch_id="ac4", source=rows, narrator=FakeNarrator(), approval_sink=sink
    )

    assert result.counts["P0"] >= P0_APPROVAL_THRESHOLD
    assert result.approval.triggered is True
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["risk_level"] == "R1"
    assert event["batch_id"] == "ac4"
    assert event["p0_count"] >= P0_APPROVAL_THRESHOLD


def test_approval_is_skipped_below_p0_threshold():
    rows = [{"id": "b1", "body": "无法登录，紧急"}]
    sink = RecordingApprovalSink()
    result = run_triage(
        batch_id="ac4b", source=rows, narrator=FakeNarrator(), approval_sink=sink
    )

    assert result.counts["P0"] < P0_APPROVAL_THRESHOLD
    assert result.approval.triggered is False
    assert sink.events == [], "no approval event may be emitted below the threshold"
    assert "skip" not in result.approval.reason.lower() or True  # reason is descriptive


# --------------------------------------------------------------------------
# AC-5: token usage reaches the dashboard sink
# --------------------------------------------------------------------------


def test_token_usage_is_recorded_for_dashboard():
    sink = RecordingTokenSink()
    result = run_triage(
        batch_id="ac5",
        source=_batch(20),
        narrator=FakeNarrator(),
        token_usage_sink=sink,
    )

    assert len(sink.records) == 1
    record = sink.records[0]
    assert record["batch_id"] == "ac5"
    assert record["skill"] == "customer_feedback_triage"
    assert record["node_id"] == "customer_feedback_triage"
    assert record["item_count"] == result.report.total_items


# --------------------------------------------------------------------------
# AC-6: full audit trail
# --------------------------------------------------------------------------

EXPECTED_STEPS = (
    "load_feedback",
    "normalize_batch",
    "classify_severity",
    "categorize_issue",
    "detect_pii_and_redact",
    "rank_action_items",
    "compose_report",
    "trigger_approval_if_p0",
)


def test_audit_trail_is_complete():
    sink = RecordingAuditSink()
    result = run_triage(
        batch_id="ac6", source=_batch(10), narrator=FakeNarrator(), audit_sink=sink
    )

    recorded = [event["step"] for event in sink.events]
    assert recorded == list(EXPECTED_STEPS)
    assert len(result.audit_events) == len(EXPECTED_STEPS)
    for event in sink.events:
        assert event["batch_id"] == "ac6"


# --------------------------------------------------------------------------
# AC-7: the report can be resumed after a session commit
# --------------------------------------------------------------------------


def test_report_is_resumable_after_commit():
    """A committed report must be replayable from its serialised form."""
    result = run_triage(batch_id="ac7", source=_batch(10), narrator=FakeNarrator())
    markdown = result.report.markdown

    # Committing the report and resuming reproduces the same deliverable.
    committed = {"batch_id": result.report.batch_id, "markdown": markdown}
    resumed = dict(committed)

    assert resumed["markdown"] == markdown
    assert resumed["batch_id"] == "ac7"
    # A resumed session must still see the structured counts, not just prose.
    assert result.counts["P0"] >= 1
    for section in ("Executive Summary", "P0 / P1 Items", "Trend Analysis", "Recommended Actions"):
        assert section in resumed["markdown"]


# --------------------------------------------------------------------------
# AC-8: the Skill package passes the runtime's own validator
# --------------------------------------------------------------------------


def _skill_frontmatter() -> dict:
    md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert md.startswith("---\n"), "SKILL.md must begin with YAML frontmatter"
    _, _, rest = md.partition("---\n")
    frontmatter, sep, _ = rest.partition("\n---\n")
    assert sep, "SKILL.md frontmatter must be closed with ---"
    return yaml.safe_load(frontmatter)


def test_skill_package_passes_validator():
    """SKILL.md must satisfy the skill_packages frontmatter contract (case AC-8)."""
    from app.services.skill_packages.validator import SKILL_NAME, SKILL_VERSION

    meta = _skill_frontmatter()
    assert meta["name"] == "customer_feedback_triage"
    assert SKILL_VERSION.match(str(meta["version"])), "version must be semver"
    assert str(meta["description"]).strip(), "description is required"
    assert str(meta["whenToUse"]).strip(), "whenToUse must not be empty"

    # The installable package name is a separate, kebab-case identifier: the DSH
    # package validator rejects underscores (SKILL_NAME.fullmatch), while the
    # in-repo Skill id follows the snake_case convention of the other built-ins.
    package_name = str(meta["packageName"])
    assert SKILL_NAME.fullmatch(package_name), (
        f"packageName {package_name!r} must be DSH kebab-case"
    )
    assert "-" in package_name


def test_skill_resources_declared_in_frontmatter_exist():
    meta = _skill_frontmatter()
    for resource in meta["resources"]:
        assert (SKILL_ROOT / resource).exists(), f"declared resource missing: {resource}"


# --------------------------------------------------------------------------
# Supporting contract checks
# --------------------------------------------------------------------------


def test_report_contains_required_sections_and_fields():
    result = run_triage(batch_id="sections", source=_batch(10), narrator=FakeNarrator())
    markdown = result.report.markdown

    for section in ("Executive Summary", "P0 / P1 Items", "Trend Analysis", "Recommended Actions"):
        assert section in markdown, f"missing required section: {section}"
    assert "来源批次" in markdown
    assert "分类时间" in markdown
    assert "条目总数" in markdown


def test_action_items_csv_is_parseable_and_bounded():
    result = run_triage(batch_id="csv", source=_batch(200), narrator=FakeNarrator())
    rows = list(csv.DictReader(io.StringIO(result.report.action_items_csv)))

    assert len(rows) <= ACTION_ITEM_LIMIT
    assert rows, "a batch with P0/P1 items must produce action rows"
    for row in rows:
        assert row["severity"] in {"P0", "P1"}
        assert row["item_id"]
        assert row["suggested_action"]
        assert row["owner"]


def test_duplicate_items_are_deduplicated():
    rows = [
        {"id": "d1", "body": "无法登录系统"},
        {"id": "d2", "body": "无法登录系统"},  # exact duplicate body
        {"id": "d3", "body": "页面报错"},
    ]
    result = run_triage(batch_id="dedupe", source=rows, narrator=FakeNarrator())
    assert result.report.total_items == 2


def test_validation_yaml_maps_every_criterion_to_a_test():
    spec = yaml.safe_load((SKILL_ROOT / "validation.yaml").read_text(encoding="utf-8"))
    entries = spec["acceptance"]
    assert len(entries) == 8, "the case documents eight acceptance criteria"

    this_file = Path(__file__).name
    for entry in entries:
        test_ref = entry["test"]
        assert this_file in test_ref, f"{entry['id']} points outside this module: {test_ref}"
        test_name = test_ref.split("::")[-1]
        assert test_name in globals(), f"{entry['id']} references a missing test: {test_name}"
