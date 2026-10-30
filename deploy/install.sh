#!/usr/bin/env bash
# Run only after the owner has approved the documented production change list.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo '需要 root 运行安装脚本'; exit 1; }
umask 022
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TARGET=/opt/codex-quota-control
CONFIG=/etc/codex-quota-control
STATE=/var/lib/codex-quota-control
SERVICE=codex-quota-trigger.service
TIMER=codex-quota-trigger.timer

getent passwd codexkeeper >/dev/null || { echo '缺少触发运行账户，请使用 deploy/setup.sh 域名或公网IP 完成初始化和登录'; exit 1; }
[[ $(id -u codexkeeper) != 0 ]] || exit 1
[[ -f /home/codexkeeper/codexkeeper-run/quota_trigger.py ]] || exit 1
[[ $(systemctl show "$SERVICE" -p User --value) == codexkeeper ]] || exit 1
[[ $(systemctl show "$SERVICE" -p ActiveState --value) == inactive ]] || {
  echo '原任务仍在执行，请等待完成后再安装'; exit 1;
}
[[ ! -e "$STATE/control/installed.json" ]] || { echo '已经安装，请先按回滚说明处理，未覆盖现有部署'; exit 1; }

# Prepare dependencies before changing any running service.
install -d -m 0755 "$TARGET" "$TARGET/server"
cp -R -- "$SOURCE/server/quota_control" "$TARGET/server/"
install -m 0644 "$SOURCE/server/helper_entry.py" "$SOURCE/server/runner_entry.py" "$TARGET/server/"
install -m 0644 "$SOURCE/server/requirements.txt" "$TARGET/server/requirements.txt"
python3 -m venv --without-pip "$TARGET/venv"
python3 - "$TARGET/get-pip.py" <<'PY'
import sys, urllib.request
urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', sys.argv[1])
PY
"$TARGET/venv/bin/python" "$TARGET/get-pip.py" --disable-pip-version-check
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/server/requirements.txt"
chown -R root:root "$TARGET/server"
chmod -R u=rwX,go=rX "$TARGET/server"
if getent passwd codexquota >/dev/null; then
  echo 'codexquota 用户已存在，停止安装以免影响其他用途'; exit 1
fi
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin codexquota
install -d -o root -g root -m 0755 "$STATE"
install -d -o root -g codexkeeper -m 0750 "$CONFIG" "$STATE/control"
install -d -o codexkeeper -g codexkeeper -m 0700 "$STATE/runtime"
install -d -m 0755 /etc/systemd/system/codex-quota-trigger.service.d /etc/systemd/system/codex-quota-trigger.timer.d
[[ ! -e /etc/systemd/system/codex-quota-trigger.service.d/90-quota-control-runner.conf ]] || exit 1
[[ ! -e /etc/systemd/system/codex-quota-trigger.timer.d/90-quota-control.conf ]] || exit 1
install -m 0640 -o root -g codexkeeper "$SOURCE/deploy/host.example.json" "$CONFIG/host.json"
if [[ ! -e "$CONFIG/management-token" ]]; then
  (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$CONFIG/management-token")
fi
python3 - "$STATE/control/installed.json" <<'PY'
import json, pathlib, subprocess, sys
def value(prop):
    return subprocess.check_output(['systemctl', 'show', 'codex-quota-trigger.timer', '-p', prop, '--value'], text=True).strip()
bootstrap=pathlib.Path(sys.argv[1]).with_name('bootstrap.json')
pathlib.Path(sys.argv[1]).write_text(json.dumps({'timer_enabled': value('UnitFileState') == 'enabled',
    'timer_active': value('ActiveState') == 'active',
    'fresh_trigger': bootstrap.is_file() and json.loads(bootstrap.read_text()).get('created_trigger') is True}))
PY
chmod 0600 "$STATE/control/installed.json"
trap 'echo "安装未完成，尝试恢复原服务入口"; bash "$SOURCE/deploy/rollback.sh" || true' ERR
systemctl stop "$TIMER"
[[ $(systemctl show "$SERVICE" -p ActiveState --value) == inactive ]] || {
  echo '原任务刚刚开始执行，安装中止'; false;
}
install -m 0755 -o root -g root "$SOURCE/deploy/codex-quota-helper" /usr/local/sbin/codex-quota-helper
visudo -cf "$SOURCE/deploy/sudoers"
install -m 0440 -o root -g root "$SOURCE/deploy/sudoers" /etc/sudoers.d/codex-quota-control
install -m 0644 "$SOURCE/deploy/systemd/codex-quota-control-api.service" /etc/systemd/system/
install -m 0644 "$SOURCE/deploy/systemd/codex-quota-control-manual.service" /etc/systemd/system/
install -m 0644 "$SOURCE/deploy/systemd/90-quota-control-runner.conf" /etc/systemd/system/codex-quota-trigger.service.d/
systemctl daemon-reload
systemctl enable --now codex-quota-control-api.service
python3 - "$STATE/control/installed.json" <<'PY'
import json, subprocess, sys
state=json.load(open(sys.argv[1]))
if state['timer_active']:
    subprocess.run(['systemctl', 'start', 'codex-quota-trigger.timer'], check=True)
PY
trap - ERR
echo 'API 已在 127.0.0.1:8787 启动，原脚本、时间表及 Codex 凭据未改动。'
echo '尚需部署 8443 HTTPS 入口；未占用 443，未触发 Codex 请求。'
