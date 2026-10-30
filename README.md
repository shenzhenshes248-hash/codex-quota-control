# Codex 额度控制

中文 Android 管理 App + VPS FastAPI 管理层。手机只远程管理，systemd 独立执行定时任务。

当前阶段：已按确认的清单部署至 VPS，真实 API、HTTPS 证书、计划修改/恢复及并发验证通过。入口为 `https://cod.futur-ix.top:8443`，现行计划为北京时间 08:00、13:00、18:00。真机交互和 VPS 重启尚未实测。检查结果见 [现有系统](docs/inspection.md)，线上变更见 [变更与回滚](docs/deployment-changes.md)。

## Android

- Android 8.0 及以上；Kotlin、Compose、Material 3，跟随系统深色模式。
- 设置页填写 `https://cod.futur-ix.top:8443` 和独立管理 Token，测试连接后保存；Token 经 Android Keystore 的 AES-GCM 加密。
- 本次 APK 已预填上述地址；独立管理 Token 已保存到开发电脑的 `.tools/手机连接信息.txt`，仅当前用户和 SYSTEM 可访问，未包含在交付包内。
- 首页编辑时间后点击“保存计划至 VPS”；启停按钮立即同步。24 小时时间选择器统一使用北京时间。
- “立即触发一次”返回 systemd 接收状态，App 随后查询真实成功/跳过/失败结果。关闭 App 不影响服务端任务。
- 断网或请求失败不会显示保存成功；当前服务器状态不可读时明确显示未连接。不会把旧缓存当作实时状态。
- 未取得额度数据时显示“暂无数据”；已取得的额度附带原始采样时间，非持续实时测量。

构建：JDK 17、Android SDK 36，在 `android` 目录运行 `./gradlew assembleDebug`（Windows 为 `gradlew.bat`）。APK 输出在 `android/app/build/outputs/apk/debug/`。

## VPS 安装

本次已由 Codex 自动执行以下部署，用户不需要逐条复制命令。脚本保留供维护和回滚，已安装的 VPS 不要重复运行安装脚本。

也已提供单文件安装包 `codex-quota-control-install.sh`。从私有 GitHub 仓库的 Release 下载并上传到 VPS 后，只执行一条命令：

```bash
sudo bash codex-quota-control-install.sh cod.futur-ix.top
```

安装包包含服务端代码，自动解包、安装 API/HTTPS 并验证连接。已有部署会保留 Token、时间计划和 HTTPS 配置。前提是 VPS 已有原触发脚本、codexkeeper 用户及有效 Codex 登录；本安装包只部署远程管理层。私有仓库下载需要先登录 GitHub。

1. 上传服务端交付包并解压，执行 `bash deploy/install.sh`。只安装新 API、执行包装器及必要单元，原脚本不改。
2. 执行 `bash deploy/install-https.sh cod.futur-ix.top`，使用 8443 和自动续期的公开可信证书。80 用于证书验证；443 保留给现有 Xray。
3. 确认 HTTPS、认证、真实计划读回及原有额度保护。管理 Token 位于 VPS `/etc/codex-quota-control/management-token`，不写入 APK、不输出到部署日志。
4. 回滚执行 `bash deploy/rollback.sh`。脚本保留原时间表、原认证信息和日志。

API 以 codexquota 运行，原触发仍以 codexkeeper 运行。日志库位于 `/var/lib/codex-quota-control/runtime/executions.sqlite3`；原始失败输出仅保存在同目录的 `last-failure.private.log`，API 不提供下载。App 最多读取 50 条过滤记录，库保留 500 条。

原脚本原样执行，包装器只解析已检查的采样/结果标记及退出码。未知输出会标为结果不可确认，不把退出码 0 单独当作触发成功。原脚本未来若改变输出协议，应同步调整 `runner.py` 的解析；额度判断与 Codex 请求逻辑始终由原脚本决定。

检查时读取的原触发脚本源码备份位于 `server/legacy/quota_trigger.py`，不包含登录凭据，安装时不会覆盖现网脚本。

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

本地验证：安装 `server/requirements-test.txt`，在 `server` 目录运行 `python -m pytest tests -q`。Windows 可为 pytest 指定项目内临时目录。测试与真实 VPS 验证的区别详见 [测试结果](docs/test-results.md)。

交付包构建：先运行 `python tools/package_delivery.py`，再运行 `python tools/build_installer.py`。私有仓库仅包含项目源码和构建工具，本机登录脚本、管理 Token、签名密钥及缓存不上传。APK 和单文件安装包放在 Release 中。
