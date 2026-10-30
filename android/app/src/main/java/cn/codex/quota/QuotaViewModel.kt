package cn.codex.quota

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class UiState(
    val config: ConnectionConfig = ConnectionConfig(),
    val status: Status? = null,
    val online: Boolean = false,
    val busy: Boolean = false,
    val editing: Boolean = false,
    val draftEnabled: Boolean = false,
    val draftTimes: List<String> = emptyList(),
    val logs: List<Execution>? = null,
    val message: String? = null,
    val executionUnknown: Boolean = false,
    val logsError: String? = null
)

class QuotaViewModel(application: Application) : AndroidViewModel(application) {
    private val credentials = CredentialStore(application)
    private val _state = MutableStateFlow(UiState())
    val state = _state.asStateFlow()
    private var foreground = false
    private var polling: Job? = null
    private var manualId: String? = null
    init {
        try { _state.update { it.copy(config = credentials.read()) } }
        catch (_: Exception) { message("本机加密配置无法读取，请在设置中重新填写连接信息") }
    }

    fun clearMessage() { _state.update { it.copy(message = null) } }
    fun message(text: String) { _state.update { it.copy(message = text) } }

    fun enterForeground() {
        foreground = true
        if (_state.value.config.address.isNotBlank()) refresh()
    }
    fun leaveForeground() { foreground = false; polling?.cancel(); polling = null }

    private suspend fun loadStatus(api: QuotaApi, replaceDraft: Boolean = false) {
        val actual = api.status()
        _state.update {
            val reset = replaceDraft || !it.editing
            it.copy(status = actual, online = true, executionUnknown = manualId != null,
                draftTimes = if (reset) actual.schedules.times else it.draftTimes,
                draftEnabled = if (reset) actual.schedules.enabled else it.draftEnabled,
                editing = if (replaceDraft) false else it.editing)
        }
    }

    private fun failed(error: Exception, uncertain: Boolean = false) {
        if (error is CancellationException) throw error
        _state.update { it.copy(online = false, status = null, logs = null,
            executionUnknown = it.executionUnknown || uncertain,
            message = error.message?.take(180) ?: "操作失败，请刷新服务器状态") }
    }

    fun refresh() {
        if (_state.value.busy) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            try { loadStatus(QuotaApi(_state.value.config)); startPolling() }
            catch (e: Exception) { failed(e) }
            finally { _state.update { it.copy(busy = false) } }
        }
    }

    fun editTime(old: String?, value: String) {
        val times = _state.value.draftTimes.filter { it != old } + value
        try { _state.update { it.copy(draftTimes = sortedTimes(times), editing = true) } }
        catch (e: IllegalArgumentException) { message(e.message ?: "时间不正确") }
    }
    fun deleteTime(value: String) { _state.update { it.copy(draftTimes = it.draftTimes - value,
        draftEnabled = it.draftEnabled && it.draftTimes.size > 1, editing = true) } }
    fun editEnabled(enabled: Boolean) { _state.update { it.copy(draftEnabled = enabled, editing = true) } }
    fun discardChanges() { _state.update { it.copy(editing = false) }; refresh() }

    fun saveSchedules() {
        val current = _state.value
        if (current.busy || current.status == null) return
        if (current.draftEnabled && current.draftTimes.isEmpty()) { message("请先添加触发时间"); return }
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            try {
                val actual = QuotaApi(current.config).saveSchedules(current.draftEnabled, current.draftTimes)
                if (actual.enabled != current.draftEnabled || actual.times != current.draftTimes) {
                    throw ApiException("VPS 读回的计划不一致，请刷新确认")
                }
                // The success message is based on the server's verified PUT response, never an optimistic update.
                _state.update { it.copy(status = it.status?.copy(schedules = actual), online = true,
                    draftTimes = actual.times, draftEnabled = actual.enabled, editing = false,
                    message = "计划已在 VPS 生效") }
            } catch (e: Exception) { failed(e) }
            finally { _state.update { it.copy(busy = false) } }
        }
    }

    fun toggleEnabled() {
        val current = _state.value
        val saved = current.status?.schedules ?: return
        if (current.busy) return
        if (!saved.enabled && saved.times.isEmpty()) { message("请先添加并保存触发时间"); return }
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            try {
                val actual = QuotaApi(current.config).saveSchedules(!saved.enabled, saved.times)
                _state.update { it.copy(status = it.status?.copy(schedules = actual),
                    draftEnabled = actual.enabled,
                    message = if (actual.enabled) "已启用全部自动计划" else "已暂停全部自动计划") }
            } catch (e: Exception) { failed(e) }
            finally { _state.update { it.copy(busy = false) } }
        }
    }

    fun trigger() {
        val current = _state.value
        if (current.busy || !current.online || current.status?.running == true || current.executionUnknown) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, executionUnknown = true) }
            try {
                manualId = QuotaApi(current.config).trigger()
                message("任务已交给 VPS，正在查询实际执行结果")
                loadStatus(QuotaApi(current.config))
                startPolling()
            } catch (e: Exception) { failed(e, uncertain = true) }
            finally { _state.update { it.copy(busy = false) } }
        }
    }

    private fun startPolling() {
        if (!foreground || polling?.isActive == true) return
        if (manualId == null && _state.value.status?.running != true) return
        polling = viewModelScope.launch {
            try {
                do {
                    delay(3000)
                    val api = QuotaApi(_state.value.config)
                    manualId?.let { id ->
                        val result = api.execution(id)
                        if (result.result != "running") {
                            manualId = null
                            message("${resultLabel(result.result)}：${result.reason}")
                        }
                    }
                    loadStatus(api)
                } while (foreground && (manualId != null || _state.value.status?.running == true))
            } catch (e: Exception) { failed(e, uncertain = manualId != null) }
        }
    }

    fun refreshLogs() {
        if (_state.value.busy || _state.value.config.address.isBlank()) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, logsError = null) }
            try { val items = QuotaApi(_state.value.config).logs(); _state.update { it.copy(logs = items) } }
            catch (e: Exception) {
                if (e is CancellationException) throw e
                _state.update { it.copy(logs = null, logsError = e.message ?: "日志读取失败") }
            } finally { _state.update { it.copy(busy = false) } }
        }
    }

    fun configure(config: ConnectionConfig, testOnly: Boolean) {
        if (_state.value.busy) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            try {
                val checked = config.normalized()
                if (testOnly) {
                    QuotaApi(checked).status()
                    message("连接测试成功，VPS 已通过身份认证")
                } else {
                    credentials.save(checked)
                    polling?.cancel(); polling = null; manualId = null
                    _state.update { UiState(config = checked, busy = true) }
                    loadStatus(QuotaApi(checked), replaceDraft = true)
                    message("连接配置已加密保存，并已读取 VPS 当前状态")
                    startPolling()
                }
            } catch (e: Exception) {
                if (testOnly || e is IllegalArgumentException) message(e.message ?: "连接配置不正确")
                else failed(e)
            } finally { _state.update { it.copy(busy = false) } }
        }
    }
}
