#!/usr/bin/env bash
# 024 T067/T069/T070 (FR-034/FR-036)：备份调度与保留策略。
#
# 提供：
#   mogo_backup_schedule_install [cron|systemd]   安装定时备份
#   mogo_backup_schedule_uninstall                卸载已安装的调度
#   mogo_backup_schedule_status                   查看调度与最近备份/保留情况
#   mogo_backup_schedule_prune                    按保留策略清理过期备份
#   mogo_backup_schedule_run                      执行一次备份（失败结构化告警）
#
# 配置：deploy/config/backup-schedule.yml（周期/目标窗口/保留策略/告警渠道）。
# 本脚本只被 mogo source，不单独执行。

if [[ -z "${ROOT_DIR:-}" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

# shellcheck source=deploy/cli/backup.sh
# shellcheck source=deploy/cli/notify.sh
source "${ROOT_DIR}/deploy/cli/notify.sh"

mogo_backup_schedule_config() {
  local cfg_file="${ROOT_DIR}/deploy/config/backup-schedule.yml"
  if [[ ! -f "${cfg_file}" ]]; then
    printf '错误: 缺少 %s\n' "${cfg_file}" >&2
    return 2
  fi
  python3 -c '
import json, sys, yaml
cfg = yaml.safe_load(open(sys.argv[1]))
s = cfg.get("schedule", {}); r = cfg.get("retention", {}); a = cfg.get("alert", {})
print(json.dumps({
  "cron": s.get("cron", "0 2 * * *"),
  "window": s.get("window", "02:00-05:00"),
  "timezone": s.get("timezone", "Asia/Shanghai"),
  "retain_count": r.get("retain_count", 7),
  "retain_days": r.get("retain_days", 14),
  "min_keep": r.get("min_keep", 3),
  "channel": a.get("channel", "log"),
  "webhook_url": a.get("webhook_url", ""),
  "fail_threshold": a.get("consecutive_fail_threshold", 2),
  "backup_command": cfg.get("backup_command", "./mogo backup"),
  "backup_dir": cfg.get("backup_dir", "backups"),
}, ensure_ascii=False))' "${cfg_file}" 2>/dev/null || {
    printf '错误: 无法解析 %s\n' "${cfg_file}" >&2
    return 2
  }
}

mogo_backup_schedule_install_cron() {
  local cron_line
  cron_line="$(mogo_backup_schedule_config | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["cron"])')"
  [[ -z "${cron_line}" ]] && { printf '错误: cron 表达式为空\n' >&2; return 2; }
  local entry="${cron_line} ${ROOT_DIR}/deploy/cli/backup-schedule.sh cron-run >/tmp/mogo-backup-schedule.log 2>&1"
  local crontab_now
  if command -v crontab >/dev/null 2>&1; then
    crontab_now="$(crontab -l 2>/dev/null | grep -v 'mogo-backup-schedule.sh cron-run' || true)"
    printf '%s\n%s\n' "${crontab_now}" "${entry}" | crontab -
    printf '已安装 cron 定时备份: %s\n' "${entry}"
  else
    printf '错误: 未找到 crontab 命令\n' >&2
    return 2
  fi
}

mogo_backup_schedule_install_systemd() {
  local cron_line
  cron_line="$(mogo_backup_schedule_config | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["cron"])')"
  # 把 5 段 cron 转成 systemd OnCalendar 格式
  local oncal
  oncal="$(python3 -c '
import sys
f = sys.argv[1].split()
if len(f) == 5:
    print(f[1] + "-*-* " + f[0] + ":00:00")
else:
    print("*-*-* 02:00:00")' "${cron_line}")"
  local unit_dir="/etc/systemd/system"
  if [[ ! -d "${unit_dir}" ]] || [[ ! -w "${unit_dir}" ]]; then
    printf '错误: 需要 root 才能安装 systemd timer 到 %s\n' "${unit_dir}" >&2
    return 2
  fi
  cat > "${unit_dir}/mogo-backup.service" <<EOF
[Unit]
Description=Mogo 定时备份
After=docker.service

[Service]
Type=oneshot
ExecStart=${ROOT_DIR}/deploy/cli/backup-schedule.sh cron-run
EOF
  cat > "${unit_dir}/mogo-backup.timer" <<EOF
[Unit]
Description=Mogo 定时备份触发器

[Timer]
OnCalendar=${oncal}
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl enable --now mogo-backup.timer >/dev/null 2>&1 || true
  printf '已安装 systemd timer: OnCalendar=%s (mogo-backup.timer)\n' "${oncal}"
}

mogo_backup_schedule_uninstall() {
  if command -v crontab >/dev/null 2>&1; then
    crontab -l 2>/dev/null | grep -v 'mogo-backup-schedule.sh cron-run' | crontab - 2>/dev/null || true
    printf '已移除 cron 条目\n'
  fi
  if [[ -d "/etc/systemd/system" ]]; then
    rm -f /etc/systemd/system/mogo-backup.service /etc/systemd/system/mogo-backup.timer 2>/dev/null
    systemctl daemon-reload >/dev/null 2>&1 || true
    printf '已移除 systemd 单元\n'
  fi
}

mogo_backup_schedule_status() {
  local cfg
  cfg="$(mogo_backup_schedule_config)"
  python3 -c '
import json, sys, os, glob, time
cfg = json.loads(sys.argv[1])
root = sys.argv[2]
print("备份调度状态")
print("  周期(cron): " + cfg["cron"])
print("  目标窗口: " + cfg["window"] + " (" + cfg["timezone"] + ")")
print("  保留策略: 保留 " + str(cfg["retain_count"]) + " 份 / " + str(cfg["retain_days"]) + " 天 (下限 " + str(cfg["min_keep"]) + " 份)")
# cron
try:
    crontab = os.popen("crontab -l 2>/dev/null").read()
    installed = "mogo-backup-schedule.sh cron-run" in crontab
    print("  cron 已安装: " + ("是" if installed else "否"))
except Exception:
    print("  cron 已安装: 未知")
# systemd
try:
    installed_sd = os.path.exists("/etc/systemd/system/mogo-backup.timer")
    print("  systemd timer 已安装: " + ("是" if installed_sd else "否"))
except Exception:
    print("  systemd timer 已安装: 未知")
# 最近备份
bd = os.path.join(root, cfg["backup_dir"])
backups = sorted(glob.glob(os.path.join(bd, "mogo-backup-*")))
if backups:
    newest = backups[-1]
    try:
        age_days = (time.time() - os.path.getmtime(newest)) / 86400.0
    except Exception:
        age_days = -1
    print("  备份目录: " + bd)
    print("  最近备份: " + os.path.basename(newest) + " (约 " + format(age_days, ".1f") + " 天前)")
    print("  备份总数: " + str(len(backups)))
else:
    print("  备份目录: " + bd + "（暂无备份）")
' "${cfg}" "${ROOT_DIR}"
}

mogo_backup_schedule_prune() {
  local cfg; cfg="$(mogo_backup_schedule_config)"
  python3 -c '
import json, sys, os, glob, time, shutil
cfg = json.loads(sys.argv[1]); root = sys.argv[2]
bd = os.path.join(root, cfg["backup_dir"])
backups = sorted(glob.glob(os.path.join(bd, "mogo-backup-*")))
if not backups:
    print("没有备份需要清理")
    sys.exit(0)
rc = int(cfg["retain_count"]); rd = int(cfg["retain_days"]); mk = int(cfg["min_keep"])
now = time.time()
# 双重策略：保留最近 rc 份 且 保留 rd 天内
to_keep = set()
# 保留"最近"rc 份（backups 升序 → 取尾部 rc 份）
to_keep |= set(backups[-rc:]) if rc > 0 else set()
for b in backups:
    try:
        if (now - os.path.getmtime(b)) / 86400.0 <= rd:
            to_keep.add(b)
    except Exception:
        pass
# 安全下限
to_keep |= set(backups[-mk:]) if len(backups) >= mk else set(backups)
to_del = [b for b in backups if b not in to_keep]
print("备份总数 %d, 保留 %d, 待清理 %d" % (len(backups), len(to_keep), len(to_del)))
for b in to_del:
    print("  删除 " + os.path.basename(b))
    shutil.rmtree(b, ignore_errors=True)
# 清理后剩余份数是否满足恢复需求
remaining = sorted(glob.glob(os.path.join(bd, "mogo-backup-*")))
print("清理后剩余 %d 份 (需求下限 %d 份 / %d 天)" % (len(remaining), rc, rd))
# 仅当本次清理导致剩余不足时才算 FAIL；若清理前本来就不足，属存量不足，提示但不判失败
if to_del and len(remaining) < rc:
    print("FAIL 清理后剩余份数不足 retain_count，保留策略不满足 FR-036")
    sys.exit(1)
print("OK 保留策略满足 FR-036")' "${cfg}" "${ROOT_DIR}"
}

mogo_backup_schedule_run() {
  local cfg; cfg="$(mogo_backup_schedule_config)"
  local cmd; cmd="$(printf '%s' "${cfg}" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["backup_command"])')"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local log="/tmp/mogo-backup-run-${ts}.log"
  if ! (cd "${ROOT_DIR}" && eval "${cmd}") >"${log}" 2>&1; then
    # 失败：结构化错误 + 告警（FR-034/FR-070）
    local detail
    detail="$(python3 -c '
import json, sys
err = open(sys.argv[1]).read().strip()[-400:]
print(json.dumps({"command": sys.argv[2], "error": err}, ensure_ascii=False))' "${log}" "${cmd}")"
    mogo_notify "critical" "mogo 定时备份失败" "${detail}"
    printf '%s\n' "${detail}" >&2
    return 1
  fi
  cat "${log}"
  mogo_backup_schedule_prune >/dev/null 2>&1 || true
  return 0
}

# 独立执行（cron/systemd 调用）
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    cron-run) mogo_backup_schedule_run ;;
    *) printf '用法: backup-schedule.sh cron-run\n' >&2; exit 2 ;;
  esac
fi
