package com.teachingsystem.web.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.core.content.FileProvider
import androidx.navigation.NavHostController
import android.content.Intent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import com.teachingsystem.web.data.Api
import com.teachingsystem.web.data.ApiException
import com.teachingsystem.web.data.BASE_URL
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
import java.io.File

// ===== 文件中心 =====
@Composable
fun FilesScreen(navController: NavHostController) {
    var files by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var total by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var downloadingId by remember { mutableStateOf<Int?>(null) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    fun load() {
        scope.launch {
            loading = true
            error = null
            try {
                val data = Api.get("/api/v1/files")
                val arr = data.optJSONArray("files") ?: JSONArray()
                val list = mutableListOf<JSONObject>()
                for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { list.add(it) }
                files = list
                total = data.optString("total")
            } catch (e: ApiException) {
                error = e.message
            } catch (e: Exception) {
                error = "网络错误"
            }
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("文件中心", onBack = { navController.goBackOrHome() })
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Primary) }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error!!, color = TextSub)
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = { load() }) { Text("重试") }
                }
            }
            files.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("暂无文件", color = TextSub) }
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (total.isNotBlank()) item { Text("共 $total 个文件", fontSize = 13.sp, color = TextSub) }
                items(files) { f ->
                    val fId = f.optInt("id")
                    val name = f.optString("title").ifBlank {
                        f.optString("original_name").ifBlank { "未命名文件" }
                    }
                    val meta = listOf(
                        f.optString("category"),
                        humanSize(f.optLong("size")),
                        f.optString("created_at").take(10),
                        f.optString("course_title"),
                    ).filter { it.isNotBlank() }.joinToString(" · ")
                    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                        Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("📄", fontSize = 20.sp)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) {
                                Text(name, fontSize = 14.sp, color = TextMain, fontWeight = FontWeight.Medium, maxLines = 2)
                                Spacer(Modifier.height(3.dp))
                                if (meta.isNotBlank()) Text(meta, fontSize = 12.sp, color = TextSub)
                            }
                            TextButton(
                                onClick = {
                                    if (Session.isLoggedIn()) {
                                        scope.launch {
                                            downloadingId = fId
                                            try {
                                                val file = downloadResourceFile(ctx, fId, name)
                                                val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", file)
                                                val intent = Intent(Intent.ACTION_VIEW).apply {
                                                    setDataAndType(uri, guessMime(name))
                                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                                                }
                                                ctx.startActivity(intent)
                                                showToast(ctx, "下载完成")
                                            } catch (e: Exception) {
                                                showToast(ctx, e.message ?: "下载失败")
                                            }
                                            downloadingId = null
                                        }
                                    } else {
                                        showToast(ctx, "请先登录后下载")
                                    }
                                },
                                enabled = downloadingId == null || downloadingId == fId,
                            ) {
                                Text(if (downloadingId == fId) "下载中" else "下载", fontSize = 13.sp)
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun humanSize(bytes: Long): String = when {
    bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1048576.0)
    bytes >= 1024 -> "%.1f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}

private fun guessMime(name: String): String {
    val ext = name.substringAfterLast('.', "").lowercase()
    return when (ext) {
        "pdf" -> "application/pdf"
        "zip" -> "application/zip"
        "rar" -> "application/x-rar-compressed"
        "7z" -> "application/x-7z-compressed"
        "doc" -> "application/msword"
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "xls" -> "application/vnd.ms-excel"
        "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "ppt" -> "application/vnd.ms-powerpoint"
        "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        "txt" -> "text/plain"
        "csv" -> "text/csv"
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        "gif" -> "image/gif"
        "webp" -> "image/webp"
        "mp4" -> "video/mp4"
        "mp3" -> "audio/mpeg"
        "wav" -> "audio/wav"
        else -> "application/octet-stream"
    }
}

private suspend fun downloadResourceFile(
    context: android.content.Context,
    fileId: Int,
    fileName: String,
): File = withContext(Dispatchers.IO) {
    val dir = File(context.cacheDir, "downloads").apply { mkdirs() }
    val safe = fileName.replace(Regex("""[\\/:*?"<>|\s]"""), "_").take(60)
    val file = File(dir, "${fileId}_$safe")
    val req = okhttp3.Request.Builder()
        .url(BASE_URL + "/api/v1/files/$fileId/download")
        .header("Authorization", "Bearer " + Session.token.value)
        .build()
    okhttp3.OkHttpClient().newCall(req).execute().use { resp ->
        if (!resp.isSuccessful) throw Exception("下载失败(${resp.code})")
        val body = resp.body ?: throw Exception("下载失败")
        body.byteStream().use { input -> file.outputStream().use { output -> input.copyTo(output) } }
    }
    file
}

// ===== 报名 =====
@Composable
fun JoinScreen(navController: NavHostController) {
    var name by remember { mutableStateOf("") }
    var college by remember { mutableStateOf("人工智能学院") }
    var contact by remember { mutableStateOf("") }
    var joinGroup by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf("") }
    var agreed by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var done by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    fun submit() {
        if (name.isBlank() || college.isBlank() || contact.isBlank()) {
            showToast(ctx, "姓名、学院、联系方式都要填"); return
        }
        if (!agreed) {
            showToast(ctx, "请先阅读并同意隐私政策"); return
        }
        scope.launch {
            loading = true
            try {
                Api.post(
                    "/api/v1/join",
                    JSONObject()
                        .put("name", name.trim())
                        .put("college", college.trim())
                        .put("contact", contact.trim())
                        .put("join_group", if (joinGroup) "1" else "0")
                        .put("note", note.trim()),
                )
                done = true
                showToast(ctx, "报名成功")
            } catch (e: ApiException) {
                showToast(ctx, e.message)
            } catch (e: Exception) {
                showToast(ctx, "网络错误")
            }
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("加入我们", onBack = { navController.goBackOrHome() })
        if (done) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("🎉 报名成功！", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Primary)
                    Spacer(Modifier.height(10.dp))
                    Text("我们会尽快联系你", fontSize = 14.sp, color = TextSub)
                }
            }
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("报名信息", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextMain)
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("姓名") }, singleLine = true)
                OutlinedTextField(college, { college = it }, Modifier.fillMaxWidth(), label = { Text("学院（自动填写）") }, singleLine = true, readOnly = true)
                OutlinedTextField(contact, { contact = it }, Modifier.fillMaxWidth(), label = { Text("联系方式（手机/QQ/微信）") }, singleLine = true)
                OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), label = { Text("备注（选填）") }, minLines = 2)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(joinGroup, { joinGroup = it })
                    Text("我愿意加入招新群", fontSize = 14.sp, color = TextMain)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(agreed, { agreed = it })
                    Text("我已阅读并同意", fontSize = 13.sp, color = TextSub)
                    TextButton(onClick = { navController.navigate(Routes.PRIVACY) }) { Text("隐私政策", fontSize = 13.sp) }
                }
                Button(onClick = { submit() }, Modifier.fillMaxWidth(), enabled = !loading) {
                    if (loading) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text("提交报名")
                }
            }
        }
    }
}

// ===== 静态协议页 =====
@Composable
fun StaticTextScreen(title: String, navController: NavHostController) {
    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar(title, onBack = { navController.goBackOrHome() })
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("$title\n\n（占位内容，后续从服务器拉取）", color = TextSub, fontSize = 14.sp, lineHeight = 22.sp)
        }
    }
}
