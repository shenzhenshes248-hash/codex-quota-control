#!/usr/bin/env bash
# Execute only after the deployment change list has been approved.
set -euo pipefail
[[ $EUID -eq 0 ]] || exit 1
DOMAIN=${1:?需要提供已解析的域名}
[[ "$DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && "$DOMAIN" == *.* ]] || exit 1
[[ $(uname -m) == x86_64 ]] || { echo '此安装文件针对已检查的 x86_64 VPS'; exit 1; }
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ -f /var/lib/codex-quota-control/control/installed.json ]] || { echo '请先安装 API'; exit 1; }
if ss -H -lnt '( sport = :80 or sport = :8443 )' | grep -q .; then
  echo '80 或 8443 已被占用，未修改现有服务'; exit 1
fi
if getent passwd codexquota-proxy >/dev/null; then
  echo '专用代理用户已存在，未覆盖现有部署'; exit 1
fi
install -d -m 0755 /usr/local/lib/codex-quota-control /etc/codex-quota-proxy
python3 - /usr/local/lib/codex-quota-control/caddy <<'PY'
import sys, urllib.request
urllib.request.urlretrieve('https://caddyserver.com/api/download?os=linux&arch=amd64', sys.argv[1])
PY
chmod 0755 /usr/local/lib/codex-quota-control/caddy
chown root:root /usr/local/lib/codex-quota-control/caddy
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin codexquota-proxy
install -d -o codexquota-proxy -g codexquota-proxy -m 0700 /var/lib/codex-quota-control/https
python3 - "$SOURCE/deploy/Caddyfile.example" "$DOMAIN" <<'PY'
import pathlib, sys
text=pathlib.Path(sys.argv[1]).read_text().replace('api.example.com', sys.argv[2])
pathlib.Path('/etc/codex-quota-proxy/Caddyfile').write_text(text)
PY
chmod 0644 /etc/codex-quota-proxy/Caddyfile
/usr/local/lib/codex-quota-control/caddy validate --config /etc/codex-quota-proxy/Caddyfile --adapter caddyfile
install -m 0644 "$SOURCE/deploy/systemd/codex-quota-control-https.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now codex-quota-control-https.service
echo "HTTPS 管理入口：https://$DOMAIN:8443；80 仅用于证书验证，443 未占用。"
