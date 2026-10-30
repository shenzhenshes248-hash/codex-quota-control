import json
import sys
import threading
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from quota_control.api import create_app
from quota_control.common import ControlError, file_lock, validate_schedule
from quota_control.controller import Controller, TIMER, MANUAL, parse_schedule, render_schedule, safe_quota
from quota_control.helper import dispatch
from quota_control.runner import parse_output, run
from quota_control.store import Store

SNAPSHOT = "[2026-10-30 13:00:00] state=idle; 94% left; reset=2026-10-30 18:00:00"
SUCCESS = SNAPSHOT + "\nNo active 5-hour window. Starting one now...\nOK\n"
SKIP = SNAPSHOT.replace("state=idle", "state=active") + "\nActive 5-hour window already running; no trigger needed.\n"


class FakeSystemd:
    """Isolated systemd contract fixture, never connects to the real server."""
    def __init__(self, dropin):
        self.dropin = dropin
        self.enabled = True
        self.active = True
        self.fail_reload = False
        self.base = ["08:00", "13:00", "18:00"]

    def run(self, *args):
        if args[0] == "daemon-reload" and self.fail_reload:
            self.fail_reload = False
            raise ControlError("fixture reload failure")
        if args[0] == "stop": self.active = False
        if args[0] == "start": self.active = True
        if args[0] == "enable": self.enabled = True
        if args[0] == "disable": self.enabled = False
        return ""

    def show(self, unit):
        if unit != TIMER:
            return {"LoadState": "loaded", "ActiveState": "inactive"}
        times = self.base
        if self.dropin.exists():
            import re
            times = re.findall(r"OnCalendar=\*-\*-\* (\d\d:\d\d):00", self.dropin.read_text())
        return {"LoadState": "loaded", "ActiveState": "active" if self.active else "inactive",
                "UnitFileState": "enabled" if self.enabled else "disabled",
                "TimersCalendar": "\n".join("{ OnCalendar=*-*-* " + t +
                    ":00 Asia/Shanghai ; next_elapse=Sat 2026-10-31 00:00:00 UTC }" for t in times),
                "NextElapseUSecRealtime": "Sat 2026-10-31 00:00:00 UTC"}


@pytest.fixture
def control(tmp_path):
    dropin = tmp_path / "timer.d" / "90-quota-control.conf"
    dropin.parent.mkdir()
    (tmp_path / "state" / "control").mkdir(parents=True)
    (tmp_path / "state" / "runtime").mkdir()
    systemd = FakeSystemd(dropin)
    return Controller(systemd, dropin, tmp_path / "state")


def test_schedule_add_replace_multiple_delete_pause_resume(control):
    save = control.set_schedules
    assert save({"enabled": True, "times": ["07:00"]})["times"] == ["07:00"]
    assert save({"enabled": True, "times": ["07:30"]})["times"] == ["07:30"]
    assert "07:00:00" not in control.dropin.read_text()
    assert save({"enabled": True, "times": ["18:45", "07:30", "12:15"]})["times"] == ["07:30", "12:15", "18:45"]
    assert save({"enabled": True, "times": ["18:45", "07:30"]})["times"] == ["07:30", "18:45"]
    paused = save({"enabled": False, "times": ["18:45", "07:30"]})
    assert not paused["enabled"] and not paused["boot_enabled"] and paused["next_run_at"] is None
    resumed = save({"enabled": True, "times": ["07:30", "18:45"]})
    assert resumed["enabled"] and resumed["boot_enabled"]
    assert "Asia/Shanghai" in control.dropin.read_text()


@pytest.mark.parametrize("data", [
    {"enabled": True, "times": ["7:00"]}, {"enabled": True, "times": ["24:00"]},
    {"enabled": True, "times": ["07:60"]}, {"enabled": True, "times": ["07:00", "07:00"]},
    {"enabled": True, "times": []}, {"enabled": "false", "times": []}])
def test_invalid_schedule(data):
    with pytest.raises(ControlError): validate_schedule(data)


def test_delete_last_time_pauses_and_persists(control):
    result = control.set_schedules({"enabled": False, "times": []})
    assert result["times"] == [] and not result["enabled"]
    assert "OnActiveSec=infinity" in control.dropin.read_text()
    reopened = Controller(control.systemd, control.dropin, control.state)
    assert reopened.schedules()["times"] == []


def test_failed_reload_restores_original(control):
    before = control.schedules()
    control.systemd.fail_reload = True
    with pytest.raises(ControlError, match="已恢复原有效计划"):
        control.set_schedules({"enabled": True, "times": ["07:30"]})
    assert control.schedules() == before
    assert not control.dropin.exists()
    control.set_schedules({"enabled": True, "times": ["07:00"]})
    original = control.dropin.read_bytes()
    control.systemd.fail_reload = True
    with pytest.raises(ControlError): control.set_schedules({"enabled": False, "times": ["12:15"]})
    assert control.dropin.read_bytes() == original
    assert control.schedules()["times"] == ["07:00"]


def test_reads_actual_loaded_systemd_plan(control):
    control.systemd.base = ["06:23"]
    assert control.schedules()["times"] == ["06:23"]
    assert control.schedules()["next_run_at"] == "2026-10-31T00:00:00+00:00"


def test_unknown_calendar_is_not_silently_replaced():
    with pytest.raises(ControlError):
        parse_schedule({"LoadState": "loaded", "TimersCalendar":
            "{ OnCalendar=Mon *-*-* 08:00:00 UTC ; next_elapse=n/a }"})


class BridgeFixture:
    def __init__(self): self.calls = []; self.fail = False
    def call(self, operation, payload=None):
        from fastapi import HTTPException
        self.calls.append((operation, payload))
        if self.fail: raise HTTPException(503, "更新失败，已恢复原有效计划")
        return {"enabled": True, "boot_enabled": True, "times": ["07:00"],
                "timezone": "Asia/Shanghai", "next_run_at": None}


@pytest.fixture
def api(tmp_path):
    token = "a" * 48
    token_file = tmp_path / "token"
    token_file.write_text(token)
    bridge = BridgeFixture()
    return TestClient(create_app(bridge, token_file)), bridge, {"Authorization": "Bearer " + token}


def test_unauthorized_requests_cannot_read_modify_or_trigger(api):
    client, bridge, headers = api
    for method, path, body in [("GET", "/api/v1/status", None), ("GET", "/api/v1/logs", None),
                               ("PUT", "/api/v1/schedules", {"enabled": True, "times": ["07:00"]}),
                               ("POST", "/api/v1/trigger", {})]:
        assert client.request(method, path, json=body).status_code == 401
    assert bridge.calls == []
    assert client.get("/api/v1/status", headers=headers).status_code == 200


def test_api_save_verifies_and_does_not_return_success_on_failure(api):
    client, bridge, headers = api
    body = {"enabled": True, "times": ["07:00"]}
    assert client.put("/api/v1/schedules", json=body, headers=headers).json()["times"] == ["07:00"]
    bridge.fail = True
    assert client.put("/api/v1/schedules", json=body, headers=headers).status_code == 503
    assert client.put("/api/v1/schedules", json={**body, "command": "id"}, headers=headers).status_code == 422


def test_helper_rejects_arbitrary_commands(control):
    with pytest.raises(ControlError): dispatch({"operation": "shell", "payload": "id"}, control)
    with pytest.raises(ControlError): dispatch({"operation": "trigger", "command": "id"}, control)


def test_manual_request_already_queued_cannot_be_replaced(control):
    original_show = control.systemd.show
    control.systemd.show = lambda unit: {"ActiveState": "inactive", "Job": "42"} if unit == MANUAL else original_show(unit)
    with pytest.raises(ControlError) as error:
        control.trigger()
    assert error.value.status == 409
    assert not (control.control / "manual-request.json").exists()


def test_original_skip_success_failure_and_unknown_results():
    assert parse_output(SUCCESS, 0)[:2] == ("success", "triggered")
    assert parse_output(SKIP, 0)[:2] == ("skipped", "active_window")
    assert parse_output(SUCCESS, 1)[:2] == ("failed", "script_failed")
    assert parse_output("OK", 0)[:2] == ("failed", "unverified")
    assert parse_output(SKIP, 0)[2]["remaining_percent"] == 94
    assert parse_output(SKIP, 0)[2]["observed_at"].endswith("+08:00")


def test_runner_serializes_real_subprocesses_and_never_returns_raw_output(tmp_path):
    runtime = tmp_path / "runtime"; runtime.mkdir()
    secret = "TEST_ONLY_SECRET_NEVER_RETURN_TO_CLIENT"
    command = [sys.executable, "-u", "-c",
               "import time; print(" + repr(SUCCESS + secret) + "); time.sleep(1)"]
    config = {"command": command, "working_directory": str(tmp_path), "execution_timeout_seconds": 5}
    thread = threading.Thread(target=run, args=("automatic", config, runtime))
    thread.start()
    store = Store(runtime / "executions.sqlite3")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if store.logs(): break
        except Exception: pass
        time.sleep(0.02)
    run("automatic", config, runtime)
    thread.join(timeout=6)
    assert not thread.is_alive()
    records = store.logs()
    assert sorted(x["reason_code"] for x in records) == ["busy", "triggered"]
    assert secret not in json.dumps(records)
    assert safe_quota({"access_token": secret}) is None
