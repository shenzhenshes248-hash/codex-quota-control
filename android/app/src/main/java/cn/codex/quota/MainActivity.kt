package cn.codex.quota

import android.app.TimePickerDialog
import android.content.Context
import android.content.res.Configuration
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import java.time.LocalTime
import java.time.ZoneId
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun attachBaseContext(newBase: Context) {
        val config = Configuration(newBase.resources.configuration)
        config.setLocale(Locale.SIMPLIFIED_CHINESE)
        super.attachBaseContext(newBase.createConfigurationContext(config))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val dark = isSystemInDarkTheme()
            val colors = if (dark) darkColorScheme(primary = Color(0xFFA9C7FF))
                         else lightColorScheme(primary = Color(0xFF2458A6))
            SideEffect {
                WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = !dark
            }
            MaterialTheme(colorScheme = colors) { QuotaApp() }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun QuotaApp(vm: QuotaViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    var page by rememberSaveable { mutableIntStateOf(if (state.config.address.isBlank()) 2 else 0) }
    val snackbar = remember { SnackbarHostState() }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> vm.enterForeground()
                Lifecycle.Event.ON_STOP -> vm.leaveForeground()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) vm.enterForeground()
        onDispose { lifecycle.removeObserver(observer); vm.leaveForeground() }
    }
    LaunchedEffect(state.message) {
        state.message?.let { snackbar.showSnackbar(it, duration = SnackbarDuration.Long); vm.clearMessage() }
    }
    LaunchedEffect(page, state.config.address) { if (page == 1) vm.refreshLogs() }
    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Codex 额度控制", fontWeight = FontWeight.SemiBold) },
                actions = {
                    if (page != 2) IconButton(enabled = !state.busy && state.config.address.isNotBlank(),
                        onClick = { if (page == 1) vm.refreshLogs() else vm.refresh() }) {
                        Icon(Icons.Default.Refresh, "刷新 VPS 数据")
                    }
                })
        },
        bottomBar = {
            NavigationBar {
                listOf("首页", "执行日志", "设置").forEachIndexed { index, label ->
                    NavigationBarItem(selected = page == index, onClick = { page = index },
                        icon = { Icon(when (index) { 0 -> Icons.Default.Home; 1 -> Icons.Default.List
                            else -> Icons.Default.Settings }, contentDescription = null) },
                        label = { Text(label) })
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbar) }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            when (page) {
                0 -> Home(state, vm)
                1 -> Logs(state)
                else -> Settings(state, vm)
            }
        }
    }
}

@Composable
private fun Section(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            content()
        }
    }
}

@Composable
private fun Info(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun Home(state: UiState, vm: QuotaViewModel) {
    val context = LocalContext.current
    val status = state.status
    fun pickTime(old: String? = null) {
        val initial = old?.split(':')?.let { LocalTime.of(it[0].toInt(), it[1].toInt()) }
            ?: LocalTime.now(ZoneId.of(BEIJING_ZONE))
        TimePickerDialog(context, { _, hour, minute ->
            vm.editTime(old, String.format(Locale.ROOT, "%02d:%02d", hour, minute))
        }, initial.hour, initial.minute, true).apply { setTitle("选择北京时间（24 小时制）") }.show()
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Section("VPS 当前状态") {
                Text(if (state.online) "● VPS 在线" else "● VPS 未连接",
                    color = if (state.online) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                    fontWeight = FontWeight.SemiBold)
                if (status == null) {
                    Text(if (state.config.address.isBlank()) "请先在设置中填写 API 地址和管理 Token"
                         else "尚未取得 VPS 当前状态，请刷新或检查连接设置")
                } else {
                    Info("自动计划", if (status.schedules.enabled) "已启用" else "已暂停")
                    Info("VPS 当前生效的时间（北京时间）",
                        status.schedules.times.joinToString("   ").ifBlank { "未设置触发时间" })
                    Info("下一次预计执行", if (status.schedules.enabled) beijingTime(status.schedules.nextRun)
                         else "计划已暂停")
                    if (status.schedules.enabled && !status.schedules.bootEnabled)
                        Text("VPS 尚未启用开机调度，请检查服务配置", color = MaterialTheme.colorScheme.error)
                    OutlinedButton(onClick = vm::toggleEnabled, enabled = !state.busy,
                        modifier = Modifier.fillMaxWidth()) {
                        Text(if (status.schedules.enabled) "暂停全部自动计划" else "启用全部自动计划")
                    }
                }
            }
        }
        item {
            Section(when { state.editing -> "编辑计划 · 尚未保存"
                status == null -> "上次读取的时间（当前未连接）"
                else -> "自动触发时间" }) {
                Text("统一采用北京时间（Asia/Shanghai）", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (state.draftTimes.isEmpty()) Text("尚未添加时间")
                state.draftTimes.forEach { time ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(time, Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
                        IconButton(onClick = { pickTime(time) }, enabled = !state.busy && status != null) {
                            Icon(Icons.Default.Edit, "修改 $time")
                        }
                        IconButton(onClick = { vm.deleteTime(time) }, enabled = !state.busy && status != null) {
                            Icon(Icons.Default.Delete, "删除 $time")
                        }
                    }
                }
                OutlinedButton(onClick = { pickTime() }, enabled = !state.busy && status != null,
                    modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.Add, null); Spacer(Modifier.width(6.dp)); Text("添加时间")
                }
                Button(onClick = vm::saveSchedules, modifier = Modifier.fillMaxWidth(),
                    enabled = state.editing && !state.busy && status != null) { Text("保存计划至 VPS") }
                if (state.editing) TextButton(onClick = vm::discardChanges, enabled = !state.busy) { Text("放弃本次编辑并刷新") }
            }
        }
        item {
            Section("手动触发") {
                Text(if (status?.running == true) "VPS 正在执行任务或等待额度窗口"
                    else if (state.executionUnknown) "上次提交的结果尚未确认，请先刷新 VPS 状态"
                    else "沿用 VPS 原有额度检查及跳过规则")
                Button(onClick = vm::trigger,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                    enabled = state.online && !state.busy && status?.running == false && !state.executionUnknown) {
                    Icon(Icons.Default.PlayArrow, null); Spacer(Modifier.width(8.dp)); Text("立即触发一次")
                }
                Text("触发会发出真实 Codex 请求，不代表强制重置额度。",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        item {
            Section("最近一次执行") {
                val last = status?.last
                if (last == null) Text("暂无数据") else {
                    Info("实际开始时间", beijingTime(last.startedAt))
                    Info("执行结果", "${resultLabel(last.result)} · ${last.reason}")
                }
            }
        }
        item {
            Section("Codex 额度状态") {
                val quota = status?.quota
                if (quota == null) Text("暂无数据") else {
                    Info("五小时额度剩余（原脚本采样值）", "${quota.remaining.toInt()}%")
                    Info("窗口状态", if (quota.state == "active") "活动窗口" else "空闲窗口")
                    Info("窗口预计结束", beijingTime(quota.resetsAt))
                    Info("采样时间", beijingTime(quota.observedAt))
                }
            }
        }
        item { Text("定时任务由 VPS 独立执行，手机关机或关闭 App 不影响已保存的计划。",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

@Composable
private fun Logs(state: UiState) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("最近 50 条执行记录 · 北京时间", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        if (state.logsError != null) item { Text(state.logsError, color = MaterialTheme.colorScheme.error) }
        else if (state.logs == null) item { Text("点击右上角刷新，读取 VPS 执行日志") }
        else if (state.logs.isEmpty()) item { Text("暂无执行记录") }
        items(state.logs.orEmpty(), key = { it.id }) { record ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(when (record.source) { "manual" -> "手动触发"; "automatic" -> "自动触发"
                            else -> "历史执行（来源未知）" },
                            fontWeight = FontWeight.SemiBold)
                        Text(resultLabel(record.result), color = if (record.result == "failed")
                            MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
                    }
                    Text(beijingTime(record.startedAt), style = MaterialTheme.typography.bodySmall)
                    Text(record.reason)
                }
            }
        }
    }
}

@Composable
private fun Settings(state: UiState, vm: QuotaViewModel) {
    var address by remember(state.config.address) {
        mutableStateOf(state.config.address.ifBlank { "https://cod.futur-ix.top:8443" })
    }
    // The plaintext token is kept only in memory; it is never saved in an activity state bundle.
    var token by remember(state.config.token) { mutableStateOf(state.config.token) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Section("VPS 连接设置") {
            OutlinedTextField(value = address, onValueChange = { address = it },
                modifier = Modifier.fillMaxWidth(), label = { Text("VPS API 地址") },
                placeholder = { Text("https://api.example.com:8443") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), enabled = !state.busy)
            OutlinedTextField(value = token, onValueChange = { token = it },
                modifier = Modifier.fillMaxWidth(), label = { Text("独立管理 Token") },
                visualTransformation = PasswordVisualTransformation(), singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), enabled = !state.busy)
            Text("使用管理接口专用 Token。请勿填写 VPS 密码、SSH 私钥或 Codex 账号凭据。",
                style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { vm.configure(ConnectionConfig(address, token), testOnly = true) },
                modifier = Modifier.fillMaxWidth(), enabled = !state.busy) { Text("测试连接") }
            Button(onClick = { vm.configure(ConnectionConfig(address, token), testOnly = false) },
                modifier = Modifier.fillMaxWidth(), enabled = !state.busy) { Text("保存连接配置") }
        }
        Text("认证信息由 Android Keystore 加密保存在本机。所有计划与执行结果均从 VPS 读取。",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
