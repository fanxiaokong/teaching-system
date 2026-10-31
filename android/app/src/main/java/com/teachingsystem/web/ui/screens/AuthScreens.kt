package com.teachingsystem.web.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
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
import com.teachingsystem.web.ui.theme.Primary
import com.teachingsystem.web.ui.theme.TextSub

@Composable
fun LoginScreen(navController: NavHostController) {
    var identifier by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var agreed by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    fun submit() {
        if (identifier.isBlank() || password.isBlank()) {
            showToast(ctx, "请输入账号和密码"); return
        }
        if (!agreed) {
            showToast(ctx, "请先勾选同意用户服务协议和隐私政策"); return
        }
        scope.launch {
            loading = true
            try {
                val data = Api.post(
                    "/api/v1/login",
                    JSONObject().put("identifier", identifier.trim()).put("password", password),
                )
                Session.saveLogin(data.optString("token"), data.optJSONObject("user") ?: JSONObject())
                showToast(ctx, "登录成功")
                navController.goBackOrHome()
            } catch (e: ApiException) {
                showToast(ctx, e.message)
            } catch (e: Exception) {
                showToast(ctx, "网络错误")
            }
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("登录", onBack = { navController.goBackOrHome() })
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("欢迎回来", fontSize = 24.sp, color = Primary)
            OutlinedTextField(identifier, { identifier = it }, Modifier.fillMaxWidth(), label = { Text("学号 / 手机号 / 用户名") }, singleLine = true)
            OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("密码") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(agreed, { agreed = it })
                Text("我已阅读并同意", fontSize = 13.sp, color = TextSub)
                TextButton(onClick = { navController.navigate(Routes.AGREEMENT) }) { Text("用户协议", fontSize = 13.sp) }
                Text("和", fontSize = 13.sp, color = TextSub)
                TextButton(onClick = { navController.navigate(Routes.PRIVACY) }) { Text("隐私政策", fontSize = 13.sp) }
            }
            Button(onClick = { submit() }, Modifier.fillMaxWidth(), enabled = !loading) {
                if (loading) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text("登录")
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                Text("还没有账号？", fontSize = 14.sp, color = TextSub)
                TextButton(onClick = { navController.navigate(Routes.REGISTER) }) { Text("去注册", color = Primary) }
            }
        }
    }
}

@Composable
fun RegisterScreen(navController: NavHostController) {
    var username by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var studentNo by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    var nickname by remember { mutableStateOf("") }
    var agreed by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    fun submit() {
        if (username.isBlank() || phone.isBlank() || studentNo.isBlank() || password.isBlank() || confirm.isBlank()) {
            showToast(ctx, "请填写完整信息"); return
        }
        if (password != confirm) {
            showToast(ctx, "两次输入的密码不一致"); return
        }
        if (!agreed) {
            showToast(ctx, "请先阅读并同意协议和隐私政策"); return
        }
        scope.launch {
            loading = true
            try {
                val data = Api.post(
                    "/api/v1/register",
                    JSONObject()
                        .put("username", username.trim())
                        .put("phone", phone.trim())
                        .put("student_no", studentNo.trim())
                        .put("password", password)
                        .put("confirm", confirm)
                        .put("nickname", nickname.trim()),
                )
                Session.saveLogin(data.optString("token"), data.optJSONObject("user") ?: JSONObject())
                showToast(ctx, "注册成功")
                navController.goBackOrHome()
            } catch (e: ApiException) {
                showToast(ctx, e.message)
            } catch (e: Exception) {
                showToast(ctx, "网络错误")
            }
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("注册", onBack = { navController.goBackOrHome() })
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("创建账号", fontSize = 24.sp, color = Primary)
            OutlinedTextField(username, { username = it }, Modifier.fillMaxWidth(), label = { Text("用户名") }, singleLine = true)
            OutlinedTextField(nickname, { nickname = it }, Modifier.fillMaxWidth(), label = { Text("昵称（选填）") }, singleLine = true)
            OutlinedTextField(phone, { phone = it }, Modifier.fillMaxWidth(), label = { Text("手机号") }, singleLine = true)
            OutlinedTextField(studentNo, { studentNo = it }, Modifier.fillMaxWidth(), label = { Text("学号") }, singleLine = true)
            OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("密码") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            OutlinedTextField(confirm, { confirm = it }, Modifier.fillMaxWidth(), label = { Text("确认密码") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(agreed, { agreed = it })
                Text("我已阅读并同意", fontSize = 13.sp, color = TextSub)
                TextButton(onClick = { navController.navigate(Routes.AGREEMENT) }) { Text("用户协议", fontSize = 13.sp) }
                Text("和", fontSize = 13.sp, color = TextSub)
                TextButton(onClick = { navController.navigate(Routes.PRIVACY) }) { Text("隐私政策", fontSize = 13.sp) }
            }
            Button(onClick = { submit() }, Modifier.fillMaxWidth(), enabled = !loading) {
                if (loading) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text("注册并登录")
            }
        }
    }
}
