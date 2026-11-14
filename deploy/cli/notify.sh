#!/usr/bin/env bash
# 024 T070 (FR-034)：统一告警渠道。
#
# 提供 `mogo_notify <severity> <title> [detail_json]`，供 backup-schedule / 后续
# 备份失败、证书告警等场景复用。输出结构化 JSON（severity/title/detail/timestamp），
# 并按渠道投递：
#   - log         : 追加到 $MOGO_ALERT_LOG（默认 stderr）
#   - webhook     : POST 到 $MOGO_ALERT_WEBHOOK_URL（Content-Type application/json）
#   - alertmanager: POST 到 $MOGO_ALERTMANAGER_URL/api/v2/alerts（复用 deploy/alertmanager/alertmanager.yml 的
#                   p0/p1/p2 分级路由；severity=critical → p0, warning → p1, info → p2）
# 渠道可通过 $MOGO_ALERT_CHANNEL 切换（默认 log）。本脚本只被 source，不单独执行。

# severity: info|warning|critical
mogo_notify() {
  local severity="$1" title="$2" detail="${3:-{}}"
  local payload ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  payload="$(printf '{"severity":"%s","title":"%s","detail":%s,"timestamp":"%s"}' \
    "${severity}" "${title}" "${detail}" "${ts}")"

  # 结构化错误始终打到 stderr（无论渠道）
  printf '[%s] %s %s %s\n' "${ts}" "${severity}" "${title}" "${detail}" >&2

  local channel="${MOGO_ALERT_CHANNEL:-log}"
  case "${channel}" in
    alertmanager)
      # 复用现有告警渠道（FR-034）：POST 到 Alertmanager，按 severity 分级。
      # label 与 alertmanager.yml 的 severity 值对应：critical=p0 / warning=p1 / info=p2
      local am_url="${MOGO_ALERTMANAGER_URL:-http://localhost:9093}"
      local am_label="${severity}"
      case "${severity}" in
        critical) am_label="p0" ;;
        warning) am_label="p1" ;;
        info|*) am_label="p2" ;;
      esac
      local am_payload
      am_payload="$(printf '[{"labels":{"alertname":"%s","severity":"%s","channel":"mogo-notify"},"annotations":{"summary":"%s","detail":"%s"},"generatorURL":""}]'         "${title}" "${am_label}" "${title}" "${detail}")"
      if command -v curl >/dev/null 2>&1; then
        curl -sS -X POST -H 'Content-Type: application/json'           -d "${am_payload}" "${am_url}/api/v2/alerts" >/dev/null || {
            printf '%s\n' "${payload}" >> "${MOGO_ALERT_LOG:-/dev/stderr}"; return 1; }
      else
        printf 'notify: 无 curl，降级到 log\n' >&2
        printf '%s\n' "${payload}" >> "${MOGO_ALERT_LOG:-/dev/stderr}"
        return 1
      fi
      ;;
    webhook)
      if [[ -z "${MOGO_ALERT_WEBHOOK_URL:-}" ]]; then
        printf 'notify: MOGO_ALERT_WEBHOOK_URL 未设置，降级到 log\n' >&2
        printf '%s\n' "${payload}" >> "${MOGO_ALERT_LOG:-/dev/stderr}"
        return 1
      fi
      if command -v curl >/dev/null 2>&1; then
        curl -sS -X POST -H 'Content-Type: application/json' \
          -d "${payload}" "${MOGO_ALERT_WEBHOOK_URL}" >/dev/null || return 1
      elif command -v wget >/dev/null 2>&1; then
        wget -q -O - --header='Content-Type: application/json' \
          --post-data="${payload}" "${MOGO_ALERT_WEBHOOK_URL}" >/dev/null || return 1
      else
        printf 'notify: 无 curl/wget，降级到 log\n' >&2
        printf '%s\n' "${payload}" >> "${MOGO_ALERT_LOG:-/dev/stderr}"
        return 1
      fi
      ;;
    log|*)
      printf '%s\n' "${payload}" >> "${MOGO_ALERT_LOG:-/dev/stderr}"
      ;;
  esac
  return 0
}