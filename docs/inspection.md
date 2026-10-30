# 已确认的现有部署

检查日期：2026-10-30。通过 Xshell 保存的登录配置自动建立临时只读连接，未解密密码。

- VPS：154.36.137.206:22；Ubuntu 22.04.5 LTS；Python 3.10.12；时区 Asia/Shanghai。
- 用户/工作目录：codexkeeper，`/home/codexkeeper/codexkeeper-run`。
- 原脚本：该目录中的 `quota_trigger.py`，权限 0700。
- 原服务/定时器：`codex-quota-trigger.service`、`codex-quota-trigger.timer`。
- 实际启用时间：08:00、13:00、18:00；AccuracySec=1s；Persistent=false。
- 原入口：`/usr/bin/python3 .../quota_trigger.py --wait-minutes 10`。
- 原逻辑：间隔 8 秒采样额度，通过 resetsAt 是否滑动判断窗口；仅空闲窗口运行 Codex exec；接近结束的活动窗口按原设置等待，其他活动窗口跳过。
- 原脚本可提供五小时额度剩余整数百分比、窗口状态、预计结束时间；不提供可靠的周额度。
- systemd journal 中确实存在采样及触发标记，可读取最近一次历史结果；历史任务的触发来源无法确认，标注“来源未知”。
- 未发现 systemd 管理的 Caddy/Nginx/Apache。443 正被 Xray 占用，80 当时空闲。
- 公共 DNS 已确认 `cod.futur-ix.top → 154.36.137.206`，使用仅 DNS 模式。
- `venv` 模块存在，`ensurepip` 不存在；安装脚本只为新 API 建立隔离虚拟环境并引导 pip，不升级系统 Python。

本次检查未修改原脚本、凭据、systemd 单元、时区或现有网络服务；未发出 Codex 请求。
