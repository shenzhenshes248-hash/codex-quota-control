#!/usr/bin/env bash
# One entry point for the existing API and HTTPS installers.
set -euo pipefail
if [[ ${1:-} == --help || $# -ne 1 ]]; then
  echo '用法：sudo bash codex-quota-control-install.sh 域名或公网IP'
  echo '域名方式：sudo bash codex-quota-control-install.sh api.example.com'
  echo '无域名方式：sudo bash codex-quota-control-install.sh 你的公网IP'
  echo '前提：已有 codexkeeper 用户、quota_trigger.py 和有效的 Codex 登录。'
  echo '管理接口使用 8443；80 用于证书验证，443 保留。'
  [[ ${1:-} == --help ]] && exit 0 || exit 2
fi
[[ $EUID -eq 0 ]] || { echo '请使用 root 或 sudo 运行'; exit 1; }
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3 systemctl ss visudo; do
  command -v "$tool" >/dev/null || { echo "缺少必要命令：$tool"; exit 1; }
done
HOST=$(python3 "$SOURCE/deploy/https_config.py" "$1")
ENDPOINT=$(python3 "$SOURCE/deploy/https_config.py" "$HOST" --url)
if [[ -f /etc/systemd/system/codex-quota-control-https.service ]]; then
  if ! grep -Fxq "$ENDPOINT {" /etc/codex-quota-proxy/Caddyfile; then
    echo '已有 HTTPS 入口与此次地址不同，未修改部署；请使用原入口地址。'; exit 1
  fi
fi
if [[ ! -f /etc/systemd/system/codex-quota-control-https.service ]]; then
  if ss -H -lnt '( sport = :80 or sport = :8443 )' | grep -q .; then
    echo '80 或 8443 已被其他服务占用，停止安装'; exit 1
  fi
fi
if [[ -f /var/lib/codex-quota-control/control/installed.json &&
      -f /etc/systemd/system/codex-quota-control-api.service ]]; then
  echo 'API 已安装，保留现有 Token 和时间计划。'
else
  bash "$SOURCE/deploy/install.sh"
fi
if [[ -f /etc/systemd/system/codex-quota-control-https.service ]]; then
  echo 'HTTPS 已安装，保留现有配置。'
else
  bash "$SOURCE/deploy/install-https.sh" "$HOST"
fi
python3 - "$ENDPOINT" <<'PY'
import json, pathlib, sys, time, urllib.error, urllib.request
url=sys.argv[1]+'/api/v1/status'
token=pathlib.Path('/etc/codex-quota-control/management-token').read_text().strip()
for attempt in range(20):
    try:
        request=urllib.request.Request(url, headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(request, timeout=8) as response:
            data=json.load(response)
            assert response.status == 200 and data['schedules']['timezone'] == 'Asia/Shanghai'
        print('部署与 HTTPS 连接验证成功。')
        break
    except (OSError, ValueError, AssertionError, KeyError):
        if attempt == 19:
            raise SystemExit('连接验证未通过，请检查 API/HTTPS 服务、系统时间、80/8443 端口和域名/IP；未显示安装成功。')
        time.sleep(2)
PY
echo "App 地址：$ENDPOINT"
echo '管理 Token：/etc/codex-quota-control/management-token（仅 root 可读取）'
echo '已有计划和认证信息已保留；没有发起 Codex 触发请求。'
