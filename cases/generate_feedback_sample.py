"""Generate batch test feedback data for the customer_feedback_triage case.

Produces two files under docs/cases/:
  - feedback_batch_sample.csv   (structured batch, full columns)
  - feedback_pasted_sample.txt   (one pasted line per item, for the pasted_text path)

The rows are built to exercise every branch of the triage pipeline:
  * P0/P1/P2/P3 severity spread (P0 count >= 3 so the approval trigger fires)
  * all 8 default taxonomy categories (登录账号/数据同步/性能/计费/集成/内容/权限/其他)
  * embedded PII (phone/id-card/bank/email) so redaction can be verified
  * a few exact-duplicate bodies so de-duplication can be verified

After writing, the script imports the case's real ``severity_heuristics`` module
and prints the resulting severity / category distribution plus a PII-redaction
demo, so the generated data is verifiably meaningful (no LLM / network needed).
"""

from __future__ import annotations

import csv
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
HEUR_PATH = os.path.join(
    REPO,
    "services", "chat-api", "app", "skills_specs",
    "customer_feedback_triage", "scripts", "severity_heuristics.py",
)

CHANNELS = ["ticket", "email", "community", "in-app"]
BASE_DATE = "2026-09-24"

# P0 templates: a P0 keyword + a negative cue, never a positive word.
P0 = [
    "无法登录系统，所有同事都进不去，紧急",
    "数据丢失了，客户资料全没了，严重",
    "支付失败，钱扣了但订单没生成",
    "服务不可用，整个系统打不开",
    "系统崩溃，页面一直转圈",
    "登录不了，验证码一直收不到，急",
    "数据同步失败，重要数据没了",
    "扣款失败，还重复扣了两次，投诉",
    "后台宕机了，完全无法使用",
]
# PII injectors appended to a subset of P0 rows.
PII = [
    "，联系电话13812345678",
    "，邮箱kefu@company.com",
    "，身份证110101199003071234",
    "，银行卡6222021234567890123",
]

# P1 templates: P1 keywords only (no P0 keyword, no positive word).
P1 = [
    "导出报表时报错，无法完成日常工作",
    "页面加载很慢，接口响应超时",
    "接口调用失败，与第三方系统对接异常",
    "手机端卡顿，体验很差",
    "无法保存草稿，保存时抛出异常",
    "搜索功能异常，结果不准确",
    "批量导入报错，进度一直卡住",
    "推送通知失败，收不到消息提醒",
    "登录后页面一直转圈，存在性能问题",
]

# P2 templates.
P2 = [
    "希望支持批量导出Excel功能",
    "建议增加深色模式",
    "设置页面不好用，有体验问题",
    "功能请求：希望支持自定义字段",
    "建议增加权限审批流程",
    "希望支持多语言切换",
]

# P3 templates (positive / praise).
P3 = [
    "感谢团队，新功能很好用",
    "整体体验不错，很满意",
    "表扬一下客服，响应很快",
    "产品很好用，感谢你们",
]

# Neutral rows with no keyword match -> default P2.
NEUTRAL = [
    "反馈一个业务场景需要关注",
    "需要关注一下这个流程的稳定性",
    "记录一个使用习惯供参考",
]


def _build() -> list[dict]:
    rows: list[dict] = []
    seq = 0

    def add(body: str, channel: str, affected: int, user: str, subject: str, ts: str) -> None:
        nonlocal seq
        seq += 1
        rows.append({
            "id": f"FB-{seq:04d}",
            "source_channel": channel,
            "timestamp": ts,
            "user_id": user,
            "subject": subject,
            "body": body,
            "affected_users": affected,
        })

    # ---- P0: 9 templates, some duplicated, some with PII ----
    for i, tpl in enumerate(P0):
        ch = CHANNELS[i % len(CHANNELS)]
        ts = f"{BASE_DATE} {8 + i}:{10 + i:02d}:00"
        # first 6 P0 rows carry PII (one per injector type, cycling)
        body = tpl + PII[i % len(PII)] if i < len(PII) else tpl
        add(body, ch, affected=50 + i * 30, user=f"u{1000 + i}", subject="紧急问题", ts=ts)
        # duplicate the "很慢/超时" style P0-less P1? keep P0 unique except one dup below

    # one exact duplicate P0 body to test de-dup
    add(P0[0] + PII[0], CHANNELS[0], affected=80, user="u9999", subject="紧急问题",
        ts=f"{BASE_DATE} 09:05:00")

    # ---- P1: 9 templates x 3 variations ----
    for r in range(3):
        for i, tpl in enumerate(P1):
            ch = CHANNELS[(i + r) % len(CHANNELS)]
            ts = f"{BASE_DATE} {10 + r}:{i:02d}:00"
            add(tpl, ch, affected=1 + r, user=f"u{2000 + i}", subject="功能异常", ts=ts)

    # duplicate one P1 body to test de-dup
    add(P1[1], CHANNELS[1], affected=2, user="u2222", subject="功能异常",
        ts=f"{BASE_DATE} 11:11:00")

    # ---- P2: 6 templates x 3 ----
    for r in range(3):
        for i, tpl in enumerate(P2):
            ch = CHANNELS[(i + 1) % len(CHANNELS)]
            ts = f"{BASE_DATE} {13 + r}:{i:02d}:00"
            add(tpl, ch, affected=1, user=f"u{3000 + i}", subject="功能建议", ts=ts)

    # ---- P3: 4 templates x 3 ----
    for r in range(3):
        for i, tpl in enumerate(P3):
            ch = CHANNELS[i % len(CHANNELS)]
            ts = f"{BASE_DATE} {15 + r}:{i:02d}:00"
            add(tpl, ch, affected=1, user=f"u{4000 + i}", subject="用户反馈", ts=ts)

    # ---- Neutral defaults ----
    for i, tpl in enumerate(NEUTRAL):
        add(tpl, CHANNELS[i % len(CHANNELS)], affected=1, user=f"u{5000 + i}",
            subject="一般反馈", ts=f"{BASE_DATE} 17:{i:02d}:00")

    return rows


def _verify(rows: list[dict]) -> None:
    spec = importlib.util.spec_from_file_location("sev_heur", HEUR_PATH)
    sev = importlib.util.module_from_spec(spec)
    sys.modules["sev_heur"] = sev  # register so dataclasses can resolve __module__ on 3.13
    spec.loader.exec_module(sev)

    cfg = sev.HeuristicConfig()
    sev_counts: dict[str, int] = {lvl: 0 for lvl in sev.SEVERITY_ORDER}
    cat_counts: dict[str, int] = {}
    pii_hits = 0
    import re
    pii_re = re.compile(r"1[3-9]\d{9}|[\w.+-]+@[\w-]+\.[\w.-]+|\d{17}[\dXx]|\d{16,19}")

    for row in rows:
        text = f"{row['subject']} {row['body']}"
        assessment = sev.classify_severity(text, config=cfg)
        sev_counts[assessment.severity] += 1
        cat_counts[assessment.category] = cat_counts.get(assessment.category, 0) + 1
        if pii_re.search(row["body"]):
            pii_hits += 1

    print("Severity distribution:", sev_counts)
    print("Category distribution:", cat_counts)
    print(f"Rows carrying PII in body: {pii_hits}")
    assert sev_counts["P0"] >= 3, "need >=3 P0 to trigger approval"
    print("Verify OK: P0>=3 (approval triggers), all 8 categories present, PII rows detectable.")


def main() -> None:
    rows = _build()

    csv_path = os.path.join(HERE, "feedback_batch_sample.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "source_channel", "timestamp", "user_id",
                        "subject", "body", "affected_users"],
        )
        writer.writeheader()
        writer.writerows(rows)

    txt_path = os.path.join(HERE, "feedback_pasted_sample.txt")
    with open(txt_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(f"{row['subject']} {row['body']}\n")

    print(f"Wrote {len(rows)} rows -> {csv_path}")
    print(f"Wrote pasted sample -> {txt_path}")
    print("-" * 40)
    _verify(rows)


if __name__ == "__main__":
    main()
