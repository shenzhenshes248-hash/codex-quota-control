import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uninstall


class UninstallTest(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[2]
        test_directory = workspace / ".tools" / "uninstall-tests"
        test_directory.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="quota-uninstall-", dir=test_directory)
        self.root = Path(self.temporary.name).resolve()
        assert self.root.is_relative_to(workspace.resolve())
        self.root_patch = patch.object(uninstall, "ROOT", self.root)
        self.root_patch.start()
        self.calls = []
        self.busy_checks = 0
        self.becomes_busy = False
        self.busy = False
        self.command_patch = patch.object(uninstall, "systemctl", side_effect=self.systemctl)
        self.command_patch.start()
        self.accounts = patch.object(uninstall, "remove_account")
        self.account_mock = self.accounts.start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        for name in (*uninstall.FILES, uninstall.RECORD,
                     "/opt/codex-quota-control/server/app.py",
                     "/usr/local/lib/codex-quota-control/caddy",
                     "/etc/codex-quota-proxy/Caddyfile",
                     "/etc/codex-quota-control/management-token",
                     "/var/lib/codex-quota-control/runtime/executions.sqlite3"):
            self.write(name, "project data")
        self.write(uninstall.RECORD, json.dumps({"timer_enabled": True, "timer_active": False}))
        self.originals = ("/home/codexkeeper/.codex/auth.json",
                          "/home/codexkeeper/codexkeeper-run/quota_trigger.py",
                          "/etc/systemd/system/codex-quota-trigger.timer",
                          "/etc/systemd/system/codex-quota-trigger.service",
                          "/etc/caddy/Caddyfile", "/etc/xray/config.json")
        for name in self.originals:
            self.write(name, "keep original")

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.accounts.stop()
        self.command_patch.stop()
        self.root_patch.stop()
        assert self.root.name.startswith("quota-uninstall-")
        self.temporary.cleanup()

    def write(self, name, text):
        target = uninstall.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def systemctl(self, *args):
        self.calls.append(args)
        if args[0] == "show":
            if args[1] == uninstall.AUTO:
                self.busy_checks += 1
            busy = args[1] == uninstall.AUTO and (self.busy or (self.becomes_busy and self.busy_checks > 1))
            active = busy or args[1] in (uninstall.API, uninstall.HTTPS, uninstall.TIMER)
            return "LoadState=loaded\nActiveState=" + ("active" if active else "inactive") + "\nJob="
        return ""

    def test_removes_management_layer_and_restores_original_timer(self):
        uninstall.uninstall()
        for name in (*uninstall.FILES, *uninstall.DIRECTORIES):
            self.assertFalse(uninstall.path(name).exists(), name)
        for name in self.originals:
            self.assertEqual("keep original", uninstall.path(name).read_text(encoding="utf-8"))
        self.assertIn(("enable", uninstall.TIMER), self.calls)
        self.assertEqual(("stop", uninstall.TIMER), self.calls[-1])
        self.assertEqual(["codexquota", "codexquota-proxy"],
                         [call.args[0] for call in self.account_mock.call_args_list])

    def test_busy_task_refuses_without_stopping_services(self):
        self.busy = True
        with self.assertRaisesRegex(RuntimeError, "正在执行"):
            uninstall.uninstall()
        self.assertTrue(uninstall.path(uninstall.RECORD).exists())
        self.assertFalse(any(call[0] in ("stop", "disable") for call in self.calls))

    def test_task_starting_during_uninstall_restores_entry_points(self):
        self.becomes_busy = True
        with self.assertRaisesRegex(RuntimeError, "正在执行"):
            uninstall.uninstall()
        self.assertTrue(uninstall.path(uninstall.FILES[0]).exists())
        for unit in (uninstall.API, uninstall.HTTPS, uninstall.TIMER):
            self.assertIn(("start", unit), self.calls)
        self.assertFalse(any(call[0] == "disable" for call in self.calls))

    def test_invalid_install_record_refuses_before_changes(self):
        self.write(uninstall.RECORD, '{"timer_enabled":"true","timer_active":false}')
        with self.assertRaisesRegex(RuntimeError, "安装记录无效"):
            uninstall.uninstall()
        self.assertEqual([], self.calls)
        self.assertTrue(uninstall.path(uninstall.FILES[0]).exists())


if __name__ == "__main__":
    unittest.main()
