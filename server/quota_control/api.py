import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool
from .common import ControlError, validate_schedule


class SchedulesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    times: list[str]


class Bridge:
    def call(self, operation, payload=None):
        try:
            proc = subprocess.run(["/usr/bin/sudo", "-n", "/usr/local/sbin/codex-quota-helper"],
                                  input=json.dumps({"operation": operation, "payload": payload or {}}),
                                  capture_output=True, text=True, timeout=90,
                                  env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
            if proc.returncode or len(proc.stdout) > 1024 * 1024:
                raise ValueError("helper failure")
            result = json.loads(proc.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise HTTPException(503, "无法确认 VPS 操作结果，请刷新状态；不要重复提交触发")
        if not result.get("ok"):
            raise HTTPException(result.get("status", 503), result.get("message", "VPS 操作失败"))
        return result["data"]


def create_app(bridge=None, token_file=None):
    bridge = bridge or Bridge()
    token_file = Path(token_file) if token_file else Path(
        os.getenv("CREDENTIALS_DIRECTORY", "/run/credentials/codex-quota-control-api.service")
    ) / "management-token"
    app = FastAPI(title="Codex 额度控制", docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(authorization: str = Header(default="")):
        try:
            token = token_file.read_text().strip()
        except OSError:
            raise HTTPException(503, "服务端管理认证尚未配置")
        if len(token) < 32:
            raise HTTPException(503, "服务端管理认证配置无效")
        expected = hashlib.sha256(("Bearer " + token).encode()).digest()
        actual = hashlib.sha256(authorization.encode()).digest()
        if not secrets.compare_digest(expected, actual):
            raise HTTPException(401, "认证失败，请检查管理 Token", headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exception):
        # Do not echo rejected values, which may contain credentials.
        return JSONResponse(status_code=422, content={"detail": "请求格式不正确，请检查时间列表"})

    @app.get("/api/v1/status", dependencies=[Depends(authenticate)])
    def status():
        return bridge.call("status")

    @app.get("/api/v1/schedules", dependencies=[Depends(authenticate)])
    def schedules():
        return bridge.call("schedules")

    @app.put("/api/v1/schedules", dependencies=[Depends(authenticate)])
    def update(body: SchedulesBody):
        try:
            data = validate_schedule(body.model_dump())
        except ControlError as e:
            raise HTTPException(e.status, str(e))
        return bridge.call("set_schedules", data)

    @app.post("/api/v1/trigger", status_code=202, dependencies=[Depends(authenticate)])
    def trigger():
        return bridge.call("trigger")

    @app.get("/api/v1/executions/{ident}", dependencies=[Depends(authenticate)])
    def execution(ident: str):
        return bridge.call("execution", {"id": ident})

    @app.get("/api/v1/logs", dependencies=[Depends(authenticate)])
    def logs(limit: int = Query(default=50, ge=1, le=50)):
        return bridge.call("logs", {"limit": limit})

    return app


app = create_app()
