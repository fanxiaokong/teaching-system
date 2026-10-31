package com.teachingsystem.web.ui.screens

import android.content.Intent
import android.net.Uri
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import com.teachingsystem.web.data.Api
import com.teachingsystem.web.data.ApiException
import com.teachingsystem.web.data.BASE_URL
import com.teachingsystem.web.data.HomeData
import com.teachingsystem.web.data.TileGroup
import com.teachingsystem.web.data.TileLink
import com.teachingsystem.web.data.parseHome
import com.teachingsystem.web.ui.Routes
import com.teachingsystem.web.ui.processScanResult
import com.teachingsystem.web.ui.rememberScanLauncher
import com.teachingsystem.web.ui.showToast
import com.teachingsystem.web.ui.theme.AppTheme
import com.teachingsystem.web.ui.theme.Background
import com.teachingsystem.web.ui.theme.CardBg
import com.teachingsystem.web.ui.theme.Primary
import com.teachingsystem.web.ui.theme.Secondary
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub

@Composable
fun HomeScreen(navController: NavHostController) {
    var home by remember { mutableStateOf<HomeData?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    fun load() {
        scope.launch {
            loading = true
            error = null
            try {
                home = parseHome(Api.get("/api/v1/home"))
            } catch (e: ApiException) {
                error = e.message
            } catch (e: Exception) {
                error = "网络错误，请检查网络后重试"
            }
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    // 扫码：点图标直接调相机，扫完即出结果，不跳中间页面
    val startScan = rememberScanLauncher(ctx) { content ->
        if (content.isNullOrBlank()) {
            showToast(ctx, "扫码已取消或未识别")
        } else {
            scope.launch {
                showToast(ctx, processScanResult(ctx, content))
            }
        }
    }

    HomeContent(
        home = home,
        loading = loading,
        error = error,
        onRetry = { load() },
        onJoin = { navController.navigate(Routes.JOIN) },
        onMe = { navController.navigate(Routes.ME) },
        onTapLink = { url -> handleLink(navController, ctx, url) },
        onOpenFeature = { route -> navController.navigate(route) },
        onScan = startScan,
    )
}

private fun handleLink(navController: NavHostController, ctx: android.content.Context, url: String) {
    if (url.isBlank()) return
    when {
        url.startsWith("http") -> {
            try {
                ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            } catch (e: Exception) {
                showToast(ctx, "无法打开链接")
            }
        }
        url.startsWith("/files") -> navController.navigate(Routes.FILES)
        url.startsWith("/challenges") -> navController.navigate(Routes.CHALLENGES)
        url.startsWith("/community") -> navController.navigate(Routes.COMMUNITY)
        url.startsWith("/drive") -> navController.navigate(Routes.DRIVE)
        else -> showToast(ctx, "该功能请在网页端使用")
    }
}

@Composable
private fun HomeContent(
    home: HomeData?,
    loading: Boolean,
    error: String?,
    onRetry: () -> Unit,
    onJoin: () -> Unit,
    onMe: () -> Unit,
    onTapLink: (String) -> Unit,
    onOpenFeature: (String) -> Unit,
    onScan: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .background(Background)
    ) {
        // 顶部标题栏（右侧扫码入口）
        Box(
            Modifier
                .fillMaxWidth()
                .background(Primary)
                .padding(horizontal = 20.dp, vertical = 10.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("教学管理系统", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                    Text("教学管理系统 · 站内导航", color = Color.White.copy(alpha = 0.85f), fontSize = 13.sp)
                }
                IconButton(onClick = onScan) {
                    Icon(
                        Icons.Filled.QrCodeScanner,
                        contentDescription = "扫一扫",
                        tint = Color.White,
                        modifier = Modifier.size(28.dp),
                    )
                }
            }
        }

        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Primary)
            }
            home == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error ?: "加载失败", color = TextSub)
                    Spacer(Modifier.height(12.dp))
                    Button(onClick = onRetry) { Text("重试") }
                }
            }
            else -> HomeBody(home!!, onJoin, onMe, onTapLink, onOpenFeature)
        }
    }
}

@Composable
private fun HomeBody(
    home: HomeData,
    onJoin: () -> Unit,
    onMe: () -> Unit,
    onTapLink: (String) -> Unit,
    onOpenFeature: (String) -> Unit,
) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Hero 区
        item {
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = Primary),
                shape = RoundedCornerShape(16.dp),
            ) {
                Column(Modifier.padding(20.dp)) {
                    if (home.heroTag.isNotBlank()) {
                        Text(
                            home.heroTag,
                            color = Color.White,
                            fontSize = 12.sp,
                            modifier = Modifier
                                .background(Secondary, RoundedCornerShape(6.dp))
                                .padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                        Spacer(Modifier.height(12.dp))
                    }
                    Text(home.heroTitle.ifBlank { "欢迎加入教学管理系统" }, color = Color.White, fontSize = 26.sp, fontWeight = FontWeight.Bold)
                    if (home.heroDesc.isNotBlank()) {
                        Spacer(Modifier.height(8.dp))
                        Text(home.heroDesc, color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp, lineHeight = 20.sp)
                    }
                    if (home.joinOpen) {
                        Spacer(Modifier.height(16.dp))
                        Row {
                            Button(
                                onClick = onJoin,
                                colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Primary),
                            ) { Text("加入我们") }
                            Spacer(Modifier.width(12.dp))
                            OutlinedButton(
                                onClick = onMe,
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                            ) { Text("我的中心") }
                        }
                    }
                }
            }
        }

        // 常用功能
        item {
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = CardBg),
                shape = RoundedCornerShape(16.dp),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("实验室功能", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain)
                    Spacer(Modifier.height(12.dp))
                    Row(Modifier.fillMaxWidth()) {
                        FeatureEntry("⚔️", "挑战", Modifier.weight(1f)) { onOpenFeature(Routes.CHALLENGES) }
                        FeatureEntry("💬", "社区", Modifier.weight(1f)) { onOpenFeature(Routes.COMMUNITY) }
                    }
                    Spacer(Modifier.height(10.dp))
                    Row(Modifier.fillMaxWidth()) {
                        FeatureEntry("☁️", "云盘", Modifier.weight(1f)) { onOpenFeature(Routes.DRIVE) }
                        FeatureEntry("📁", "文件中心", Modifier.weight(1f)) { onOpenFeature(Routes.FILES) }
                    }
                    Spacer(Modifier.height(10.dp))
                    Row(Modifier.fillMaxWidth()) {
                        FeatureEntry("🧰", "工具箱", Modifier.weight(1f)) { onOpenFeature(Routes.TOOLBOX) }
                        Spacer(Modifier.weight(1f))
                    }
                }
            }
        }

        // 磁贴分组
        home.groups.forEach { group ->
            item(key = "group_${group.name}") { GroupSection(group, onTapLink) }
        }

        // 招新统计
        if (home.joinOpen) {
            item {
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = CardBg),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Column(Modifier.padding(20.dp)) {
                        Text("招新进行中", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = TextMain)
                        if (home.siteIntro.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                            Text(home.siteIntro, fontSize = 13.sp, color = TextSub, lineHeight = 19.sp)
                        }
                        Spacer(Modifier.height(16.dp))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                            StatItem(home.statsTotal, "已报名")
                            StatItem(home.statsToday, "今日新增")
                            StatItem(home.statsRate, "愿进群")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun GroupSection(group: TileGroup, onTapLink: (String) -> Unit) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(width = 4.dp, height = 18.dp).background(Primary, RoundedCornerShape(2.dp)))
            Spacer(Modifier.width(8.dp))
            Text(group.name, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain)
            Spacer(Modifier.width(6.dp))
            Text("${group.links.size} 项", fontSize = 12.sp, color = TextSub)
        }
        Spacer(Modifier.height(10.dp))
        // 宫格：每行最多 3 个
        val cols = 3
        group.links.chunked(cols).forEach { rowLinks ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                rowLinks.forEach { link ->
                    LinkCard(link, Modifier.weight(1f), onTapLink)
                }
                repeat(cols - rowLinks.size) {
                    Spacer(Modifier.weight(1f))
                }
            }
            Spacer(Modifier.height(10.dp))
        }
    }
}

@Composable
private fun LinkCard(link: TileLink, modifier: Modifier, onTapLink: (String) -> Unit) {
    Card(
        modifier = modifier.clickable { onTapLink(link.url) },
        colors = CardDefaults.cardColors(containerColor = CardBg),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (link.icon.startsWith("/")) {
                AsyncImage(
                    model = BASE_URL + link.icon,
                    contentDescription = link.title,
                    modifier = Modifier.size(28.dp),
                )
            } else {
                Text(link.icon.ifBlank { "🔗" }, fontSize = 24.sp)
            }
            Spacer(Modifier.height(6.dp))
            Text(link.title, fontSize = 12.sp, color = TextMain, textAlign = TextAlign.Center, maxLines = 1)
        }
    }
}

@Composable
private fun StatItem(num: String, label: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(num.ifBlank { "0" }, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Primary)
        Spacer(Modifier.height(2.dp))
        Text(label, fontSize = 12.sp, color = TextSub)
    }
}

@Composable
private fun FeatureEntry(emoji: String, label: String, modifier: Modifier, onClick: () -> Unit) {
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
                .padding(vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(emoji, fontSize = 26.sp)
            Spacer(Modifier.height(6.dp))
            Text(label, fontSize = 13.sp, color = TextMain)
        }
    }
}

// ===== 预览 =====
@Preview(showBackground = true, widthDp = 360, heightDp = 720)
@Composable
private fun HomePreview() {
    AppTheme {
        HomeContent(
            home = HomeData(
                heroTag = "招新进行中",
                heroTitle = "教学管理系统",
                heroDesc = "我们正在招新，欢迎您点击下方按钮了解详情",
                joinOpen = true,
                siteIntro = "",
                groupQrcode = "",
                statsTotal = "25",
                statsToday = "1",
                statsRate = "96",
                groups = listOf(
                    TileGroup(
                        "实验室内部",
                        listOf(
                            TileLink("Docker", "https://docker.your-server.example.com", "🐳"),
                            TileLink("文件系统", "/files", "📁"),
                            TileLink("考试系统", "https://exam.your-server.example.com", "📝"),
                        ),
                    ),
                    TileGroup(
                        "常用站点",
                        listOf(
                            TileLink("DeepSeek", "https://chat.deepseek.com", "🤖"),
                            TileLink("CSDN", "https://www.csdn.net", "💻"),
                            TileLink("豆包", "https://www.doubao.com", "✨"),
                        ),
                    ),
                ),
            ),
            loading = false,
            error = null,
            onRetry = {},
            onJoin = {},
            onMe = {},
            onTapLink = {},
            onOpenFeature = {},
            onScan = {},
        )
    }
}
