#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SAMPLE_SECONDS = 8

def read_limits():
    p = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    def send(obj):
        p.stdin.write(json.dumps(obj) + "\n")
        p.stdin.flush()

    def wait_for(req_id):
        while True:
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("Codex app-server exited unexpectedly")
            msg = json.loads(line)
            if msg.get("id") == req_id:
                return msg

    send({
        "method": "initialize",
        "id": 1,
        "params": {
            "clientInfo": {
                "name": "codex_quota_keeper",
                "title": "Codex Quota Keeper",
                "version": "0.2.0"
            }
        }
    })
    wait_for(1)
    send({"method": "initialized", "params": {}})
    send({"method": "account/rateLimits/read", "id": 2})

    msg = wait_for(2)
    p.terminate()

    if "error" in msg:
        raise RuntimeError(msg["error"])

    return msg["result"]["rateLimits"]["primary"]

def sample():
    primary = read_limits()
    return {
        "time": time.time(),
        "reset": float(primary["resetsAt"]),
        "used": float(primary["usedPercent"]),
    }

def is_sliding(a, b):
    wall = b["time"] - a["time"]
    shift = b["reset"] - a["reset"]

    # 空闲窗口：resetsAt 会和当前时间一起往后滑
    return wall * 0.5 <= shift <= wall * 1.5

def detect_window():
    a = sample()
    time.sleep(SAMPLE_SECONDS)
    b = sample()

    if is_sliding(a, b):
        return "idle", b

    # 如果两次之间刚好发生窗口切换，再取第三次避免误判
    shift = b["reset"] - a["reset"]
    if shift > SAMPLE_SECONDS * 2:
        time.sleep(SAMPLE_SECONDS)
        c = sample()
        if is_sliding(b, c):
            return "idle", c
        return "active", c

    return "active", b

def trigger():
    cmd = [
        "codex", "exec",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--color", "never",
        "Reply exactly OK. Do not run commands, inspect files, or use tools."
    ]
    return subprocess.run(
        cmd,
        cwd="/home/codexkeeper/codexkeeper-run"
    ).returncode

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--wait-minutes", type=int, default=0)
args = parser.parse_args()

deadline = time.time() + args.wait_minutes * 60

while True:
    state, s = detect_window()

    now = datetime.now(TZ)
    reset = datetime.fromtimestamp(s["reset"], TZ)
    left = 100 - s["used"]

    print(
        f"[{now:%Y-%m-%d %H:%M:%S}] "
        f"state={state}; {left:.0f}% left; "
        f"reset={reset:%Y-%m-%d %H:%M:%S}"
    )

    if state == "idle":
        if args.dry_run:
            print("DRY RUN: no active 5-hour window; would trigger Codex now.")
            raise SystemExit(0)

        print("No active 5-hour window. Starting one now...")
        raise SystemExit(trigger())

    # 有活动窗口。如果它会在本次 10 分钟等待期内结束，就继续等。
    if s["reset"] <= deadline:
        print("Active window is near reset; waiting...")
        time.sleep(15)
        continue

    print("Active 5-hour window already running; no trigger needed.")
    raise SystemExit(0)
