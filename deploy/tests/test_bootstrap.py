import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[2]
        directory = workspace / ".tools/bootstrap-tests"
        directory.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="bootstrap-", dir=directory)
        root = Path(self.temporary.name).resolve()
        assert root.is_relative_to(workspace.resolve())
        self.addCleanup(self.temporary.cleanup)
        self.root_patch = patch.object(bootstrap, "ROOT", root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.commands = patch.object(bootstrap, "run", return_value=subprocess.CompletedProcess([], 0))
        self.run = self.commands.start()
        self.addCleanup(self.commands.stop)
        self.accounts = patch.object(bootstrap, "user", return_value=None)
        self.account = self.accounts.start()
        self.addCleanup(self.accounts.stop)
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def test_fresh_host_gets_original_script_and_paused_timer(self):
        bootstrap.provision()
        self.assertEqual((bootstrap.SOURCE / "server/legacy/quota_trigger.py").read_bytes(),
                         bootstrap.path(bootstrap.SCRIPT).read_bytes())
        self.assertTrue(json.loads(bootstrap.path(bootstrap.MARKER).read_text())["created_trigger"])
        for unit in bootstrap.UNITS:
            self.assertTrue(bootstrap.path("/etc/systemd/system/" + unit).is_file())
        self.assertTrue(any(call.args[0] == "useradd" for call in self.run.call_args_list))
        self.assertFalse(any("start" in call.args or "enable" in call.args for call in self.run.call_args_list))
        self.run.reset_mock()
        self.account.return_value = object()
        bootstrap.provision()
        self.run.assert_called_once_with("systemctl", "daemon-reload")

    def test_existing_environment_is_reused_without_overwriting_files(self):
        self.account.return_value = object()
        targets = [bootstrap.path(bootstrap.SCRIPT), *(bootstrap.path("/etc/systemd/system/" + unit)
                                                       for unit in bootstrap.UNITS)]
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("existing content")
        bootstrap.provision()
        self.assertTrue(all(target.read_text() == "existing content" for target in targets))
        self.assertFalse(bootstrap.path(bootstrap.MARKER).exists())
        self.run.assert_not_called()

    def test_partial_original_environment_is_not_replaced(self):
        target = bootstrap.path(bootstrap.SCRIPT)
        target.parent.mkdir(parents=True)
        target.write_text("existing script")
        with self.assertRaisesRegex(RuntimeError, "不完整"):
            bootstrap.provision()
        self.assertEqual("existing script", target.read_text())
        self.run.assert_not_called()

    def test_missing_cli_and_login_use_official_user_install_and_device_auth(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            member = tarfile.TarInfo(bootstrap.CLI_NAME)
            member.size = 7
            bundle.addfile(member, io.BytesIO(b"CLItest"))
        raw = archive.getvalue()
        def run(*args, **options):
            if args[0] == "curl":
                Path(args[-1]).write_bytes(raw)
            code = 1 if args[-1] == "command -v codex" or args[-3:] == ("codex", "login", "status") else 0
            return subprocess.CompletedProcess(args, code)
        self.run.side_effect = run
        with patch.object(bootstrap, "CLI_SHA256", hashlib.sha256(raw).hexdigest()):
            bootstrap.authorize()
        calls = self.run.call_args_list
        self.assertEqual(b"CLItest", bootstrap.path(bootstrap.HOME + "/.local/bin/codex").read_bytes())
        self.assertTrue(any(call.args[-3:] == ("codex", "login", "--device-auth") for call in calls))
        self.assertTrue(any(call.args[0] == "timeout" and call.args[-1] == "--dry-run" for call in calls))
        self.assertFalse(bootstrap.path(bootstrap.BASE + "/login-check.private.log").exists())

    def test_unavailable_quota_never_reports_success(self):
        self.run.side_effect = lambda *args, **options: subprocess.CompletedProcess(args, 7 if args[0] == "timeout" else 0)
        with self.assertRaisesRegex(RuntimeError, "账号额度检查未通过"):
            bootstrap.authorize()
        self.assertNotIn("账号额度检查通过", self.output.getvalue())
        self.assertTrue(bootstrap.path(bootstrap.BASE + "/login-check.private.log").is_file())


if __name__ == "__main__":
    unittest.main()
