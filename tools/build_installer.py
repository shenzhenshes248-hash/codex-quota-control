"""Build a single shell installer with the server bundle embedded; no credentials."""
import base64
from pathlib import Path

root = Path(__file__).resolve().parent.parent
bundle = (root / "dist/codex-quota-control-server.tar.gz").read_bytes()
header = r'''#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == --help || $# -ne 1 ]]; then
  echo '用法：sudo bash codex-quota-control-install.sh 你的域名'
  echo '已有 Codex 触发脚本及登录后，一条命令安装 API、HTTPS 并验证连接。'
  [[ ${1:-} == --help ]] && exit 0 || exit 2
fi
[[ $EUID -eq 0 ]] || { echo '请使用 root 或 sudo 运行'; exit 1; }
[[ $(uname -s) == Linux ]] || { echo '此安装包仅用于 Linux VPS'; exit 1; }
command -v python3 >/dev/null || { echo '需要 Python 3'; exit 1; }
umask 077
INSTALL_TEMP=$(mktemp -d /tmp/codex-quota-install.XXXXXXXX)
trap 'rm -rf -- "$INSTALL_TEMP"' EXIT
python3 - "${BASH_SOURCE[0]}" "$INSTALL_TEMP" <<'PY'
import base64, io, pathlib, sys, tarfile
source=pathlib.Path(sys.argv[1]).read_bytes()
data=base64.b64decode(source.split(b'\n__CODEX_INSTALL_PAYLOAD__\n',1)[1])
target=pathlib.Path(sys.argv[2]).resolve()
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as bundle:
    for member in bundle.getmembers():
        if not member.isfile() or not (target/member.name).resolve().is_relative_to(target):
            raise SystemExit('安装包内容不正确')
    bundle.extractall(target)
PY
bash "$INSTALL_TEMP/codex-quota-control/deploy/setup.sh" "$@"
exit 0
__CODEX_INSTALL_PAYLOAD__
'''
encoded = base64.b64encode(bundle).decode("ascii")
output = root / "dist/codex-quota-control-install.sh"
output.write_text(header + "\n".join(encoded[i:i+76] for i in range(0,len(encoded),76)) + "\n", encoding="utf-8", newline="\n")
print(output.name, output.stat().st_size)
