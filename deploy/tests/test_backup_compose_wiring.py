"""备份部署接线的静态回归守卫（023 Phase 7 / T101、T102）。

这三类缺陷都只在线上暴露，CI 里看不出来：

1. **备份卷没挂进容器**：mongo 服务挂不上备份目录，备份脚本往容器可写层写，
   ``docker compose down`` 即全丢——而「备份任务成功」的日志照样打。
2. **口令进了仓库**：口令写成 compose 的 ``environment`` 常量或出现在
   ``.env.example`` 里，等于把「加密备份」降级成「看起来加密了」。
3. **备份容器与库的生命周期绑死**：备份塞进 mongo 服务本体，库一重启备份就被
   拦腰截断，且 dump 期间与库抢 IO。

另外校验调度器与宿主 cron 两条路的时间表一致——两种部署方式节奏不同的话，
验收清单就只有一份能对上。

     python -m pytest deploy/tests/test_backup_compose_wiring.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CONTAINER_RUN = REPO_ROOT / "scripts" / "backup" / "container_run.sh"
CRONTAB_EXAMPLE = REPO_ROOT / "scripts" / "backup" / "crontab.example"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def backup_service(compose: dict) -> dict:
    services = compose.get("services", {})
    assert "mongo-backup" in services, "缺少 mongo-backup 服务（T101）"
    return services["mongo-backup"]


# ── T101：备份卷 ──────────────────────────────────────────────────────


def test_mongo_mounts_backup_volume(compose: dict) -> None:
    mongo = compose["services"]["mongo"]
    assert "mongo-backup:/backups" in mongo["volumes"], (
        "mongo 服务必须挂载 mongo-backup 卷到 /backups，否则备份产物落在容器可写层"
    )


def test_backup_volume_declared(compose: dict) -> None:
    volumes = compose.get("volumes", {})
    assert "mongo-backup" in volumes, "顶层 volumes 缺少 mongo-backup"
    name = volumes["mongo-backup"].get("name", "")
    assert name.startswith("${MOGO_VOLUME_PREFIX:-mogo}_"), (
        "卷名必须遵循 MOGO_VOLUME_PREFIX 前缀约定，否则多部署隔离会互相覆盖"
    )
    assert name.endswith("_mongo-backup")


def test_backup_runner_mounts_backup_volume(backup_service: dict) -> None:
    assert "mongo-backup:/backups" in backup_service["volumes"]
    # 脚本只读挂载：改脚本不重建镜像，但容器不能改脚本
    assert any(v.endswith(":/opt/mogo/scripts:ro") for v in backup_service["volumes"]), (
        "备份脚本必须以只读方式挂进容器"
    )


def test_backup_runner_uses_same_mongo_image(backup_service: dict) -> None:
    """mongodump 版本不能高于 server，否则 dump 直接被拒。"""
    mongo_image = "${MOGO_MONGO_IMAGE:-mongo:8.3.13}"
    assert backup_service["image"] == mongo_image, (
        "备份容器应与 mongo 服务用同一镜像变量，避免 mongodump/mongorestore 与 server 版本漂移"
    )


def test_backup_runner_is_opt_in(backup_service: dict) -> None:
    """备份容器默认不启动：不是每个部署都需要自建备份。"""
    assert backup_service.get("profiles") == ["backup"], (
        "mongo-backup 必须挂在 profile: backup 上，避免默认 up 时多起一个容器"
    )


def test_backup_runner_waits_for_healthy_mongo(backup_service: dict) -> None:
    depends = backup_service.get("depends_on", {})
    assert depends.get("mongo", {}).get("condition") == "service_healthy", (
        "备份容器必须等 mongo 健康后再启动，否则首启全量会连到未就绪的库"
    )


def test_backup_runner_has_no_listening_port(backup_service: dict) -> None:
    """备份器不该对外暴露任何端口。"""
    assert not backup_service.get("ports"), "mongo-backup 不应声明 ports"
    assert backup_service["networks"] == ["backend"], "备份容器只应接入内部 backend 网络"


def test_backup_runner_healthcheck_uses_last_success(backup_service: dict) -> None:
    """没有监听端口的服务，健康 = 上次成功运行在窗口内。"""
    test_cmd = " ".join(backup_service["healthcheck"]["test"])
    assert ".last-success" in test_cmd, (
        "备份容器健康检查应基于 .last-success 时间戳；否则只能检查进程活着，"
        "备份静默失败（cron 跑了但 dump 报错）永远发现不了"
    )
    # 窗口必须比调度间隔（15 分钟）宽，否则正常运行时也会周期性 unhealthy
    match = re.search(r"-lt (\d+)", test_cmd)
    assert match, "健康检查应带时间窗口阈值"
    assert int(match.group(1)) >= 3600, "健康检查窗口至少 1 小时（调度间隔 15 分钟）"


def test_backup_runner_passes_passphrase_file(backup_service: dict) -> None:
    env = backup_service["environment"]
    assert "MOGO_BACKUP_PASSPHRASE_FILE" in env, "备份容器必须通过文件路径取口令"
    assert "/run/secrets/" in env["MOGO_BACKUP_PASSPHRASE_FILE"], (
        "默认口令路径应指向 docker secret 挂载点"
    )
    assert backup_service.get("secrets"), "备份容器应挂载 mongo_backup_passphrase secret"


# ── T102：密钥管理 ────────────────────────────────────────────────────


def test_passphrase_secret_declared(compose: dict) -> None:
    secrets = compose.get("secrets", {})
    assert "mongo_backup_passphrase" in secrets, "顶层 secrets 缺少 mongo_backup_passphrase"


def test_passphrase_not_in_compose_environment(backup_service: dict) -> None:
    """口令只能是 secret/file 引用，不能是 environment 里的字面量。"""
    env = backup_service["environment"]
    for key in env:
        assert "PASSPHRASE" not in key or key.endswith("_FILE"), (
            f"{key} 疑似直接传口令；口令必须走文件或 secret"
        )
    rendered = COMPOSE.read_text(encoding="utf-8")
    # 常见口令字面量形态：PASSPHRASE: xxx / PASSPHRASE=xxx（排除 *_FILE 与注释）
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "PASSPHRASE_FILE" in stripped:
            continue
        assert not re.search(r"MOGO_BACKUP_PASSPHRASE\s*[:=]\s*\S", stripped), (
            f"compose 里出现口令字面量：{stripped}"
        )


def test_passphrase_not_in_env_example() -> None:
    if not ENV_EXAMPLE.exists():
        pytest.skip(".env.example 不存在")
    body = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.search(r"^MOGO_BACKUP_PASSPHRASE\s*=", stripped), (
            ".env.example 不能出现真实口令；只留 MOGO_BACKUP_PASSPHRASE_FILE 路径示例"
        )


def test_passphrase_secret_file_path_is_overridable(compose: dict) -> None:
    """单机部署用宿主文件代替 Swarm secret，路径要能覆盖。"""
    secret = compose["secrets"]["mongo_backup_passphrase"]
    assert "file" in secret, "单机 compose 需要 file: 源"
    assert "${MOGO_BACKUP_PASSPHRASE_HOST_FILE" in secret["file"], (
        "secret 文件路径应可通过 MOGO_BACKUP_PASSPHRASE_HOST_FILE 覆盖"
    )


# ── 调度器与 cron 一致 ────────────────────────────────────────────────


def test_container_scheduler_exists() -> None:
    assert CONTAINER_RUN.exists(), "缺少容器调度器 scripts/backup/container_run.sh"
    body = CONTAINER_RUN.read_text(encoding="utf-8")
    assert "job_for_minute" in body or "schedule.sh" in body, "调度器应复用统一的时刻表判定"
    assert "set -Eeuo pipefail" in body


def test_schedule_matches_crontab() -> None:
    """两条部署路径（容器调度器 / 宿主 cron）必须跑同一套节奏。"""
    schedule = (REPO_ROOT / "scripts" / "backup" / "schedule.sh").read_text(encoding="utf-8")
    cron = CRONTAB_EXAMPLE.read_text(encoding="utf-8")

    # 容器调度器：02:30 full / 04:00 rotate / 周一 05:00 drill / 其余 */15 oplog
    assert 'minute}" == "30"' in schedule and 'hour}" == "02"' in schedule
    assert 'minute}" == "00"' in schedule and 'hour}" == "04"' in schedule
    assert 'dow}" == "1"' in schedule
    assert "10#${minute} % 15" in schedule, (
        "分钟取模必须用 10# 前缀；date +%M 输出 '08' 这类前导零会被当八进制"
    )

    assert "30 2 * * *" in cron
    assert "0 4 * * *" in cron
    assert "0 5 * * 1" in cron
    assert "*/15 * * * *" in cron
    assert "CRON_TZ=UTC" in cron, "cron 示例必须锁 UTC，否则夏令时会错点"


def test_crontab_has_no_secret() -> None:
    cron = CRONTAB_EXAMPLE.read_text(encoding="utf-8")
    for line in cron.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "PASSPHRASE=" not in stripped, "crontab.example 不能写口令；口令应来自 env/secret"


def test_backup_scripts_never_default_passphrase() -> None:
    """口令缺失必须失败，不能回退内置默认值。"""
    lib = (REPO_ROOT / "scripts" / "backup" / "lib.sh").read_text(encoding="utf-8")
    assert "mogo_backup_passphrase_source" in lib
    body = lib.split("mogo_backup_passphrase_source()", 1)[1].split("\n}", 1)[0]
    assert "mogo_backup_die" in body, "取不到口令时必须 die"
    assert not re.search(r"PASSPHRASE=.*changeme|PASSPHRASE=.*default", lib, re.I), (
        "lib.sh 里不能有默认口令兜底"
    )
