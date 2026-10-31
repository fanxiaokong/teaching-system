package com.teachingsystem.web.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
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
import com.teachingsystem.web.data.Api
import com.teachingsystem.web.data.ApiException
import com.teachingsystem.web.data.Session
import com.teachingsystem.web.ui.Routes
import com.teachingsystem.web.ui.SimpleTopBar
import com.teachingsystem.web.ui.goBackOrHome
import com.teachingsystem.web.ui.showToast
import com.teachingsystem.web.ui.theme.Background
import com.teachingsystem.web.ui.theme.CardBg
import com.teachingsystem.web.ui.theme.Primary
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub

@Composable
fun ReportScreen(navController: NavHostController) {
    val loggedIn = Session.token.value.isNotEmpty()
    var report by remember { mutableStateOf<JSONObject?>(null) }
    var name by remember { mutableStateOf("") }
    var college by remember { mutableStateOf("人工智能学院") }
    var majorClass by remember { mutableStateOf("") }
    var joinedQq by remember { mutableStateOf(false) }
    var agreed by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(loggedIn) {
        if (loggedIn) {
            try {
                report = Api.get("/api/v1/report").optJSONObject("report")
            } catch (e: Exception) {
                // 忽略，未登录/无记录时为空
            }
        }
    }

    fun submit() {
        if (name.isBlank() || college.isBlank() || majorClass.isBlank()) {
            showToast(ctx, "姓名、学院、专业班级都要填"); return
        }
        if (!agreed) {
            showToast(ctx, "请先阅读并同意隐私政策和用户协议"); return
        }
        scope.launch {
            loading = true
            try {
                val data = Api.post(
                    "/api/v1/report",
                    JSONObject()
                        .put("name", name.trim())
                        .put("college", college.trim())
                        .put("major_class", majorClass.trim())
                        .put("joined_qq", if (joinedQq) "1" else "0"),
                )
                report = data.optJSONObject("report")
                showToast(ctx, "报到申请已提交")
            } catch (e: ApiException) {
                showToast(ctx, e.message)
            } catch (e: Exception) {
                showToast(ctx, "网络错误")
            }
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("报到登记", onBack = { navController.goBackOrHome() })

        if (!loggedIn) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("登录后提交报到申请", color = TextSub)
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
                // 状态展示
                if (report != null) {
                    val status = report!!.optString("status")
                    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg), shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.padding(16.dp)) {
                            when (status) {
                                "pending" -> {
                                    Text("报到申请已提交", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain)
                                    Text("正在审核中，请耐心等待管理员审批。", fontSize = 13.sp, color = TextSub)
                                }
                                "approved" -> {
                                    Text("✓ 报到已通过", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = Primary)
                                    Text("${report!!.optString("name")} · ${report!!.optString("college")} · ${report!!.optString("major_class")}", fontSize = 13.sp, color = TextSub)
                                }
                                else -> {
                                    Text("报到被退回", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain)
                                    Text("请修改信息后重新提交。", fontSize = 13.sp, color = TextSub)
                                }
                            }
                        }
                    }
                }

                // 表单（未提交 或 被退回 时显示）
                val showForm = report == null || report!!.optString("status") == "rejected"
                if (showForm) {
                    Text("报到登记", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextMain)
                    Text("填写真实信息提交报到，管理员审核通过后完成报到。", fontSize = 13.sp, color = TextSub)
                    OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("姓名") }, singleLine = true)
                    OutlinedTextField(college, { college = it }, Modifier.fillMaxWidth(), label = { Text("学院（自动填写）") }, singleLine = true, readOnly = true)
                    OutlinedTextField(majorClass, { majorClass = it }, Modifier.fillMaxWidth(), label = { Text("专业班级") }, singleLine = true)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(joinedQq, { joinedQq = it })
                        Text("我已加入实验室官方 QQ 群", fontSize = 14.sp, color = TextMain)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(agreed, { agreed = it })
                        Text("我已阅读并同意", fontSize = 13.sp, color = TextSub)
                        TextButton(onClick = { navController.navigate(Routes.AGREEMENT) }) { Text("用户协议", fontSize = 13.sp) }
                        Text("和", fontSize = 13.sp, color = TextSub)
                        TextButton(onClick = { navController.navigate(Routes.PRIVACY) }) { Text("隐私政策", fontSize = 13.sp) }
                    }
                    Button(onClick = { submit() }, Modifier.fillMaxWidth(), enabled = !loading) {
                        if (loading) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text("提交报到")
                    }
                }
            }
        }
    }
}
