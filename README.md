# Codex 额度控制

中文 Android 客户端和 VPS 管理接口。手机负责远程管理，VPS 的 systemd 独立执行计划；手机关机、断网或关闭 App 不影响已保存的计划。

[下载 APK 和安装包](https://github.com/shenzhenshes248-hash/codex-quota-control/releases/tag/v0.1.0) · [原触发脚本源码](server/legacy/quota_trigger.py) · [测试结果](docs/test-results.md)

## 环境要求

当前单文件安装包适用于已经有 Codex 额度触发系统的 x86_64 Linux VPS，已在 Ubuntu 22.04 / Python 3.10 上验证。安装前需要：

- systemd、Python 3.10+（含 venv）、sudo，以及 root/sudo 权限。
- 已有 `codexkeeper` 用户，该用户的 Codex CLI 已完成登录，并能正常运行原触发逻辑。
- 原脚本位于 `/home/codexkeeper/codexkeeper-run/quota_trigger.py`，已有 `codex-quota-trigger.service` 和 `codex-quota-trigger.timer`。
- 自己的域名已解析到目标 VPS；TCP 80 用于 HTTPS 证书验证/续期，TCP 8443 用于管理接口。443 保留给已有业务。

全新 VPS 请先准备原触发脚本、运行用户、Codex 登录和原 systemd 服务。此安装包安装远程管理层，保留原触发逻辑和认证信息。[原脚本备份及说明](server/legacy/README.md)

## 一条命令下载并安装

**先将下面命令末尾的 `api.example.com` 替换为你自己的域名。** 在目标 VPS 的终端运行完整一行，包含下载安装包的步骤，无需提前手动上传文件：

```bash
curl -fL 'https://github.com/shenzhenshes248-hash/codex-quota-control/releases/download/v0.1.0/codex-quota-control-install.sh' -o codex-quota-control-install.sh && sudo bash codex-quota-control-install.sh api.example.com
```

仓库和 Release 均已公开，下载不需要 GitHub 登录或 GitHub Token。安装包自动解包、安装管理 API/HTTPS 并验证连接；下载失败时不会继续执行安装。已有部署会跳过安装，保留原 Token、时间计划和 HTTPS 配置。

安装完成后的 App 接口地址为 `https://你的域名:8443`。管理 Token 由 VPS 随机生成，在自己的 VPS 终端查看：

```bash
sudo cat /etc/codex-quota-control/management-token
```

此 Token 用于自己的管理接口，不是 Codex 账号凭据；请勿提交到仓库或写入 APK。

## 手机客户端

- Android 8.0 及以上；Kotlin、Compose、Material 3，跟随系统深色模式。
- 从 [Release](https://github.com/shenzhenshes248-hash/codex-quota-control/releases/tag/v0.1.0) 下载并安装 APK。
- 在“设置”中将 API 地址改成自己的 `https://你的域名:8443`，填入自己 VPS 生成的管理 Token，点击“测试连接”后保存。不要沿用其他人的服务器地址。
- Token 经 Android Keystore 的 AES-GCM 加密保存在手机本机，APK 中没有预置管理 Token。
- 首页编辑时间后点击“保存计划至 VPS”；启停按钮立即同步。24 小时时间选择器统一使用北京时间。
- “立即触发一次”返回 systemd 接收状态，App 随后查询真实成功/跳过/失败结果。关闭 App 不影响服务端任务。
- 触发遵循原有额度保护，不代表强制重置额度。
- 断网或请求失败不会显示保存成功；当前服务器状态不可读时明确显示未连接。不会把旧缓存当作实时状态。
- 未取得额度数据时显示“暂无数据”；已取得的额度附带原始采样时间，非持续实时测量。

## 服务端与回滚

API 以 codexquota 运行，原触发仍以 codexkeeper 运行。日志库位于 `/var/lib/codex-quota-control/runtime/executions.sqlite3`；原始失败输出仅保存在同目录的 `last-failure.private.log`，API 不提供下载。App 最多读取 50 条过滤记录，库保留 500 条。

原脚本原样执行，包装器只解析已检查的采样/结果标记及退出码。未知输出会标为结果不可确认，不把退出码 0 单独当作触发成功。原脚本未来若改变输出协议，应同步调整 `runner.py` 的解析；额度判断与 Codex 请求逻辑始终由原脚本决定。

源码安装也可从项目目录依次执行 `deploy/install.sh` 和 `deploy/install-https.sh`。回滚时，从源码目录以 root/sudo 执行 `bash deploy/rollback.sh`，恢复安装前的服务入口和计划启停状态；保留认证信息和日志。[部署变更和回滚说明](docs/deployment-changes.md)

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
