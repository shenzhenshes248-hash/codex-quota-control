#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || exit 1
STATE=/var/lib/codex-quota-control
[[ -f "$STATE/control/installed.json" ]] || { echo '未找到本项目安装记录'; exit 1; }
for unit in codex-quota-trigger.service codex-quota-control-manual.service; do
  phase=$(systemctl show "$unit" -p ActiveState --value 2>/dev/null || true)
  [[ -z "$phase" || "$phase" == inactive || "$phase" == failed ]] || {
    echo '有任务正在执行，等待完成后再回滚'; exit 1;
  }
done
systemctl disable --now codex-quota-control-api.service 2>/dev/null || true
if systemctl list-unit-files codex-quota-control-https.service --no-legend | grep -q codex-quota-control-https; then
  systemctl disable --now codex-quota-control-https.service
fi
systemctl stop codex-quota-trigger.timer
rm -f -- /etc/systemd/system/codex-quota-trigger.service.d/90-quota-control-runner.conf
rm -f -- /etc/systemd/system/codex-quota-trigger.timer.d/90-quota-control.conf
rm -f -- /etc/sudoers.d/codex-quota-control
systemctl daemon-reload
python3 - "$STATE/control/installed.json" <<'PY'
import json, subprocess, sys
state=json.load(open(sys.argv[1]))
unit='codex-quota-trigger.timer'
subprocess.run(['systemctl', 'enable' if state['timer_enabled'] else 'disable', unit], check=True)
subprocess.run(['systemctl', 'start' if state['timer_active'] else 'stop', unit], check=True)
PY
echo '已恢复安装前的原服务入口及时间表/启停状态。管理 Token、日志和原有凭据均保留。'
