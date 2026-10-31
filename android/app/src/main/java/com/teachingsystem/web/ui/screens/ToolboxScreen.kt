package com.teachingsystem.web.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import kotlinx.coroutines.launch
import com.teachingsystem.web.ui.Routes
import com.teachingsystem.web.ui.SimpleTopBar
import com.teachingsystem.web.ui.goBackOrHome
import com.teachingsystem.web.ui.processScanResult
import com.teachingsystem.web.ui.rememberScanLauncher
import com.teachingsystem.web.ui.showToast
import com.teachingsystem.web.ui.theme.Background
import com.teachingsystem.web.ui.theme.CardBg
import com.teachingsystem.web.ui.theme.Primary
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub

private data class ToolGroup(val name: String, val items: List<ToolItem>)
private data class ToolItem(val emoji: String, val label: String, val desc: String, val route: String)

/** 特殊 route：表示直接调相机扫码，而不是跳转页面 */
private const val SCAN_ACTION = "__scan__"

@Composable
fun ToolboxScreen(navController: NavHostController) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // 扫码：点「扫一扫」直接调相机，扫完即出结果，不跳中间页面
    val startScan = rememberScanLauncher(context) { content ->
        if (content.isNullOrBlank()) {
            showToast(context, "扫码已取消或未识别")
        } else {
            scope.launch {
                showToast(context, processScanResult(context, content))
            }
        }
    }

    val groups = listOf(
        ToolGroup(
            "网络工具",
            listOf(
                ToolItem("📡", "Ping 测试", "测试主机连通性与延迟", Routes.TOOL_PING),
                ToolItem("🔍", "IP 扫描", "扫描局域网在线设备", Routes.TOOL_IPSCAN),
                ToolItem("🔌", "端口扫描", "探测目标开放端口", Routes.TOOL_PORTSCAN),
                ToolItem("🌐", "DNS 查询", "域名解析记录查询", Routes.TOOL_DNS),
                ToolItem("🌍", "公网 IP", "查看本机公网出口 IP", Routes.TOOL_PUBLIC_IP),
            ),
        ),
        ToolGroup(
            "扫码与编码",
            listOf(
                ToolItem("📷", "扫一扫", "扫描二维码 / 条码", SCAN_ACTION),
                ToolItem("🔳", "二维码生成", "文本转二维码图片", Routes.TOOL_QR),
                ToolItem("🔐", "Base64 编解码", "Base64 加密解密", Routes.TOOL_BASE64),
                ToolItem("🔗", "URL 编解码", "URL 转义与还原", Routes.TOOL_URL),
                ToolItem("#️⃣", "哈希计算", "MD5 / SHA 校验", Routes.TOOL_HASH),
            ),
        ),
        ToolGroup(
            "日常工具",
            listOf(
                ToolItem("📏", "单位换算", "长度/重量/温度等", Routes.TOOL_UNIT),
                ToolItem("🧮", "计算器", "基础四则运算", Routes.TOOL_CALC),
            ),
        ),
    )

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("工具箱", onBack = { navController.goBackOrHome() })
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            groups.forEach { group ->
                item(key = group.name) {
                    Card(
                        Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = CardBg),
                        shape = RoundedCornerShape(14.dp),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(group.name, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain)
                            Spacer(Modifier.height(12.dp))
                            group.items.chunked(2).forEach { rowItems ->
                                Row(Modifier.fillMaxWidth()) {
                                    rowItems.forEach { item ->
                                        ToolCell(item, Modifier.weight(1f)) {
                                            if (item.route == SCAN_ACTION) startScan()
                                            else navController.navigate(item.route)
                                        }
                                    }
                                    if (rowItems.size == 1) Spacer(Modifier.weight(1f))
                                }
                                Spacer(Modifier.height(10.dp))
                            }
                        }
                    }
                }
            }
            item { Spacer(Modifier.height(8.dp)) }
        }
    }
}

@Composable
private fun ToolCell(item: ToolItem, modifier: Modifier, onClick: () -> Unit) {
    Card(
        modifier = modifier
            .padding(horizontal = 4.dp)
            .clickable { onClick() },
        colors = CardDefaults.cardColors(containerColor = Background),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp, horizontal = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(item.emoji, fontSize = 26.sp)
            Spacer(Modifier.height(6.dp))
            Text(item.label, fontSize = 14.sp, color = TextMain, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(2.dp))
            Text(item.desc, fontSize = 11.sp, color = TextSub)
        }
    }
}

/** 通用：工具页顶部栏 + 内容容器 */
@Composable
fun ToolPage(title: String, navController: NavHostController, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar(title, onBack = { navController.goBackOrHome() })
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            content()
        }
    }
}
