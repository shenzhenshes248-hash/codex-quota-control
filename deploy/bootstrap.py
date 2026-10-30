#!/usr/bin/env python3
"""Prepare a fresh VPS, or reuse its existing trigger without replacing it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path("/")
SOURCE = Path(__file__).resolve().parent.parent
HOME = "/home/codexkeeper"
WORK = HOME + "/codexkeeper-run"
SCRIPT = WORK + "/quota_trigger.py"
BASE = "/var/lib/codex-quota-control/control"
MARKER = BASE + "/bootstrap.json"
UNITS = ("codex-quota-trigger.service", "codex-quota-trigger.timer")
CLI_NAME = "codex-x86_64-unknown-linux-musl"
CLI_URL = "https://github.com/openai/codex/releases/download/rust-v0.166.0/" + CLI_NAME + ".tar.gz"
CLI_SHA256 = "a0bf572d2f93f056c6712a6da348e96078dc84f3885fd7be67807ef389cb3978"


def path(name):
    return ROOT / name.lstrip("/")


def run(*args, **options):
    return subprocess.run(list(args), check=options.pop("check", True), **options)


def user():
    import pwd
    try:
        account = pwd.getpwnam("codexkeeper")
    except KeyError:
        return None
    if account.pw_uid == 0 or account.pw_dir != HOME:
        raise RuntimeError("已有 codexkeeper 账户的 UID/主目录不符合要求，未修改该账户")
    return account


def user_command(*args):
    return ["runuser", "-u", "codexkeeper", "--", "env", "-i", "HOME=" + HOME,
            "PATH=" + HOME + "/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG=C.UTF-8", "CODEX_NON_INTERACTIVE=1", *args]


def dependencies():
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python 3.10+，请使用 Debian 12+ 或 Ubuntu 22.04+ 的 VPS")
    if not path("/run/systemd/system").is_dir():
        raise RuntimeError("此安装器需要使用 systemd 的 Linux VPS")
    commands = ("sudo", "visudo", "ss", "runuser", "timeout", "curl")
    venv_ok = subprocess.run([sys.executable, "-c", "import venv, ensurepip"],
                             capture_output=True).returncode == 0
    if any(shutil.which(name) is None for name in commands) or not venv_ok:
        if not shutil.which("apt-get"):
            raise RuntimeError("缺少依赖且没有 apt-get；当前自动初始化支持 Debian/Ubuntu")
        print("正在安装 Python venv、sudo 等必要依赖……", flush=True)
        run("apt-get", "update")
        run("apt-get", "install", "-y", "--no-install-recommends", "python3", "python3-venv", "ca-certificates",
            "curl", "sudo", "iproute2", "util-linux", "coreutils")


def provision():
    originals = [path(SCRIPT), *(path("/etc/systemd/system/" + name) for name in UNITS)]
    present = [item.is_file() for item in originals]
    owned = path(MARKER).is_file() and json.loads(path(MARKER).read_text()).get("created_trigger") is True
    if all(present):
        if user() is None:
            raise RuntimeError("发现原触发文件，但缺少其 codexkeeper 账户，未覆盖原文件")
        print("复用已有触发脚本、定时计划及 Codex 登录。", flush=True)
        if owned:
            run("systemctl", "daemon-reload")
        return
    if any(present) and not owned:
        raise RuntimeError("发现不完整的原触发环境，未覆盖现有文件；请先核对原脚本和 service/timer")
    account = user()
    path(BASE).mkdir(parents=True, exist_ok=True)
    if not owned:
        marker = path(MARKER)
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps({"created_trigger": True}), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(marker)
    if account is None:
        run("useradd", "--system", "--user-group", "--create-home", "--home-dir", HOME,
            "--shell", "/usr/sbin/nologin", "codexkeeper")
    path(WORK).mkdir(parents=True, exist_ok=True)
    run("chown", "codexkeeper:codexkeeper", str(path(HOME)), str(path(WORK)))
    pairs = [(SOURCE / "server/legacy/quota_trigger.py", path(SCRIPT))]
    pairs += [(SOURCE / "deploy/systemd" / name, path("/etc/systemd/system/" + name)) for name in UNITS]
    for source, target in pairs:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".quota-install")
            shutil.copyfile(source, temporary)
            temporary.chmod(0o700 if target == path(SCRIPT) else 0o644)
            temporary.replace(target)
    run("chown", "codexkeeper:codexkeeper", str(path(SCRIPT)))
    run("systemctl", "daemon-reload")
    print("新触发环境已准备，默认时间为北京时间 08:00、13:00、18:00，计划暂未启用。", flush=True)


def install_cli():
    path(BASE).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-download-", dir=path(BASE)) as directory:
        archive = Path(directory) / "codex.tar.gz"
        run("curl", "--fail", "--location", "--show-error", CLI_URL, "--output", str(archive))
        digest = hashlib.sha256()
        with archive.open("rb") as downloaded:
            while chunk := downloaded.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != CLI_SHA256:
            raise RuntimeError("Codex 官方下载文件校验不一致，未安装该文件")
        binary = path(HOME + "/.local/bin/codex")
        binary.parent.mkdir(parents=True, exist_ok=True)
        run("chown", "codexkeeper:codexkeeper", str(binary.parent.parent), str(binary.parent))
        with tarfile.open(archive, "r:gz") as bundle:
            member = bundle.getmember(CLI_NAME)
            if not member.isfile():
                raise RuntimeError("Codex 发布包内容不正确")
            with tempfile.NamedTemporaryFile(prefix=".codex-install-", dir=binary.parent, delete=False) as output:
                temporary = Path(output.name)
                try:
                    with bundle.extractfile(member) as content:
                        shutil.copyfileobj(content, output)
                except Exception:
                    output.close()
                    temporary.unlink(missing_ok=True)
                    raise
        try:
            temporary.chmod(0o755)
            run("chown", "codexkeeper:codexkeeper", str(temporary))
            temporary.replace(binary)
        finally:
            temporary.unlink(missing_ok=True)


def authorize():
    exists = run(*user_command("sh", "-c", "command -v codex"),
                 cwd=str(path(WORK)), capture_output=True, check=False).returncode == 0
    if not exists:
        print("正在为专用账户安装官方 Codex CLI 0.166.0（GitHub 发布包）……", flush=True)
        install_cli()
    logged_in = run(*user_command("codex", "login", "status"),
                    cwd=str(path(WORK)), capture_output=True, check=False).returncode == 0
    if not logged_in:
        print("请用你自己的 ChatGPT/Codex 账号完成下面的官方设备码授权。", flush=True)
        print("在手机/电脑浏览器打开终端显示的链接并输入一次性代码；无需提供 API Key 或把密码发给任何人。", flush=True)
        print("若设备码登录未启用，请先在 ChatGPT 设置→安全中启用。登录中断后可重跑同一安装命令。", flush=True)
        run(*user_command("codex", "login", "--device-auth"), cwd=str(path(WORK)))
    print("正在检查账号额度接口；本检查不会发送 Codex 触发请求……", flush=True)
    path(BASE).mkdir(parents=True, exist_ok=True)
    log = path(BASE + "/login-check.private.log")
    with log.open("w", encoding="utf-8") as output:
        log.chmod(0o600)
        result = run("timeout", "--kill-after=5", "45", *user_command(
            "python3", SCRIPT, "--dry-run"), cwd=str(path(WORK)), stdout=output, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError("账号额度检查未通过，未启动新计划。需要 ChatGPT 登录及 Codex 使用权限；"
                           "API Key 不能代替该账号额度。root 可查看 " + str(log) + "，请勿公开其中的原始输出")
    log.unlink()
    print("账号额度检查通过。", flush=True)


def main():
    parser = argparse.ArgumentParser(description="初始化新 VPS 并引导个人 Codex 登录；复用已有环境")
    parser.add_argument("--dependencies-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.exit(1, "请在 Linux VPS 上以 root 或 sudo 运行\n")
    try:
        if args.dependencies_only:
            dependencies()
        else:
            provision()
            authorize()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, "初始化未完成：" + str(error) + "\n")


if __name__ == "__main__":
    main()
