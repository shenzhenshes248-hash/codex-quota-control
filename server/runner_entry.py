import sys
sys.path.insert(0, "/opt/codex-quota-control/server")
from quota_control.common import read_json
from quota_control.runner import CONFIG, run
raise SystemExit(run(sys.argv[1], read_json(CONFIG)))
