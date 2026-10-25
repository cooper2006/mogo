"""告警与排障配置的静态回归守卫（023 Phase 5 / T061–T067）。

覆盖三类**只会在线上暴露**的缺陷：

1. **Alertmanager 启动即失败**：``alertmanager.yml`` 里出现未知字段
   （``webhook_url_template``、顶层 ``silences``）时，Alertmanager 用
   ``UnmarshalStrict`` 解析并直接退出——告警通道全哑，而 CI 只跑 Python 测试，
   完全发现不了。2026-10-25 修复前仓库里就是这么写的。

2. **规则文件根本没被加载**：``prometheus.yml`` 写了 ``rule_files`` 但
   ``docker-compose.yml`` 没把宿主机目录挂进容器，Prometheus 静默地在空目录上
   启动——规则「存在」但永不触发。这是「配置正确、部署错误」的经典形态，
   只看 YAML 内容永远查不出来，所以必须同时校验 compose 挂载。

3. **告警文案指向死链**：每个 ``runbook_url`` 必须指向真实存在的文件；
   FR-19 要求至少 5 个场景且每个场景含症状/影响/根因/恢复步骤/复盘模板五节。

全部是静态检查，不需要 docker，任何平台可跑::

    python -m pytest deploy/tests/test_observability_alerting_config.py -q
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

ALERTMANAGER_CONFIG = "deploy/alertmanager/alertmanager.yml"
ALERTMANAGER_TEMPLATES_DIR = "deploy/alertmanager/templates"
PROMETHEUS_CONFIG = "deploy/prometheus/prometheus.yml"
ALERT_RULES = "deploy/prometheus/rules/alert-rules.yml"
COMPOSE_PATH = "docker-compose.yml"
RUNBOOK_DIR = "docs/runbooks"
DASHBOARD_DIR = "deploy/grafana/provisioning/dashboards"

# Alertmanager 顶层合法字段（v0.27 config 结构）。
ALLOWED_TOP_LEVEL = {
    "global",
    "route",
    "receivers",
    "inhibit_rules",
    "templates",
    "time_intervals",
    "mute_time_intervals",
}

# receiver 内允许的配置块。
ALLOWED_RECEIVER_KEYS = {
    "name",
    "email_configs",
    "webhook_configs",
    "slack_configs",
    "pagerduty_configs",
    "pushover_configs",
    "opsgenie_configs",
    "victorops_configs",
    "wechat_configs",
    "msteams_configs",
    "sns_configs",
    "webex_configs",
    "telegram_configs",
    "discord_configs",
}

SEVERITIES = {"P0", "P1", "P2"}

# FR-19 要求的 5 个场景（文件名必须存在）。
REQUIRED_SCENARIOS = [
    "mongodb_unreachable.md",
    "llm_timeout.md",
    "redis_stall.md",
    "queue_backlog.md",
    "certificate_expired.md",
]

# 每个场景文档必须包含的 5 个小节关键词（FR-19）。
REQUIRED_SECTIONS = ["症状", "影响", "根因", "恢复步骤", "复盘"]


def _read(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    assert path.exists(), f"缺少文件：{rel_path}"
    return path.read_text(encoding="utf-8")


def _load_yaml(rel_path: str) -> dict[str, Any]:
    return yaml.safe_load(_read(rel_path))


def _walk_routes(route: dict[str, Any]):
    """深度优先遍历 route 树，产出每个 route 节点。"""
    yield route
    for child in route.get("routes") or []:
        yield from _walk_routes(child)


# --------------------------------------------------------------------------
# 1. Alertmanager 配置：不能有未知字段（否则启动即失败）
# --------------------------------------------------------------------------


def test_alertmanager_top_level_keys_are_all_known():
    config = _load_yaml(ALERTMANAGER_CONFIG)
    unknown = set(config) - ALLOWED_TOP_LEVEL
    assert not unknown, (
        f"{ALERTMANAGER_CONFIG} 出现 Alertmanager 不认识的顶层字段：{sorted(unknown)}。"
        "Alertmanager 使用 UnmarshalStrict 解析，未知字段会导致启动失败，告警通道全哑。"
    )


def test_alertmanager_silences_are_not_in_static_config():
    """静默是运行时对象，写进配置文件同样会触发未知字段错误。"""
    config = _load_yaml(ALERTMANAGER_CONFIG)
    assert "silences" not in config, (
        "静默（silence）必须通过 amtool/API 创建，不能写进 alertmanager.yml；"
        "顶层 silences 字段会让 Alertmanager 启动失败。"
    )


def test_alertmanager_receivers_have_no_unknown_keys():
    config = _load_yaml(ALERTMANAGER_CONFIG)
    receivers = config.get("receivers") or []
    assert receivers, "alertmanager.yml 至少需要一个 receiver"

    for receiver in receivers:
        unknown = set(receiver) - ALLOWED_RECEIVER_KEYS
        assert not unknown, (
            f"receiver {receiver.get('name')!r} 含未知字段 {sorted(unknown)}；"
            "每个通知通道的配置必须放在对应的 *_configs 列表里。"
        )


def test_alertmanager_templates_are_registered_and_exist():
    config = _load_yaml(ALERTMANAGER_CONFIG)
    templates = config.get("templates") or []
    assert templates, "P0 告警文案需要模板（分级提示 + 三个排障入口），templates 不能为空"

    compose_text = _read(COMPOSE_PATH)
    # templates 里写的是**容器内**路径（可带通配符）。要能在宿主机上找到文件，
    # 前提是 compose 把宿主目录挂进了这个容器目录——只校验宿主机目录存在是不够的
    # （挂载漏了，容器内模板目录为空，Alertmanager 会因找不到模板而告警文案降级）。
    host_dir = REPO_ROOT / ALERTMANAGER_TEMPLATES_DIR
    assert host_dir.is_dir(), f"宿主机模板目录不存在：{ALERTMANAGER_TEMPLATES_DIR}"
    host_templates = list(host_dir.glob("*.tmpl"))
    assert host_templates, f"{ALERTMANAGER_TEMPLATES_DIR} 下没有 *.tmpl"

    for entry in templates:
        container_dir = str(Path(entry).parent)
        assert container_dir in compose_text, (
            f"templates 引用了容器内路径 {entry}，但 docker-compose.yml 没有挂载 "
            f"{container_dir} —— 容器内模板目录为空。"
        )

    combined = "\n".join(p.read_text(encoding="utf-8") for p in host_templates)
    for name in ("mogo.title", "mogo.links", "mogo.text", "mogo.html"):
        assert f'define "{name}"' in combined, f"模板缺少 {name} 定义（P0 文案必需三个排障入口）"


def test_alertmanager_has_severity_routes_for_all_levels():
    """FR-17：P0/P1/P2 必须分级路由，且 P2 不主动打扰。"""
    config = _load_yaml(ALERTMANAGER_CONFIG)
    route = config["route"]

    severities_in_matchers: set[str] = set()
    for node in _walk_routes(route):
        for matcher in node.get("matchers") or []:
            # 形如 severity="P0" 或 severity=~"P[01]"
            if "severity" in matcher:
                severities_in_matchers.update(re.findall(r"P[012]", matcher))

    missing = SEVERITIES - severities_in_matchers
    assert not missing, f"路由树缺少这些级别的专门分支：{sorted(missing)}"

    # 每个 receiver 引用都必须真实存在
    names = {r["name"] for r in config["receivers"]}
    for node in _walk_routes(route):
        receiver = node.get("receiver")
        if receiver:
            assert receiver in names, f"route 引用了未定义的 receiver：{receiver}"


def test_alertmanager_inhibit_rules_are_well_formed():
    config = _load_yaml(ALERTMANAGER_CONFIG)
    rules = config.get("inhibit_rules") or []
    assert rules, "至少需要抑制规则：同一根因只打扰一次"

    for idx, rule in enumerate(rules):
        assert rule.get("source_matchers"), f"inhibit_rules[{idx}] 缺少 source_matchers"
        assert rule.get("target_matchers"), f"inhibit_rules[{idx}] 缺少 target_matchers"


# --------------------------------------------------------------------------
# 2. Prometheus：规则文件必须被真实加载（内容 + 挂载两者都校验）
# --------------------------------------------------------------------------


def test_prometheus_rule_files_reference_mounted_directory():
    prom = _load_yaml(PROMETHEUS_CONFIG)
    rule_files = prom.get("rule_files") or []
    assert rule_files, "prometheus.yml 必须配置 rule_files，否则规则永不加载"

    compose_text = _read(COMPOSE_PATH)
    # 规则文件在容器内的路径形如 /etc/prometheus/rules/*.yml
    container_dirs = {
        str(Path(rf).parent) for rf in rule_files if rf.startswith("/etc/prometheus")
    }
    assert container_dirs, f"rule_files 应位于容器内 /etc/prometheus 下，实际：{rule_files}"

    for container_dir in container_dirs:
        assert container_dir in compose_text, (
            f"prometheus.yml 的 rule_files 用了容器内路径 {container_dir}，"
            f"但 docker-compose.yml 没有对应挂载 —— 容器内该目录为空，规则静默失效。"
        )

    # 宿主侧目录必须真的存在且有 yml
    host_dir = REPO_ROOT / "deploy/prometheus/rules"
    assert host_dir.is_dir(), "宿主机规则目录 deploy/prometheus/rules/ 不存在"
    assert list(host_dir.glob("*.yml")), "deploy/prometheus/rules/ 下没有任何 *.yml 规则文件"


def test_every_rule_document_is_covered_by_rule_files():
    """新增的规则文件必须落在 rule_files 通配范围内，否则等于没写。

    真实事故形态（2026-10-25 自查发现）：T063–T065 把告警规则写到了
    ``deploy/prometheus/alert-rules.yml``，而 ``rule_files`` 只匹配
    ``/etc/prometheus/rules/*.yml`` —— 文件存在、YAML 合法、测试全绿，
    但 Prometheus 从未加载它，线上一条告警都不会响。
    """
    prom = _load_yaml(PROMETHEUS_CONFIG)
    globs = [rf for rf in (prom.get("rule_files") or []) if rf.startswith("/etc/prometheus")]

    # 容器内 glob → 宿主 glob
    mount_root = Path("deploy/prometheus")
    host_globs = []
    for pattern in globs:
        rel = pattern[len("/etc/prometheus/") :]
        host_globs.append(mount_root / rel)

    patterns = [str(g) for g in host_globs]

    def covered(path: Path) -> bool:
        # Path.match 按从右往左匹配相对模式，正好等价于 Prometheus 的通配语义
        return any(path.match(pattern) for pattern in patterns)

    rule_docs = []
    for path in sorted((REPO_ROOT / mount_root).rglob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if "groups" in doc:
            rule_docs.append(path)

    assert rule_docs, "deploy/prometheus 下没有找到任何规则文档"

    uncovered = [p for p in rule_docs if not covered(p)]
    assert not uncovered, (
        "这些规则文档不在 rule_files 通配范围内，Prometheus 不会加载它们："
        + ", ".join(str(p.relative_to(REPO_ROOT)) for p in uncovered)
    )


def _has_service_dimension(alert: dict[str, Any]) -> bool:
    """service 维度的来源有两种，都算合格：

    1. 静态 ``labels.service``（如 ``service: chat-api``）；
    2. 表达式聚合/重命名出来的 service（``sum by (service)`` 或
       ``label_replace(..., "service", ...)``）——聚合类 SLO 告警只能这样带维度。

    之所以要求 service 必须存在：Alertmanager 的静默与抑制规则按 ``service``
    匹配，缺了这个 label 意味着这条告警**既压不掉也抑制不了**。
    """
    if (alert.get("labels") or {}).get("service"):
        return True
    expr = str(alert.get("expr") or "")
    # 形如 sum by (service) / sum by (le, service) / label_replace(..., "service", ...)
    if re.search(r"by\s*\([^)]*\bservice\b", expr):
        return True
    return '"service"' in expr


def test_every_alert_rule_is_complete():
    rules_doc = _load_yaml(ALERT_RULES)
    groups = rules_doc.get("groups") or []
    assert groups, "alert-rules.yml 必须包含 groups"

    alerts: list[dict[str, Any]] = []
    for group in groups:
        assert group.get("name"), "每个 rule group 必须有 name"
        assert group.get("rules"), f"rule group {group.get('name')!r} 为空"
        alerts.extend(group["rules"])

    assert len(alerts) >= 6, f"告警规则过少（{len(alerts)} 条），未覆盖 FR-16 的三类"

    for alert in alerts:
        name = alert.get("alert")
        assert name, f"规则缺少 alert 名称：{alert}"
        assert alert.get("expr"), f"{name} 缺少 expr"

        labels = alert.get("labels") or {}
        assert labels.get("severity") in SEVERITIES, (
            f"{name} 的 labels.severity 必须是 {sorted(SEVERITIES)}，实际 {labels.get('severity')!r}"
        )
        assert _has_service_dimension(alert), (
            f"{name} 既没有 labels.service，表达式里也没有 service 维度 —— "
            "静默与抑制规则按 service 匹配，缺了它这条告警压不掉。"
        )

        annotations = alert.get("annotations") or {}
        assert annotations.get("summary"), f"{name} 缺少 annotations.summary"
        assert annotations.get("description"), f"{name} 缺少 annotations.description"
        assert annotations.get("runbook_url"), f"{name} 缺少 annotations.runbook_url（FR-18）"
        assert annotations.get("dashboard_url"), f"{name} 缺少 annotations.dashboard_url（FR-18）"


def test_alert_expressions_have_balanced_delimiters():
    """PromQL 结构自检（**不是**完整语法校验）。

    如实说明能力边界：真正权威的校验是
    ``docker run --rm -v $PWD/deploy/prometheus:/etc/prometheus:ro \\
        --entrypoint promtool prom/prometheus:v2.53.4 check rules /etc/prometheus/*.yml``。
    本机无法访问 Docker Hub（2026-10-25 实测 registry-1.docker.io 返回 Bad Gateway），
    因此这里只做括号/引号配平这类「写错就打不开」的廉价检查，用来兜住手改 YAML 时
    最常见的断括号；语义正确性仍需在有镜像的机器上跑 promtool。
    """
    rules_doc = _load_yaml(ALERT_RULES)
    pairs = {")": "(", "]": "[", "}": "{"}

    for group in rules_doc.get("groups") or []:
        for alert in group["rules"]:
            name = alert["alert"]
            expr = str(alert["expr"])

            assert expr.strip(), f"{name} 的 expr 为空"
            assert re.search(r">|<|==|!=|>=|<=", expr), (
                f"{name} 的 expr 没有比较运算符 —— 告警规则必须是布尔判定"
            )

            stack: list[str] = []
            for char in expr:
                if char in "([{":
                    stack.append(char)
                elif char in pairs:
                    assert stack, f"{name} 的 expr 出现多余的 {char!r}：{expr}"
                    assert stack.pop() == pairs[char], (
                        f"{name} 的 expr 括号配对错误（{char!r} 不匹配）：{expr}"
                    )
            assert not stack, f"{name} 的 expr 有未闭合的括号 {stack}：{expr}"
            assert expr.count('"') % 2 == 0, f"{name} 的 expr 引号未闭合：{expr}"


def test_alert_runbook_urls_point_to_existing_files():
    """告警文案里的 Runbook 链接不能是死链。"""
    rules_doc = _load_yaml(ALERT_RULES)
    for group in rules_doc.get("groups") or []:
        for alert in group["rules"]:
            url = (alert.get("annotations") or {}).get("runbook_url")
            if not url:
                continue
            assert url.startswith("https://github.com/cooper2006/mogo/blob/"), (
                f"{alert['alert']} 的 runbook_url 必须指向本仓库：{url}"
            )
            rel = url.split("/blob/", 1)[1].split("/", 1)[1]
            assert (REPO_ROOT / rel).exists(), f"{alert['alert']} 的 Runbook 死链：{url}"


# --------------------------------------------------------------------------
# 3. Runbook 覆盖度（FR-19）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("filename", REQUIRED_SCENARIOS)
def test_required_runbook_exists_with_all_five_sections(filename: str):
    rel = f"{RUNBOOK_DIR}/{filename}"
    text = _read(rel)

    for section in REQUIRED_SECTIONS:
        assert section in text, f"{rel} 缺少必需小节关键词「{section}」（FR-19 要求五节齐全）"

    assert "```" in text, f"{rel} 必须给出可直接复制的命令（代码块）"


def test_runbook_index_maps_every_alert():
    """docs/runbooks/README.md 必须登记所有告警，否则告警里的链接会脱离索引。"""
    index = _read(f"{RUNBOOK_DIR}/README.md")
    rules_doc = _load_yaml(ALERT_RULES)

    for group in rules_doc.get("groups") or []:
        for alert in group["rules"]:
            name = alert["alert"]
            assert name in index, (
                f"告警 {name} 未在 docs/runbooks/README.md 的映射表登记 —— "
                "值班同学从索引找不到对应处置文档。"
            )


# --------------------------------------------------------------------------
# 4. Grafana 排障看板（FR-20 逐层下钻）
# --------------------------------------------------------------------------


def test_troubleshooting_dashboard_exists_with_drilldown_layers():
    path = REPO_ROOT / DASHBOARD_DIR / "troubleshooting.json"
    assert path.exists(), "缺少排障看板 troubleshooting.json（FR-20）"
    dashboard = json.loads(path.read_text(encoding="utf-8"))

    assert dashboard.get("uid") == "mogo-troubleshooting"
    titles = " ".join(p.get("title", "") for p in dashboard.get("panels", []))
    for layer in ("服务概览", "依赖健康", "热点路由", "Trace"):
        assert layer in titles, f"排障看板缺少下钻层级：{layer}"

    # 必须支持按 trace_id 定位单条 span
    variables = {
        v.get("name") for v in (dashboard.get("templating") or {}).get("list", [])
    }
    assert "trace_id" in variables, "排障看板需要 trace_id 变量才能下钻到单个慢请求 span"


def test_all_dashboard_json_files_are_valid():
    files = sorted((REPO_ROOT / DASHBOARD_DIR).glob("*.json"))
    assert len(files) >= 4, f"看板数量不足：{len(files)}"
    for path in files:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        assert dashboard.get("uid"), f"{path.name} 缺少 uid"
        assert dashboard.get("panels"), f"{path.name} 没有任何面板"
        for panel in dashboard["panels"]:
            assert panel.get("id") is not None, f"{path.name} 面板缺少 id"
            assert panel.get("type"), f"{path.name} 面板缺少 type"
            for target in panel.get("targets") or []:
                assert target.get("expr"), f"{path.name} 面板 {panel.get('id')} 存在空查询"
