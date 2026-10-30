package cn.codex.quota

import java.net.URI
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

const val BEIJING_ZONE = "Asia/Shanghai"

data class ConnectionConfig(val address: String = "", val token: String = "") {
    fun normalized(): ConnectionConfig {
        val text = address.trim().trimEnd('/')
        val uri = try { URI(text) } catch (_: Exception) {
            throw IllegalArgumentException("API 地址格式不正确")
        }
        require(uri.scheme == "https" && !uri.host.isNullOrBlank() &&
            uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null &&
            uri.path.isNullOrEmpty() && (uri.port == -1 || uri.port in 1..65535)) {
            "请输入 HTTPS 域名或 IP 地址，例如 https://你的公网IP:8443"
        }
        require(token.trim().length >= 32 && token.trim().all { it.code in 33..126 }) {
            "管理 Token 至少需要 32 个英文字符或数字"
        }
        return ConnectionConfig(text, token.trim())
    }
}

data class Schedule(
    val enabled: Boolean,
    val bootEnabled: Boolean,
    val times: List<String>,
    val nextRun: String?
)

data class Quota(val remaining: Double, val resetsAt: String, val observedAt: String, val state: String)
data class Execution(
    val id: String,
    val source: String,
    val startedAt: String?,
    val finishedAt: String?,
    val result: String,
    val reason: String
)
data class Status(val schedules: Schedule, val running: Boolean, val last: Execution?, val quota: Quota?)

fun sortedTimes(times: List<String>): List<String> {
    require(times.all { it.matches(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d")) }) { "时间格式不正确" }
    require(times.distinct().size == times.size) { "此时间已经存在" }
    return times.sorted()
}

fun beijingTime(value: String?): String {
    if (value == null) return "暂无数据"
    return try {
        DateTimeFormatter.ofPattern("MM-dd HH:mm:ss", Locale.SIMPLIFIED_CHINESE)
            .withZone(ZoneId.of(BEIJING_ZONE)).format(OffsetDateTime.parse(value).toInstant()) + " 北京时间"
    } catch (_: Exception) { "暂无数据" }
}

fun resultLabel(value: String) = when (value) {
    "success" -> "成功"
    "skipped" -> "跳过"
    "failed" -> "失败"
    "running" -> "执行中"
    else -> "暂无数据"
}
