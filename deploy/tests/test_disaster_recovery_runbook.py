"""T114 —— 灾难恢复预案的文档化校验。

为什么要用测试守着这份文档：`docs/runbooks/disaster-recovery.md` 不是写给人看的
宣传材料，而是**故障当场要照着做**的操作手册。它一旦退化成「标题还在、步骤没了」
（改文档时误删、合并分支丢段），人在最紧张的时候才发现，代价最大。

本文件只校验**结构**（有没有场景、每个场景有没有预案与恢复步骤、有没有引用真实
存在的脚本和文档），不校验命令对不对——命令的正确性靠脚本测试与真实演练。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "disaster-recovery.md"
RTO_DOC = REPO_ROOT / "docs" / "observability" / "rto-rpo.md"

# 骨架小节：一个场景必须同时回答「怎么判断 / 影响什么 / 怎么做 / 怎么确认好了」
SKELETON = ("症状", "影响", "恢复步骤", "验证")

# 非场景章节（前置说明、对照表、复盘模板）
NON_SCENARIO_NUMBERS = {"0", "9", "10"}


def _runbook_body() -> str:
    if not RUNBOOK.exists():
        pytest.fail(f"缺少 {RUNBOOK.relative_to(REPO_ROOT)}（T107 的交付物）")
    return RUNBOOK.read_text(encoding="utf-8")


def _scenario_blocks() -> list[tuple[str, str, str]]:
    """把 `## <数字>. 标题` 切成块，返回 (编号, 标题, 正文)。"""

    body = _runbook_body()
    matches = list(re.finditer(r"^## (\d+)\. (.+)$", body, flags=re.MULTILINE))
    blocks: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        blocks.append((match.group(1), match.group(2).strip(), body[match.end():end]))
    return blocks


def test_runbook_covers_at_least_five_scenarios() -> None:
    """T114 的硬指标：5+ 场景。"""

    scenarios = [b for b in _scenario_blocks() if b[0] not in NON_SCENARIO_NUMBERS]
    assert len(scenarios) >= 5, (
        "灾难恢复预案至少覆盖 5 个场景，当前 "
        f"{len(scenarios)} 个：{[title for _, title, _ in scenarios]}"
    )


def test_every_scenario_has_symptom_impact_recovery_and_verification() -> None:
    """每个场景都要能回答：怎么认出它、影响什么、怎么做、怎么确认恢复。"""

    offenders: list[str] = []
    scenario_count = 0
    for number, title, body in _scenario_blocks():
        if number in NON_SCENARIO_NUMBERS:
            continue
        # §8 是拓扑说明而不是故障场景，允许没有「症状」骨架
        if "症状" not in body:
            continue
        scenario_count += 1
        missing = [part for part in SKELETON if part not in body]
        if missing:
            offenders.append(f"§{number} {title} 缺 {missing}")

    assert scenario_count >= 5, f"带骨架的故障场景只有 {scenario_count} 个"
    assert not offenders, "以下场景骨架不完整：" + "；".join(offenders)


@pytest.mark.parametrize("keyword", ["MongoDB", "LLM", "宿主机", "密钥", "证书", "备份", "Redis"])
def test_runbook_covers_high_risk_failure_modes(keyword: str) -> None:
    """这几个是最可能真发生的，缺一个都不是「5+ 场景」。"""

    body = _runbook_body()
    assert keyword in body, f"预案未覆盖高风险故障模式：{keyword}"


def test_runbook_points_at_real_scripts() -> None:
    """文档里引用的脚本必须真的存在——引用错路径等于现场没有工具。"""

    body = _runbook_body()
    referenced = set(re.findall(r"scripts/[a-z_/]+\.sh", body))
    assert referenced, "预案没有引用任何恢复脚本"
    missing = sorted(rel for rel in referenced if not (REPO_ROOT / rel).exists())
    assert not missing, f"预案引用了不存在的脚本：{missing}"


def test_runbook_declares_targets_and_backup_rules() -> None:
    """目标数字和保留策略必须写在预案里，否则值班时无从判断「算不算恢复完成」。"""

    body = _runbook_body()
    assert "RTO" in body and "RPO" in body
    # 目标 RTO ≤ 30 min、RPO ≤ 15 min；保留策略 30 天本地 / 90 天异地
    assert "30 min" in body or "30min" in body
    assert "15 min" in body or "15min" in body
    assert "90 天" in body, "预案应写明异地保留 90 天"
    assert "rto-rpo.md" in body, "预案应链到 RTO/RPO 实测记录"


def test_runbook_cross_az_section_matches_drill_script() -> None:
    """§8 说「自动切换靠 drain 节点」，那就必须指向真实的演练脚本。"""

    body = _runbook_body()
    assert "跨 AZ" in body
    assert "drill_az_failover.sh" in body
    assert (REPO_ROOT / "scripts" / "drill" / "drill_az_failover.sh").exists()
    assert "docker-compose.prod.yml" in body


def test_rto_rpo_doc_records_measurements_honestly() -> None:
    """实测记录表存在，且未演练的场景被明确标出来——不许拿「脚本测试通过」冒充 RTO 达标。"""

    assert RTO_DOC.exists(), "缺少 docs/observability/rto-rpo.md（T108 的交付物）"
    body = RTO_DOC.read_text(encoding="utf-8")

    assert "RTO" in body and "RPO" in body
    assert "30" in body and "15" in body, "文档应写明目标 RTO ≤ 30min、RPO ≤ 15min"

    # 实测记录表 + 诚实的未演练说明
    assert "实测" in body
    assert "未演练" in body, "没有真实演练时必须如实标注「未演练」"
    assert "drill_recovery.sh" in body and "drill_az_failover.sh" in body


def test_keepalived_helper_documented_and_present() -> None:
    """预案 §8.3 引用了自建 VIP 方案，就得有可执行的健康检查脚本。"""

    readme = REPO_ROOT / "deploy" / "keepalived" / "README.md"
    script = REPO_ROOT / "deploy" / "keepalived" / "check_gateway.sh"
    assert readme.exists() and script.exists(), "缺少 deploy/keepalived/ 文档或健康检查脚本"
    assert "check_gateway.sh" in readme.read_text(encoding="utf-8")
    # 只查 /health：依赖抖动不该导致 VIP 漂移
    text = script.read_text(encoding="utf-8")
    assert "/health" in text
    assert "mongo" not in text.replace("MongoDB", ""), "VIP 健康检查不应依赖 Mongo"
