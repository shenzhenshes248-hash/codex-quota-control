"""The only sudo entry point. No command-line arguments or arbitrary commands accepted."""
import json
import os
import sys
from .common import ControlError
from .controller import Controller


def dispatch(data, controller):
    if not isinstance(data, dict) or set(data) - {"operation", "payload"}:
        raise ControlError("无效管理请求", 422)
    op, payload = data.get("operation"), data.get("payload", {})
    if op == "status" and payload == {}:
        return controller.status()
    if op == "schedules" and payload == {}:
        return controller.schedules()
    if op == "set_schedules":
        return controller.set_schedules(payload)
    if op == "trigger" and payload == {}:
        return controller.trigger()
    if op == "logs" and isinstance(payload, dict) and set(payload) == {"limit"}:
        n = payload["limit"]
        if type(n) is int and 1 <= n <= 50:
            return {"items": controller.logs(n)}
    if op == "execution" and isinstance(payload, dict) and set(payload) == {"id"}:
        return controller.execution(payload["id"])
    raise ControlError("不支持此管理操作", 422)


def main():
    try:
        if os.name != "posix" or os.geteuid() != 0 or len(sys.argv) != 1:
            raise ControlError("管理助手仅允许通过限定的 sudo 入口运行")
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ControlError("请求过大", 413)
        data = dispatch(json.loads(raw), Controller())
        result = {"ok": True, "data": data}
    except ControlError as e:
        result = {"ok": False, "status": e.status, "message": str(e)}
    except Exception:
        result = {"ok": False, "status": 503, "message": "VPS 管理助手执行失败，请检查服务配置"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
