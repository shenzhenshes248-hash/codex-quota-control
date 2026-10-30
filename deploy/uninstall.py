#!/usr/bin/env python3
"""Remove management and its fresh trigger, or restore a pre-existing trigger."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path("/")
TIMER = "codex-quota-trigger.timer"
AUTO = "codex-quota-trigger.service"
API = "codex-quota-control-api.service"
HTTPS = "codex-quota-control-https.service"
MANUAL = "codex-quota-control-manual.service"
RECORD = "/var/lib/codex-quota-control/control/installed.json"
FILES = (
    "/etc/systemd/system/codex-quota-trigger.service.d/90-quota-control-runner.conf",
    "/etc/systemd/system/codex-quota-trigger.timer.d/90-quota-control.conf",
    "/etc/sudoers.d/codex-quota-control",
    "/usr/local/sbin/codex-quota-helper",
    *("/etc/systemd/system/" + unit for unit in (API, HTTPS, MANUAL)),
)
DIRECTORIES = (
    "/opt/codex-quota-control",
    "/usr/local/lib/codex-quota-control",
    "/etc/codex-quota-proxy",
    "/etc/codex-quota-control",
    "/var/lib/codex-quota-control",
)


def path(name):
    return ROOT / name.lstrip("/")


def systemctl(*args):
    result = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=30)
    if result.returncode and "LoadState=not-found" not in result.stdout:
        raise RuntimeError("systemd 操作失败：" + " ".join(args))
    return result.stdout.strip()


def show(unit):
    return dict(line.split("=", 1) for line in systemctl(
        "show", unit, "--property=LoadState,ActiveState,Job", "--no-pager"
    ).splitlines() if "=" in line)


def require_idle():
    for unit in (AUTO, MANUAL):
        data = show(unit)
        if data.get("LoadState") == "not-found":
            continue
        if (data.get("ActiveState") not in ("inactive", "failed")
                or data.get("Job", "") not in ("", "0", "[not set]")):
            raise RuntimeError("有触发任务正在执行或排队，请等待完成后再卸载")


def remove(name):
    target = path(name)
    if not target.parent.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("卸载路径超出目标目录")
    if target.is_symlink() or not target.is_dir():
        target.unlink(missing_ok=True)
    else:
        shutil.rmtree(target)


def remove_account(name):
    # These two system accounts were created by the management-layer installer.
    import grp
    import pwd
    try:
        pwd.getpwnam(name)
    except KeyError:
        pass
    else:
        subprocess.run(["userdel", name], check=True, capture_output=True, timeout=20)
    try:
        grp.getgrnam(name)
    except KeyError:
        pass
    else:
        subprocess.run(["groupdel", name], check=True, capture_output=True, timeout=20)


def uninstall():
    record = path(RECORD)
    if not record.is_file():
        raise RuntimeError("未找到本项目安装记录，未删除任何文件")
    state = json.loads(record.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or any(type(state.get(key)) is not bool
                                         for key in ("timer_enabled", "timer_active")):
        raise RuntimeError("安装记录无效，未修改部署")
    require_idle()
    # Stop request/scheduling entry points before checking again for a task that
    # started during the first check. Keep enable flags intact until it is idle.
    previous = {unit: show(unit) for unit in (API, HTTPS, TIMER)}
    loaded = [unit for unit, data in previous.items() if data.get("LoadState") == "loaded"]
    try:
        for unit in loaded:
            systemctl("stop", unit)
        require_idle()
    except Exception:
        for unit in loaded:
            if previous[unit].get("ActiveState") == "active":
                systemctl("start", unit)
        raise
    print("正在卸载管理层并恢复原定时任务……", flush=True)
    for unit in (API, HTTPS):
        if unit in loaded:
            systemctl("disable", unit)
    for name in FILES:
        remove(name)
    fresh = state.get("fresh_trigger") is True
    if fresh:
        systemctl("disable", TIMER)
        for name in ("/etc/systemd/system/" + AUTO, "/etc/systemd/system/" + TIMER,
                     "/home/codexkeeper/codexkeeper-run/quota_trigger.py"):
            remove(name)
    systemctl("daemon-reload")
    if not fresh:
        systemctl("enable" if state["timer_enabled"] else "disable", TIMER)
        systemctl("start" if state["timer_active"] else "stop", TIMER)
    # Remove accounts before erasing the installation record, so a failed
    # account cleanup can be retried without losing the original timer state.
    for account in ("codexquota", "codexquota-proxy"):
        remove_account(account)
    for name in DIRECTORIES:
        remove(name)
    print("卸载完成：管理服务、程序、管理 Token、日志、证书和专用账户已清理。")
    if fresh:
        print("新装时创建的触发脚本和定时任务已删除；Codex CLI、codexkeeper 和 Codex 登录保留。")
    else:
        print("已恢复安装前的原定时计划及启停状态；原脚本、codexkeeper 和 Codex 登录均保留。")


def main():
    parser = argparse.ArgumentParser(description=(
        "卸载管理层及其 Token/日志/证书。已有环境恢复原计划，新初始化环境移除自建触发任务。"
        "保留 Codex CLI、运行账户及登录。"))
    parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.exit(1, "请在目标 Linux VPS 上使用 root 或 sudo python3 运行\n")
    try:
        uninstall()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, "卸载未完成：" + str(error) + "\n")


if __name__ == "__main__":
    main()
