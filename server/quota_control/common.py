import contextlib
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

TZ_NAME = "Asia/Shanghai"
UTC = dt.timezone.utc
REASONS = {
    "triggered": "原脚本已完成一次真实 Codex 请求",
    "active_window": "五小时窗口正在运行，原脚本已跳过",
    "busy": "已有触发任务正在执行，本次已跳过",
    "running": "原脚本正在检查额度、等待窗口或执行请求",
    "script_failed": "原脚本执行失败，请在 VPS 查看受保护的服务日志",
    "timeout": "原脚本执行超时，已终止本次任务",
    "unverified": "原脚本输出不完整，无法确认执行结果",
    "interrupted": "任务被中断，执行结果未知，请先检查 VPS 日志",
}


class ControlError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def now():
    return dt.datetime.now(UTC).isoformat()


def validate_schedule(data):
    if not isinstance(data, dict) or set(data) != {"enabled", "times"}:
        raise ControlError("计划只能包含 enabled 和 times", 422)
    enabled, times = data["enabled"], data["times"]
    if type(enabled) is not bool or not isinstance(times, list) or len(times) > 1440:
        raise ControlError("计划格式不正确", 422)
    if any(not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t)
           for t in times):
        raise ControlError("时间须为 24 小时制 HH:mm", 422)
    if len(times) != len(set(times)):
        raise ControlError("触发时间不能重复", 422)
    if enabled and not times:
        raise ControlError("启用计划前请至少添加一个时间", 422)
    return {"enabled": enabled, "times": sorted(times)}


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".quota-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def file_lock(path, blocking=False):
    # Windows support is for local tests; the installed service runs on Linux/flock.
    f = open(path, "a+b")
    try:
        if os.name == "posix":
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        else:
            import msvcrt
            f.seek(0)
            if not f.read(1):
                f.write(b"0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        raise ControlError("已有任务正在执行，请稍后刷新", 409)
    try:
        yield
    finally:
        if os.name == "posix":
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
        else:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


def read_json(path, limit=16384):
    with open(path, "rb") as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ControlError("服务端数据超过允许长度")
    return json.loads(raw)
