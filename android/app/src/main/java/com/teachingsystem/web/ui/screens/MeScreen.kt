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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import kotlinx.coroutines.launch
import org.json.JSONObject
import com.teachingsystem.web.BuildConfig
import com.teachingsystem.web.data.Api
import com.teachingsystem.web.data.ApiException
import com.teachingsystem.web.data.Session
import com.teachingsystem.web.ui.Routes
import com.teachingsystem.web.ui.UpdateCenter
import com.teachingsystem.web.ui.showToast
import com.teachingsystem.web.ui.theme.Background
import com.teachingsystem.web.ui.theme.CardBg
import com.teachingsystem.web.ui.theme.Primary
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub

@Composable
fun MeScreen(navController: NavHostController) {
    val loggedIn = Session.token.value.isNotEmpty()
    val user = Session.user.value
    var needActivate by remember { mutableStateOf(user != null && !user.optBoolean("is_activated")) }
    var code by remember { mutableStateOf("") }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(loggedIn) {
        if (loggedIn) {
            try {
                val data = Api.get("/api/v1/me")
                val u = data.optJSONObject("user")
                if (u != null) {
                    Session.saveUser(u)
                    needActivate = !u.optBoolean("is_activated")
                }
            } catch (e: Exception) {
                // 忽略，基本信息已从本地读取
            }
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        Box(
            Modifier
                .fillMaxWidth()
                .background(Primary)
                .padding(horizontal = 20.dp, vertical = 16.dp)
        ) {
            Text("我的", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        }

        if (!loggedIn) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("登录后查看课程进度、下载课件", color = TextSub)
                    Spacer(Modifier.height(16.dp))
                    Button(onClick = { navController.navigate(Routes.LOGIN) }) { Text("登录 / 注册") }
                }
            }
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                // 用户卡片
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                    Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            Modifier
                                .size(56.dp)
                                .background(Primary, CircleShape),
                            contentAlignment = Alignment.Center,
                        ) {
                            val name = user?.optString("nickname")?.ifBlank { user?.optString("username") } ?: "?"
                            Text(name.take(1), color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.padding(start = 14.dp))
                        Column {
                            Text(user?.optString("nickname")?.ifBlank { user?.optString("username") } ?: "", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextMain)
                            if (!user?.optString("phone").isNullOrBlank()) {
                                Text(user!!.optString("phone"), fontSize = 13.sp, color = TextSub)
                            }
                        }
                    }
                }

                // 激活码（未激活时显示）
                if (needActivate) {
                    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                        Column(Modifier.padding(20.dp)) {
                            Text("账号未激活", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = TextMain)
                            Text("输入激活码后可下载课程资料", fontSize = 13.sp, color = TextSub)
                            Spacer(Modifier.height(10.dp))
                            OutlinedTextField(code, { code = it }, Modifier.fillMaxWidth(), label = { Text("激活码") }, singleLine = true)
                            Spacer(Modifier.height(10.dp))
                            Button(
                                onClick = {
                                    val c = code.trim()
                                    if (c.isEmpty()) { showToast(ctx, "请输入激活码"); return@Button }
                                    scope.launch {
                                        try {
                                            Api.post("/api/v1/activate", JSONObject().put("code", c))
                                            showToast(ctx, "激活成功")
                                            needActivate = false
                                            code = ""
                                            // 刷新 me
                                            Api.get("/api/v1/me").optJSONObject("user")?.let { Session.saveUser(it) }
                                        } catch (e: ApiException) {
                                            showToast(ctx, e.message)
                                        } catch (e: Exception) {
                                            showToast(ctx, "网络错误")
                                        }
                                    }
                                },
                            ) { Text("激活") }
                        }
                    }
                }

                // 功能入口
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                    Column(Modifier.padding(vertical = 6.dp)) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { navController.navigate(Routes.REPORT) }
                                .padding(horizontal = 20.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("📝 报到登记", fontSize = 15.sp, color = TextMain)
                            Spacer(Modifier.weight(1f))
                            Text("›", fontSize = 18.sp, color = TextSub)
                        }
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { UpdateCenter.manualCheck.value++ }
                                .padding(horizontal = 20.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("🔄 检查更新", fontSize = 15.sp, color = TextMain)
                            Spacer(Modifier.weight(1f))
                            Text("›", fontSize = 18.sp, color = TextSub)
                        }
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 20.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("当前版本", fontSize = 15.sp, color = TextMain)
                            Spacer(Modifier.weight(1f))
                            Text(
                                "v${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                                fontSize = 13.sp,
                                color = TextSub,
                            )
                        }
                    }
                }

                // 协议入口
                Row {
                    TextButton(onClick = { navController.navigate(Routes.AGREEMENT) }) { Text("用户协议", color = TextSub) }
                    TextButton(onClick = { navController.navigate(Routes.PRIVACY) }) { Text("隐私政策", color = TextSub) }
                }

                OutlinedButton(
                    onClick = {
                        Session.logout()
                        showToast(ctx, "已退出登录")
                    },
                    Modifier.fillMaxWidth(),
                ) { Text("退出登录", color = TextSub) }
            }
        }
    }
}
