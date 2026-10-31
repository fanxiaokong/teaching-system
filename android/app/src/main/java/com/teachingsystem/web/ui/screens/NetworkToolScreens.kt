package com.teachingsystem.web.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import com.teachingsystem.web.ui.showToast
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.io.BufferedReader
import java.io.InputStreamReader

// ===================== Ping =====================
@Composable
fun PingScreen(navController: NavHostController) {
    var host by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    ToolPage("Ping 测试", navController) {
        OutlinedTextField(host, { host = it }, Modifier.fillMaxWidth(),
            label = { Text("域名或 IP（如 baidu.com）") }, singleLine = true)
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                val h = host.trim()
                if (h.isEmpty()) { showToast(ctx, "请输入域名或 IP"); return@Button }
                scope.launch {
                    running = true
                    result = ""
                    result = pingHost(h)
                    running = false
                }
            },
            enabled = !running,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (running) "Ping 中…" else "开始 Ping") }
        Spacer(Modifier.height(12.dp))
        Text("结果（4 次）", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(
            result.ifBlank { "尚未执行" },
            fontSize = 13.sp,
            color = TextMain,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.verticalScroll(rememberScrollState()),
        )
    }
}

private suspend fun pingHost(host: String): String = withContext(Dispatchers.IO) {
    try {
        val proc = ProcessBuilder("ping", "-c", "4", "-W", "2", host)
            .redirectErrorStream(true).start()
        val out = StringBuilder()
        BufferedReader(InputStreamReader(proc.inputStream)).useLines { lines ->
            lines.forEach { out.append(it).append('\n') }
        }
        proc.waitFor()
        out.toString().ifBlank { "无输出（可能被系统限制）" }
    } catch (e: Exception) {
        "Ping 失败：${e.message}"
    }
}

// ===================== IP 扫描 =====================
@Composable
fun IpScanScreen(navController: NavHostController) {
    var result by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    ToolPage("IP 扫描", navController) {
        Text("扫描当前 Wi-Fi 网段内的在线设备（约 1~2 分钟）", fontSize = 13.sp, color = TextSub)
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                scope.launch {
                    running = true
                    result = ""
                    result = scanLan()
                    running = false
                }
            },
            enabled = !running,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (running) "扫描中…" else "开始扫描") }
        Spacer(Modifier.height(12.dp))
        Text("在线设备", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(
            result.ifBlank { "尚未扫描" },
            fontSize = 13.sp,
            color = TextMain,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.verticalScroll(rememberScrollState()),
        )
    }
}

private fun localIp(): String? = try {
    Socket().use { s ->
        s.connect(InetSocketAddress("8.8.8.8", 80), 1500)
        s.localAddress?.hostAddress
    }
} catch (e: Exception) { null }

private suspend fun scanLan(): String = withContext(Dispatchers.IO) {
    val ip = localIp() ?: return@withContext "无法获取本机 IP（请确认已连接 Wi-Fi）"
    val prefix = ip.substringBeforeLast('.')
    val base = prefix.split('.').joinToString(".")
    coroutineScope {
        val found = (1..254).map { last ->
            async {
                val target = "$base.$last"
                val ok = try {
                    InetAddress.getByName(target).isReachable(800)
                } catch (e: Exception) { false }
                if (ok) target else null
            }
        }.awaitAll().filterNotNull()
        buildString {
            append("本机网段：$base.0/24\n\n")
            if (found.isEmpty()) append("未发现在线设备")
            else found.forEach { append("在线：$it\n") }
        }
    }
}

// ===================== 端口扫描 =====================
@Composable
fun PortScanScreen(navController: NavHostController) {
    var host by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current
    val commonPorts = listOf(21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 1433, 1521, 3306, 3389, 5432, 6379, 7001, 8000, 8080, 8443, 8888, 9090)

    ToolPage("端口扫描", navController) {
        OutlinedTextField(host, { host = it }, Modifier.fillMaxWidth(),
            label = { Text("目标 IP 或域名") }, singleLine = true)
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                val h = host.trim()
                if (h.isEmpty()) { showToast(ctx, "请输入目标地址"); return@Button }
                scope.launch {
                    running = true
                    result = ""
                    result = scanPorts(h, commonPorts)
                    running = false
                }
            },
            enabled = !running,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (running) "扫描中…" else "扫描常用端口") }
        Spacer(Modifier.height(12.dp))
        Text("开放端口", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(
            result.ifBlank { "尚未扫描" },
            fontSize = 13.sp,
            color = TextMain,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.verticalScroll(rememberScrollState()),
        )
    }
}

private suspend fun scanPorts(host: String, ports: List<Int>): String = withContext(Dispatchers.IO) {
    coroutineScope {
        val open = ports.map { p ->
            async {
                val ok = try {
                    Socket().use { s -> s.connect(InetSocketAddress(host, p), 600); true }
                } catch (e: Exception) { false }
                if (ok) p else null
            }
        }.awaitAll().filterNotNull()
        if (open.isEmpty()) "未发现开放端口"
        else open.joinToString("\n") { "开放：$it" }
    }
}

// ===================== DNS 查询 =====================
@Composable
fun DnsScreen(navController: NavHostController) {
    var host by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    ToolPage("DNS 查询", navController) {
        OutlinedTextField(host, { host = it }, Modifier.fillMaxWidth(),
            label = { Text("域名（如 baidu.com）") }, singleLine = true)
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                val h = host.trim()
                if (h.isEmpty()) { showToast(ctx, "请输入域名"); return@Button }
                scope.launch {
                    result = withContext(Dispatchers.IO) {
                        try {
                            InetAddress.getAllByName(h).joinToString("\n") { it.hostAddress }
                        } catch (e: Exception) { "解析失败：${e.message}" }
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("查询") }
        Spacer(Modifier.height(12.dp))
        Text("解析结果", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(result.ifBlank { "尚未查询" }, fontSize = 14.sp, color = TextMain, fontFamily = FontFamily.Monospace)
    }
}

// ===================== 公网 IP =====================
@Composable
fun PublicIpScreen(navController: NavHostController) {
    var result by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val client = remember { OkHttpClient() }

    ToolPage("公网 IP", navController) {
        Text("查询本机对外出口的公网 IP 地址", fontSize = 13.sp, color = TextSub)
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                scope.launch {
                    running = true
                    result = ""
                    result = withContext(Dispatchers.IO) {
                        val urls = listOf(
                            "https://api.ipify.org",
                            "https://ipv4.icanhazip.com",
                            "https://ipinfo.io/ip",
                        )
                        for (u in urls) {
                            try {
                                val resp = client.newCall(Request.Builder().url(u).build()).execute()
                                if (resp.isSuccessful) {
                                    val ip = resp.body?.string()?.trim()
                                    if (!ip.isNullOrBlank()) return@withContext ip
                                }
                            } catch (e: Exception) { /* 尝试下一个 */ }
                        }
                        "查询失败，请检查网络"
                    }
                    running = false
                }
            },
            enabled = !running,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (running) "查询中…" else "查询公网 IP") }
        Spacer(Modifier.height(16.dp))
        Text("公网 IP 地址", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(result.ifBlank { "尚未查询" }, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = TextMain)
    }
}
