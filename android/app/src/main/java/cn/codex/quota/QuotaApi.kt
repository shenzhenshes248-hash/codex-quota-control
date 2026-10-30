package cn.codex.quota

import java.net.URL
import java.net.SocketTimeoutException
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class ApiException(message: String, val statusCode: Int = 0) : Exception(message)

class QuotaApi(private val config: ConnectionConfig) {
    private suspend fun request(method: String, path: String, body: JSONObject? = null): JSONObject =
        withContext(Dispatchers.IO) {
            val checked = config.normalized()
            val connection = URL(checked.address + path).openConnection() as HttpsURLConnection
            try {
                connection.requestMethod = method
                connection.connectTimeout = 15000
                connection.readTimeout = 30000
                connection.instanceFollowRedirects = false
                connection.setRequestProperty("Authorization", "Bearer ${checked.token}")
                connection.setRequestProperty("Accept", "application/json")
                if (body != null) {
                    connection.doOutput = true
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                }
                val code = connection.responseCode
                if (code in 300..399) throw ApiException("API 地址发生重定向，请填写最终 HTTPS 地址", code)
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val bytes = stream?.use { it.readBytesLimited() } ?: byteArrayOf()
                val json = try { JSONObject(String(bytes, Charsets.UTF_8)) } catch (_: Exception) {
                    throw ApiException("VPS 返回了无法识别的响应", code)
                }
                if (code !in 200..299) {
                    val message = when (code) {
                        401 -> "认证失败，请检查管理 Token"
                        404 -> "API 路径或执行记录不存在，请检查服务器地址"
                        else -> json.optString("detail", "VPS 请求失败").take(180)
                    }
                    throw ApiException(message, code)
                }
                json
            } catch (e: ApiException) {
                throw e
            } catch (_: SocketTimeoutException) {
                throw ApiException("连接超时，操作结果尚未确认，请刷新 VPS 状态")
            } catch (_: SSLException) {
                throw ApiException("HTTPS 证书验证失败，请检查域名和服务器证书")
            } catch (_: java.io.IOException) {
                throw ApiException("网络连接失败，请检查网络、API 地址及 VPS 状态")
            } finally {
                connection.disconnect()
            }
        }

    private fun java.io.InputStream.readBytesLimited(): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (true) {
            val count = read(buffer)
            if (count == -1) return out.toByteArray()
            if (out.size() + count > 512 * 1024) throw ApiException("VPS 响应过大")
            out.write(buffer, 0, count)
        }
    }

    suspend fun status(): Status {
        val data = request("GET", "/api/v1/status")
        val quota = data.objectOrNull("quota")?.let {
            Quota(it.getDouble("remaining_percent"), it.getString("window_resets_at"),
                it.getString("observed_at"), it.getString("window_state"))
        }
        return Status(parseSchedule(data.getJSONObject("schedules")), data.getBoolean("running"),
            data.objectOrNull("last_execution")?.let(::parseExecution), quota)
    }

    suspend fun saveSchedules(enabled: Boolean, times: List<String>): Schedule = parseSchedule(
        request("PUT", "/api/v1/schedules", JSONObject().put("enabled", enabled)
            .put("times", JSONArray(sortedTimes(times)))))

    suspend fun trigger(): String = request("POST", "/api/v1/trigger", JSONObject()).getString("id")
    suspend fun execution(id: String): Execution = parseExecution(request("GET", "/api/v1/executions/$id"))
    suspend fun logs(): List<Execution> {
        val items = request("GET", "/api/v1/logs?limit=50").getJSONArray("items")
        return (0 until items.length()).map { parseExecution(items.getJSONObject(it)) }
    }

    private fun parseSchedule(data: JSONObject): Schedule {
        if (data.getString("timezone") != BEIJING_ZONE) throw ApiException("VPS 计划时区不是北京时间，请检查配置")
        val times = data.getJSONArray("times")
        return Schedule(data.getBoolean("enabled"), data.getBoolean("boot_enabled"),
            sortedTimes((0 until times.length()).map { times.getString(it) }), data.stringOrNull("next_run_at"))
    }

    private fun parseExecution(data: JSONObject) = Execution(data.getString("id"), data.getString("source"),
        data.stringOrNull("started_at"), data.stringOrNull("finished_at"),
        data.getString("result"), data.getString("reason"))

    private fun JSONObject.objectOrNull(key: String) = if (isNull(key)) null else getJSONObject(key)
    private fun JSONObject.stringOrNull(key: String) = if (isNull(key)) null else getString(key)
}
