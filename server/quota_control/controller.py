import datetime as dt
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from .common import ControlError, REASONS, UTC, TZ_NAME, atomic_write, file_lock, now, read_json, validate_schedule
from .store import Store
from .runner import parse_output, SNAPSHOT

TIMER = "codex-quota-trigger.timer"
AUTO = "codex-quota-trigger.service"
MANUAL = "codex-quota-control-manual.service"
STATE = Path("/var/lib/codex-quota-control")
DROPIN = Path("/etc/systemd/system/codex-quota-trigger.timer.d/90-quota-control.conf")


class Systemd:
    def run(self, *args):
        try:
            result = subprocess.run(["/usr/bin/systemctl", *args], capture_output=True,
                                    text=True, timeout=20,
                                    env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "TZ": "UTC"})
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("无法连接 VPS 的 systemd")
        if result.returncode:
            raise ControlError("systemd 操作失败，未确认计划生效")
        return result.stdout.strip()

    def show(self, unit):
        text = self.run("show", unit, "--no-pager", "--property=" +
                        "LoadState,ActiveState,UnitFileState,TimersCalendar,NextElapseUSecRealtime,"
                        "ExecMainStartTimestamp,ExecMainExitTimestamp,ExecMainStatus,Result,Job")
        result = {}
        for line in text.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key] = result[key] + "\n" + value if key in result else value
        return result


def timestamp(value):
    if not value or value in ("n/a", "0"):
        return None
    m = re.fullmatch(r"\w+ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.\d+)? (?:UTC|GMT)", value)
    if not m:
        raise ControlError("无法解析 systemd 返回的真实执行时间")
    return dt.datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).isoformat()


def parse_schedule(properties):
    if properties.get("LoadState") != "loaded":
        raise ControlError("原定时器未正确加载，请检查 VPS 配置")
    expressions = re.findall(r"OnCalendar=(.*?)\s*;\s*next_elapse=", properties.get("TimersCalendar", ""))
    times = []
    for expression in expressions:
        m = re.fullmatch(r"\*-\*-\* (\d\d:\d\d):00 Asia/Shanghai", expression.strip())
        if not m:
            raise ControlError("发现不受支持的现行计划，未对它作出修改")
        times.append(m[1])
    if len(times) != len(set(times)):
        raise ControlError("systemd 中存在重复的计划，请先检查")
    active = properties.get("ActiveState") == "active"
    return {"times": sorted(times), "enabled": active,
            "boot_enabled": properties.get("UnitFileState") == "enabled", "timezone": TZ_NAME,
            "next_run_at": timestamp(properties.get("NextElapseUSecRealtime")) if active else None}


def render_schedule(times):
    body = "[Timer]\nOnCalendar=\n"
    body += "".join("OnCalendar=*-*-* " + t + ":00 Asia/Shanghai\n" for t in times)
    if not times:
        body += "OnActiveSec=infinity\n"
    return body + "AccuracySec=1s\nRandomizedDelaySec=0\nPersistent=false\n"


def safe_quota(data):
    if not isinstance(data, dict):
        return None
    left = data.get("remaining_percent")
    if type(left) not in (int, float) or not 0 <= left <= 100:
        return None
    if data.get("window_state") not in ("active", "idle"):
        return None
    clean = {"remaining_percent": left, "window_state": data["window_state"]}
    for key in ("observed_at", "window_resets_at"):
        try:
            parsed = dt.datetime.fromisoformat(data[key])
            if parsed.tzinfo is None:
                return None
            clean[key] = parsed.isoformat()
        except (ValueError, TypeError, KeyError):
            return None
    return clean


def safe_execution(item, running=True):
    code = item["reason_code"]
    result = item["result"]
    if result == "running" and not running:
        result, code = "failed", "interrupted"
    return {"id": item["id"], "source": item["source"], "started_at": item["started_at"],
            "finished_at": item["finished_at"], "result": result,
            "reason_code": code, "reason": REASONS[code], "quota": safe_quota(item.get("quota"))}


class Controller:
    def __init__(self, systemd=None, dropin=DROPIN, state=STATE):
        self.systemd = systemd or Systemd()
        self.dropin = Path(dropin)
        self.state = Path(state)
        self.control = self.state / "control"
        self.store = Store(self.state / "runtime" / "executions.sqlite3")

    def schedules(self):
        return parse_schedule(self.systemd.show(TIMER))

    def set_schedules(self, data):
        new = validate_schedule(data)
        with file_lock(self.control / "schedule.lock", blocking=True):
            old = self.schedules()
            original = self.dropin.read_bytes() if self.dropin.exists() else None
            try:
                self.systemd.run("stop", TIMER)
                atomic_write(self.dropin, render_schedule(new["times"]), mode=0o644)
                self.systemd.run("daemon-reload")
                self.systemd.run("enable" if new["enabled"] else "disable", TIMER)
                if new["enabled"]:
                    self.systemd.run("start", TIMER)
                actual = self.schedules()
                if (actual["times"] != new["times"] or actual["enabled"] != new["enabled"]
                        or actual["boot_enabled"] != new["enabled"]):
                    raise ControlError("systemd 读回的计划与保存内容不一致")
                return actual
            except Exception:
                try:
                    if original is None:
                        self.dropin.unlink(missing_ok=True)
                    else:
                        atomic_write(self.dropin, original, mode=0o644)
                    self.systemd.run("daemon-reload")
                    self.systemd.run("enable" if old["boot_enabled"] else "disable", TIMER)
                    self.systemd.run("start" if old["enabled"] else "stop", TIMER)
                    restored = self.schedules()
                    if any(restored[k] != old[k] for k in ("times", "enabled", "boot_enabled")):
                        raise RuntimeError("rollback verification failed")
                except Exception:
                    raise ControlError("更新失败，原计划未能确认恢复，请立即检查 VPS")
                raise ControlError("更新失败，已恢复原有效计划")

    def running(self):
        return any(self.unit_busy(self.systemd.show(unit)) for unit in (AUTO, MANUAL))

    @staticmethod
    def unit_busy(properties):
        return (properties.get("ActiveState") in ("active", "activating") or
                properties.get("Job", "").strip() not in ("", "0"))

    def logs(self, limit=50):
        active = self.running()
        records = [safe_execution(x, active) for x in self.store.logs(limit)]
        if not records:
            previous = self.previous_execution()
            if previous:
                records.append(previous)
        return records

    def previous_execution(self):
        """Read the last pre-install execution without guessing its trigger source."""
        properties = self.systemd.show(AUTO)
        try:
            start = timestamp(properties.get("ExecMainStartTimestamp"))
            finish = timestamp(properties.get("ExecMainExitTimestamp"))
            if not start or not finish or finish < start:
                return None
            since = dt.datetime.fromisoformat(start).strftime("%Y-%m-%d %H:%M:%S UTC")
            until = (dt.datetime.fromisoformat(finish) + dt.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S UTC")
            proc = subprocess.run(["/usr/bin/journalctl", "-u", AUTO, "--no-pager", "-o", "json",
                                   "--since", since, "--until", until, "-n", "500"],
                                  capture_output=True, text=True, timeout=10)
            messages = []
            markers = {"No active 5-hour window. Starting one now...",
                       "Active 5-hour window already running; no trigger needed."}
            for line in proc.stdout.splitlines():
                message = json.loads(line).get("MESSAGE", "")
                if isinstance(message, str) and (SNAPSHOT.fullmatch(message) or message in markers):
                    messages.append(message)
            exit_code = int(properties.get("ExecMainStatus", "1"))
            if properties.get("Result") != "success":
                exit_code = 1
            result, code, quota = parse_output("\n".join(messages), exit_code)
            if not quota:
                return None
            return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, AUTO + start)), "source": "legacy",
                    "started_at": start, "finished_at": finish, "result": result,
                    "reason_code": code, "reason": REASONS[code], "quota": quota}
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired, ControlError):
            return None

    def status(self):
        schedule = self.schedules()
        records = self.logs()
        return {"server_time": now(), "schedules": schedule, "running": self.running(),
                "last_execution": records[0] if records else None,
                "quota": next((r["quota"] for r in records if r["quota"]), None)}

    def trigger(self):
        with file_lock(self.control / "manual.lock"):
            if self.unit_busy(self.systemd.show(MANUAL)):
                raise ControlError("已有手动任务正在执行，请查看执行状态", 409)
            ident = str(uuid.uuid4())
            atomic_write(self.control / "manual-request.json",
                         json.dumps({"id": ident, "requested_at": now()}), mode=0o640)
            # The control directory and file group are the existing runner group.
            import grp
            config = read_json("/etc/codex-quota-control/host.json")
            os.chown(self.control / "manual-request.json", 0, grp.getgrnam(config["run_group"]).gr_gid)
            self.systemd.run("start", "--no-block", MANUAL)
            return {"id": ident, "result": "running", "reason": "任务已交给 systemd，等待脚本执行"}

    def execution(self, ident):
        try:
            uuid.UUID(ident)
        except (ValueError, TypeError):
            raise ControlError("执行记录 ID 不正确", 422)
        record = self.store.get(ident)
        if record:
            return safe_execution(record, self.running())
        try:
            pending = read_json(self.control / "manual-request.json")
        except FileNotFoundError:
            pending = {}
        if pending.get("id") == ident:
            active = self.unit_busy(self.systemd.show(MANUAL))
            return {"id": ident, "source": "manual", "started_at": None, "finished_at": None,
                    "result": "running" if active else "failed",
                    "reason_code": "running" if active else "interrupted",
                    "reason": "任务已交给 systemd，等待脚本执行" if active else REASONS["interrupted"],
                    "quota": None}
        raise ControlError("未找到此执行记录", 404)
