"""Serialize both systemd entry points and interpret the inspected, unchanged script."""
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo
from .common import ControlError, TZ_NAME, atomic_write, file_lock, read_json
from .store import Store

CONFIG = Path("/etc/codex-quota-control/host.json")
BASE = Path("/var/lib/codex-quota-control")
STATE = BASE / "runtime"
SNAPSHOT = re.compile(
    r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] state=(idle|active); "
    r"(-?\d+)% left; reset=(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)$", re.M)


def parse_output(text, exit_code):
    text = text.replace("\r\n", "\n")
    quota = None
    matches = list(SNAPSHOT.finditer(text))
    if matches:
        observed, state, left, reset = matches[-1].groups()
        if 0 <= int(left) <= 100:
            zone = ZoneInfo(TZ_NAME)
            iso = lambda value: dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zone).isoformat()
            quota = {"remaining_percent": int(left), "window_state": state,
                     "observed_at": iso(observed), "window_resets_at": iso(reset)}
    lines = text.splitlines()
    if exit_code != 0:
        return "failed", "script_failed", quota
    if matches and "No active 5-hour window. Starting one now..." in lines:
        return "success", "triggered", quota
    if matches and "Active 5-hour window already running; no trigger needed." in lines:
        return "skipped", "active_window", quota
    return "failed", "unverified", quota


def run(source, config, state_dir=STATE, control_dir=BASE / "control"):
    if source not in ("automatic", "manual"):
        raise ValueError("Invalid trigger source")
    state_dir = Path(state_dir)
    store = Store(state_dir / "executions.sqlite3")
    store.initialize()
    ident = str(uuid.uuid4())
    if source == "manual":
        ident = read_json(Path(control_dir) / "manual-request.json")["id"]
        uuid.UUID(ident)
    try:
        lock = file_lock(state_dir / "trigger.lock")
        lock.__enter__()
    except ControlError:
        store.start(ident, source)
        store.finish(ident, "skipped", "busy")
        return 0
    try:
        store.recover_interrupted()
        store.start(ident, source)
        # Original stdout may contain Codex response details. It is never sent to the API.
        # A temporary file avoids an unbounded stdout PIPE and is removed after interpretation.
        with tempfile.TemporaryFile(dir=state_dir) as output:
            child = subprocess.Popen(config["command"], cwd=config["working_directory"],
                                     stdout=output, stderr=output,
                                     start_new_session=(os.name == "posix"))
            try:
                code = child.wait(timeout=config.get("execution_timeout_seconds", 840))
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
                child.wait()
                store.finish(ident, "failed", "timeout")
                return 1
            output.seek(0)
            raw = output.read(2 * 1024 * 1024)
            result, reason, quota = parse_output(raw.decode("utf-8", "replace"), code)
            if result == "failed":
                atomic_write(state_dir / "last-failure.private.log", raw)
        store.finish(ident, result, reason, quota)
        print(json.dumps({"id": ident, "source": source, "result": result, "reason_code": reason}))
        return 1 if result == "failed" else 0
    except Exception:
        store.finish(ident, "failed", "script_failed")
        return 1
    finally:
        lock.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1], read_json(CONFIG)))
