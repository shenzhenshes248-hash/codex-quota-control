# Codex 额度控制

中文 Android 客户端和 VPS 管理接口。手机负责远程管理，VPS 的 systemd 独立执行计划；手机关机、断网或关闭 App 不影响已保存的计划。

[下载 APK 和安装包](https://github.com/shenzhenshes248-hash/codex-quota-control/releases/tag/v0.2.0) · [原触发脚本源码](server/legacy/quota_trigger.py) · [测试结果](docs/test-results.md)

## 环境要求

v0.2.0 起支持新 VPS 初始化，也兼容已经有原触发环境的 VPS。每位使用者需要：

- 自己的 Debian 12+ / Ubuntu 22.04+、x86_64、systemd VPS，以及 root/sudo 权限。需要 Python 3.10+；缺失的基础依赖由 apt 安装。
- 自己具有 Codex 使用权限的 ChatGPT 账号。安装时由本人完成官方登录授权，不需要提供 OpenAI API Key，不共享项目作者的账号或 VPS。
- 二选一：已解析到目标 VPS 的域名，或该 VPS 的固定公网 IP（无需域名）。支持 IPv4/IPv6。
- TCP 80 用于 HTTPS 证书验证/续期，TCP 8443 用于管理接口；安装器需要这两个端口空闲并可从公网访问。443 保留给已有业务。
- VPS 系统时间准确，以便验证下载连接和 HTTPS 证书。

新 VPS 会自动创建专用运行账户、安装官方 Codex CLI、部署仓库内的原触发脚本和 systemd 单元，并引导账号授权。原触发判断逻辑不重写。[原脚本及说明](server/legacy/README.md)

已有完整触发环境会复用其脚本、登录和时间表；发现不完整的旧环境会停止，避免覆盖未知配置。原管理端已安装时，重复运行安装命令会保留原入口、Token 和计划。

## 一条命令下载并安装

选择下面一种方式，在目标 VPS 的终端运行完整一行。安装器会自动识别域名或 IP，无需提前手动上传文件。

**有域名：** 将末尾的 `api.example.com` 替换成已解析到目标 VPS 的域名。

```bash
curl -fL 'https://github.com/shenzhenshes248-hash/codex-quota-control/releases/download/v0.2.0/codex-quota-control-install.sh' -o codex-quota-control-install.sh && sudo bash codex-quota-control-install.sh api.example.com
```

**没有域名：** 将末尾的 `你的公网IP` 替换成目标 VPS 的固定公网 IPv4 或 IPv6 地址，不要加 `https://`、端口或路径。

```bash
curl -fL 'https://github.com/shenzhenshes248-hash/codex-quota-control/releases/download/v0.2.0/codex-quota-control-install.sh' -o codex-quota-control-install.sh && sudo bash codex-quota-control-install.sh 你的公网IP
```

无域名方式通过 Let's Encrypt 的 `shortlived` 配置申请公网可信 IP 证书，由 Caddy 自动续期，无需在手机安装自签名证书。IP 证书有效期约 6 天，需要持续开放 TCP 80 以供续期；IP 变化后须重新配置入口和 App 地址。[IP 证书官方说明](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability/)

仓库和 Release 均已公开，下载不需要 GitHub 登录或 GitHub Token。安装包自动解包、安装管理 API/HTTPS 并验证连接；下载失败时不会继续执行安装。已有部署使用原入口地址重复安装时会跳过安装，保留原 Token、时间计划和 HTTPS 配置；填写不同入口会停止，不自动切换现有服务。

首次安装尚未登录时，终端会显示官方授权链接和一次性代码。用手机或电脑浏览器打开链接，登录**自己的 ChatGPT/Codex 账号**并输入代码；如未启用设备码登录，先在 ChatGPT 的“设置→安全”或工作区权限中启用。凭据保存在自己的 VPS 专用账户中，不发送给项目作者或 GitHub。授权中断后，重新运行同一安装命令可继续。[官方无浏览器设备登录说明](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)

安装器会以只读方式检查原额度接口；不支持该接口、认证失败或网络错误时不报告成功，也不自动发送触发请求。API Key 按量计费，与该账号的订阅额度不同，不能替代本项目所需的 ChatGPT 登录。

**新装的默认时间为北京时间 08:00、13:00、18:00，自动计划处于暂停状态。** 在 App 修改时间并启用后才开始调度；已有环境保持安装前的计划状态。账号权限和窗口规则由 OpenAI 决定，原脚本的滑动窗口判定不保证适用于所有账号或未来规则。

安装完成后会显示 App 接口地址：域名方式为 `https://你的域名:8443`，无域名方式为 `https://你的公网IP:8443`，IPv6 为 `https://[你的IPv6]:8443`。管理 Token 由 VPS 随机生成，在自己的 VPS 终端查看：

```bash
sudo cat /etc/codex-quota-control/management-token
```

此 Token 用于自己的管理接口，不是 Codex 账号凭据；请勿提交到仓库或写入 APK。

## 手机客户端

- Android 8.0 及以上；Kotlin、Compose、Material 3，跟随系统深色模式。
- 从 [Release](https://github.com/shenzhenshes248-hash/codex-quota-control/releases/tag/v0.2.0) 下载并安装 APK。服务端 v0.2.0 沿用客户端 v0.1.1；已有 v0.1.1 手机端无需重装，v0.1.0 可覆盖升级。
- 在“设置”中填写安装结束时显示的 HTTPS 地址，域名和公网 IP 均可，填入自己 VPS 生成的管理 Token，点击“测试连接”后保存。
- Token 经 Android Keystore 的 AES-GCM 加密保存在手机本机，APK 中没有预置管理 Token。
- 首页编辑时间后点击“保存计划至 VPS”；启停按钮立即同步。24 小时时间选择器统一使用北京时间。
- “立即触发一次”返回 systemd 接收状态，App 随后查询真实成功/跳过/失败结果。关闭 App 不影响服务端任务。
- 触发遵循原有额度保护，不代表强制重置额度。
- 断网或请求失败不会显示保存成功；当前服务器状态不可读时明确显示未连接。不会把旧缓存当作实时状态。
- 未取得额度数据时显示“暂无数据”；已取得的额度附带原始采样时间，非持续实时测量。

## 服务端与回滚

API 以 codexquota 运行，原触发仍以 codexkeeper 运行。日志库位于 `/var/lib/codex-quota-control/runtime/executions.sqlite3`；原始失败输出仅保存在同目录的 `last-failure.private.log`，API 不提供下载。App 最多读取 50 条过滤记录，库保留 500 条。

原脚本原样执行，包装器只解析已检查的采样/结果标记及退出码。未知输出会标为结果不可确认，不把退出码 0 单独当作触发成功。原脚本未来若改变输出协议，应同步调整 `runner.py` 的解析；额度判断与 Codex 请求逻辑始终由原脚本决定。

源码安装从项目目录执行 `sudo bash deploy/setup.sh 域名或公网IP`。回滚时，从源码目录以 root/sudo 执行 `bash deploy/rollback.sh`，恢复管理层安装前的服务入口和计划启停状态；保留认证信息和日志。新初始化的计划会恢复为暂停状态。[部署变更和回滚说明](docs/deployment-changes.md)

## 一条命令卸载

适用于 v0.1.0 / v0.1.1 / v0.2.0，无需域名、管理 Token 或重新安装，下载后在目标 VPS 执行：

```bash
curl -fL 'https://github.com/shenzhenshes248-hash/codex-quota-control/releases/download/v0.2.0/codex-quota-control-uninstall.py' -o codex-quota-control-uninstall.py && sudo python3 codex-quota-control-uninstall.py
```

**此命令会删除本管理层的 API/HTTPS 服务、程序、独立管理 Token、执行日志、HTTPS 证书及 codexquota/codexquota-proxy 专用账户。需要的日志请提前自行留存。** 对已有环境，恢复其原脚本和安装前的定时计划，原定时触发可能继续运行；对 v0.2.0 新初始化的环境，删除本项目新建的触发脚本和 timer/service。两种情况均保留 `codexkeeper`、Codex CLI 和登录凭据。发现触发任务正在执行或排队时，卸载会中止，等待任务完成后再运行即可。

卸载手机 App 只删除手机客户端，不会卸载 VPS 服务或停止 VPS 定时任务。若只需恢复部署前状态并保留管理端数据，仍可使用前面的 `deploy/rollback.sh`。

## 接口

全部接口要求 `Authorization: Bearer <独立管理Token>`，公开入口只提供 HTTPS。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/status` | systemd 真实状态、最后记录和最近可靠额度采样 |
| GET/PUT | `/api/v1/schedules` | 读取/原子更新 `{enabled, times}` |
| POST | `/api/v1/trigger` | 返回 202 和任务 ID；并非执行成功 |
| GET | `/api/v1/executions/{id}` | 查询任务实际进度/结果 |
| GET | `/api/v1/logs?limit=50` | 过滤后的执行记录 |

计划固定为 Asia/Shanghai，不随手机时区变化。暂停不会杀死已经执行的任务。沿用原 `Persistent=false`：重启保留计划，停机期间错过的时间不补触发。

## 源码构建与验证

Android 使用 JDK 17 和 Android SDK 36，在 `android` 目录运行 `./gradlew assembleDebug`（Windows 为 `gradlew.bat`）。APK 输出在 `android/app/build/outputs/apk/debug/`。

服务端本地验证：安装 `server/requirements-test.txt`，在 `server` 目录运行 `python -m pytest tests -q`。Windows 可为 pytest 指定项目内临时目录。已完成真实 VPS API、计划修改及并发保护验证；真机交互和 VPS 重启尚未实测，详见 [测试结果](docs/test-results.md)。

交付包构建：先运行 `python tools/package_delivery.py`，再运行 `python tools/build_installer.py`。仓库仅包含项目源码和构建工具，本机登录脚本、管理 Token、签名密钥及缓存不上传。APK 和单文件安装包放在 Release 中。
