"""跨 AZ 故障切换配置的静态回归守卫（023 Phase 7 / T112）。

「单个 AZ 挂掉，关键服务 30 分钟内自动接上」这件事没有任何单元测试能覆盖，
但它的**配置前提**可以静态钉住。历史上出错的方式几乎都是配置层：

1. 只起了一个副本 —— 一主一备根本没备起来，节点挂掉就是全站挂。
2. 两个副本落在同一节点 —— 视觉上「有两个」，节点挂掉两个一起没。
3. 没有 ``update_config.order: start-first`` —— 滚动更新时先停后起，
   每次发版都有几十秒全站不可用，而且恰好在变更窗口里失去冗余。
4. ``restart_policy.max_attempts`` 写成一个有限值 —— 反复崩溃后放弃重启，
   服务就那么躺着，等人发现。
5. 探针查错东西：把依赖检查挂到 liveness 上 —— 数据库抖动变成连环重启。

真实的节点宕机演练见 ``scripts/drill/drill_az_failover.sh``。

    python -m pytest deploy/tests/test_prod_az_failover.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "deploy" / "docker-compose.prod.yml"
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
PROBES = REPO_ROOT / "deploy" / "probes"
DRILL = REPO_ROOT / "scripts" / "drill" / "drill_az_failover.sh"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "disaster-recovery.md"
RTO_DOC = REPO_ROOT / "docs" / "observability" / "rto-rpo.md"

# 「关键服务」：挂掉就直接影响用户请求的那几个。
CRITICAL = ["chat-api", "admin-api", "document-api", "gateway"]


@pytest.fixture(scope="module")
def prod() -> dict:
    assert PROD_COMPOSE.exists(), "缺少 deploy/docker-compose.prod.yml（T103）"
    return yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))


# ── T103：跨 AZ 拓扑 ──────────────────────────────────────────────────


def test_prod_compose_is_mergeable_override(prod: dict) -> None:
    """必须是覆盖文件：不重复定义基础服务，只写差异。"""
    assert prod.get("name") == "mogo", "覆盖文件的 project name 必须与基础文件一致"
    base = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    unknown = set(prod["services"]) - set(base["services"])
    assert not unknown, f"prod 覆盖文件里出现基础文件没有的服务：{sorted(unknown)}"


def test_prod_compose_not_auto_loaded() -> None:
    """放在 deploy/ 下是有意的：Compose 只自动加载同目录的 docker-compose.<profile>.yml。"""
    auto = REPO_ROOT / "docker-compose.prod.yml"
    assert not auto.exists(), (
        "根目录出现 docker-compose.prod.yml 会被某些工装自动合并；"
        "生产覆盖文件应留在 deploy/ 下并显式 -f"
    )


def test_placement_keeps_replicas_off_same_node(prod: dict) -> None:
    """一主一备必须分布在两个节点；同一节点上两个副本等于只有一个。"""
    for service in CRITICAL:
        deploy = prod["services"][service]["deploy"]
        assert deploy["replicas"] >= 2, f"{service} 至少一主一备（replicas >= 2）"
        placement = deploy.get("placement", {})
        assert placement.get("max_replicas_per_node") == 1, (
            f"{service} 必须限制每节点最多 1 个副本，否则两个副本会挤在同一节点"
        )


def test_stateful_services_single_replica(prod: dict) -> None:
    """Mongo/Redis 靠副本集而不是多起容器；两个单机 mongod 是两个不同步的库。"""
    for service in ("mongo", "redis", "mongo-backup"):
        deploy = prod["services"][service]["deploy"]
        assert deploy["replicas"] == 1, f"{service} 应为单副本（HA 由副本集/单实例语义承担）"


def test_stateful_services_pinned_to_data_nodes(prod: dict) -> None:
    for service in ("mongo", "redis"):
        placement = prod["services"][service]["deploy"]["placement"]
        constraints = placement.get("constraints", [])
        assert any("node.labels.mogo.data" in c for c in constraints), (
            f"{service} 必须钉在有本地数据盘的节点上，数据卷不能跨节点漂移"
        )


# ── T104：一主一备 + 无缝切换 ─────────────────────────────────────────


def test_update_is_start_first(prod: dict) -> None:
    """先起新副本再停旧的：发版窗口里始终有实例接流量。"""
    for service in CRITICAL:
        update = prod["services"][service]["deploy"]["update_config"]
        assert update["order"] == "start-first", (
            f"{service} 的 update_config.order 必须是 start-first（默认 stop-first 会造成冷启动缺口）"
        )


def test_update_rolls_back_on_failure(prod: dict) -> None:
    """坏镜像不能把两个 AZ 一起换掉。"""
    for service in CRITICAL:
        update = prod["services"][service]["deploy"]["update_config"]
        assert update["failure_action"] == "rollback", f"{service} 更新失败必须自动回滚"
        assert update.get("monitor"), f"{service} 需要 monitor 窗口判定新副本真的稳定了"


# ── T105：探针 ────────────────────────────────────────────────────────


def test_critical_services_use_readiness_probe(prod: dict) -> None:
    for service in ("chat-api", "admin-api", "document-api"):
        test_cmd = " ".join(prod["services"][service]["healthcheck"]["test"])
        assert "readiness.sh" in test_cmd, (
            f"{service} 的 healthcheck 应跑 readiness 探针（依赖不可用时不接流量）"
        )
        assert "liveness.sh" not in test_cmd, (
            f"{service} 的 healthcheck 不能跑 liveness（依赖检查放这里会连锁重启）"
        )


def test_probes_mounted_read_only(prod: dict) -> None:
    for service in ("chat-api", "admin-api", "document-api"):
        volumes = prod["services"][service].get("volumes", [])
        assert any(v.endswith(":/opt/mogo/deploy/probes:ro") for v in volumes), (
            f"{service} 需要把探针脚本只读挂进容器"
        )


def test_probe_scripts_exist() -> None:
    assert (PROBES / "readiness.sh").exists()
    assert (PROBES / "liveness.sh").exists()


def test_healthcheck_start_period_allows_cold_start(prod: dict) -> None:
    """start_period 太短会造成「没起来就判死 → 重启 → 又没起来」的崩溃循环。"""
    for service in CRITICAL:
        healthcheck = prod["services"][service]["healthcheck"]
        start_period = healthcheck["start_period"]
        seconds = int(str(start_period).rstrip("s"))
        assert seconds >= 30, f"{service} 的 start_period 至少 30s，实际 {start_period}"
        assert healthcheck["retries"] >= 3, f"{service} 需要连续多次失败才判死（容忍一次 GC 停顿）"


# ── T106：restart policy ──────────────────────────────────────────────


def test_restart_policy_never_gives_up(prod: dict) -> None:
    """max_attempts: 0 表示无限重试；写成有限值会在持续故障后彻底放弃。"""
    for service in CRITICAL:
        policy = prod["services"][service]["deploy"]["restart_policy"]
        assert policy["condition"] == "any", f"{service} 任何退出方式都应重启"
        assert policy["max_attempts"] == 0, (
            f"{service} 的 max_attempts 必须是 0（无限），否则连续崩溃后会彻底不重启"
        )


def test_base_compose_keeps_restart_policy(prod: dict) -> None:
    """单机模式靠 restart: unless-stopped，覆盖文件不能把它抹掉。"""
    base = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    for service in CRITICAL:
        if service in prod["services"]:
            assert "restart" not in prod["services"][service], (
                f"{service} 在覆盖文件里重设 restart 会覆盖单机模式的 unless-stopped；"
                "单机靠 restart、Swarm 靠 deploy.restart_policy，两者并存"
            )
        assert base["services"][service].get("restart") == "unless-stopped"


# ── T112：演练工具与文档 ──────────────────────────────────────────────


def test_az_failover_drill_exists() -> None:
    assert DRILL.exists(), "缺少 scripts/drill/drill_az_failover.sh（T112 的演练入口）"
    body = DRILL.read_text(encoding="utf-8")
    for needle in ("docker node update", "drain", "--availability", "active"):
        assert needle in body, f"演练脚本应包含 {needle}（模拟节点下线与恢复）"
    assert "RTO" in body, "演练脚本必须记录 RTO 实测值"


def test_failover_drill_records_report() -> None:
    body = DRILL.read_text(encoding="utf-8")
    assert "report" in body.lower(), "演练应落盘报告"
    assert "30" in body or "1800" in body, "演练应体现 RTO ≤ 30min 的预算"


def test_runbook_covers_az_failure() -> None:
    if not RUNBOOK.exists():
        pytest.skip("disaster-recovery.md 尚未创建（T107）")
    body = RUNBOOK.read_text(encoding="utf-8")
    assert "跨 AZ" in body or "跨AZ" in body, "灾难恢复预案必须覆盖跨 AZ 故障"
    assert DRILL.name in body or "drill_az_failover" in body, "预案应指向演练脚本"


def test_rto_rpo_doc_declares_targets() -> None:
    if not RTO_DOC.exists():
        pytest.skip("rto-rpo.md 尚未创建（T108）")
    body = RTO_DOC.read_text(encoding="utf-8")
    assert "RTO" in body and "RPO" in body
    assert "30" in body and "15" in body, "文档应写明目标 RTO ≤ 30min、RPO ≤ 15min"
