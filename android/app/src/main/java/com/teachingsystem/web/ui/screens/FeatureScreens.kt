package com.teachingsystem.web.ui.screens

import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.OpenableColumns
import android.text.Html
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
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

private fun jsonArrayToList(arr: JSONArray?): List<JSONObject> {
    val list = mutableListOf<JSONObject>()
    if (arr == null) return list
    for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { list.add(it) }
    return list
}

private fun humanSize(bytes: Long): String {
    if (bytes <= 0) return "0 B"
    val units = arrayOf("B", "KB", "MB", "GB")
    var v = bytes.toDouble(); var i = 0
    while (v >= 1024 && i < units.size - 1) { v /= 1024; i++ }
    return "%.1f %s".format(v, units[i])
}

/** 从 content:// URI 读取文件名与 MIME 类型 */
private fun queryNameMime(ctx: Context, uri: Uri): Pair<String, String> {
    var name = "file"
    var mime = "application/octet-stream"
    try {
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (n >= 0) c.getString(n)?.let { name = it }
            }
        }
    } catch (e: Exception) { /* 忽略，用默认名 */ }
    try { ctx.contentResolver.getType(uri)?.let { mime = it } } catch (e: Exception) { /* 忽略 */ }
    return name to mime
}

// ===== 挑战列表 =====
@Composable
fun ChallengeScreen(navController: NavHostController) {
    var list by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun load() {
        scope.launch {
            loading = true
            error = null
            try {
                list = jsonArrayToList(Api.get("/api/v1/challenges").optJSONArray("challenges"))
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
        SimpleTopBar("挑战", onBack = { navController.goBackOrHome() })
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Primary) }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error!!, color = TextSub); Spacer(Modifier.height(10.dp))
                    Button(onClick = { load() }) { Text("重试") }
                }
            }
            list.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("暂无挑战", color = TextSub) }
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(list) { c ->
                    val diff = when (c.optInt("difficulty", 1)) { 1 -> "入门" 2 -> "进阶" else -> "高手" }
                    Card(
                        Modifier.fillMaxWidth().clickable { navController.navigate("challenge_detail/${c.optInt("id")}") },
                        colors = CardDefaults.cardColors(containerColor = CardBg), shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(c.optString("title").ifBlank { "未命名挑战" }, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain, modifier = Modifier.weight(1f))
                                Text(diff, fontSize = 12.sp, color = Primary)
                            }
                            val summary = c.optString("summary")
                            if (summary.isNotBlank()) { Spacer(Modifier.height(6.dp)); Text(summary, fontSize = 13.sp, color = TextSub, maxLines = 2) }
                        }
                    }
                }
            }
        }
    }
}

// ===== 挑战详情 =====
@Composable
fun ChallengeDetailScreen(navController: NavHostController, id: String) {
    var title by remember { mutableStateOf("挑战详情") }
    var summary by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }
    var deadline by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(id) {
        try {
            val c = Api.get("/api/v1/challenges/$id").optJSONObject("challenge")
            title = c?.optString("title")?.ifBlank { "挑战详情" } ?: "挑战详情"
            summary = c?.optString("summary") ?: ""
            content = c?.optString("content_html") ?: ""
            deadline = c?.optString("deadline") ?: ""
        } catch (e: ApiException) { error = e.message } catch (e: Exception) { error = "网络错误" }
        loading = false
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar(title, onBack = { navController.goBackOrHome() })
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Primary) }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(error!!, color = TextSub) }
            else -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                    Column(Modifier.padding(16.dp)) {
                        Text(summary.ifBlank { "暂无简介" }, fontSize = 14.sp, color = TextMain, lineHeight = 20.sp)
                        if (deadline.isNotBlank()) { Spacer(Modifier.height(8.dp)); Text("截止：$deadline", fontSize = 12.sp, color = TextSub) }
                    }
                }
                if (content.isNotBlank()) {
                    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                        Column(Modifier.padding(16.dp)) {
                            Text("挑战内容", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = TextMain)
                            Spacer(Modifier.height(8.dp))
                            Text(Html.fromHtml(content, Html.FROM_HTML_MODE_LEGACY).toString(), fontSize = 14.sp, color = TextSub, lineHeight = 21.sp)
                        }
                    }
                }
            }
        }
    }
}

// ===== 社区列表 =====
@Composable
fun CommunityScreen(navController: NavHostController) {
    var list by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var showCompose by remember { mutableStateOf(false) }
    var title by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }
    var atts by remember { mutableStateOf<List<Pair<Int, String>>>(emptyList()) }
    var posting by remember { mutableStateOf(false) }
    var uploadingAtt by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    fun load() {
        scope.launch {
            loading = true; error = null
            try {
                list = jsonArrayToList(Api.get("/api/v1/community").optJSONArray("posts"))
            } catch (e: ApiException) { error = e.message } catch (e: Exception) { error = "网络错误" }
            loading = false
        }
    }
    LaunchedEffect(Unit) { load() }

    // 发帖附件：选文件后上传，得到 file_id
    val attLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        scope.launch {
            uploadingAtt = true
            for (uri in uris) {
                try {
                    val (name, mime) = queryNameMime(ctx, uri)
                    val bytes = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: byteArrayOf()
                    if (bytes.isEmpty()) continue
                    val resp = Api.upload("/api/v1/community/upload", "file", name, bytes, mime)
                    val fid = resp.optInt("file_id")
                    if (fid > 0) atts = atts + (fid to name)
                } catch (e: Exception) { /* 跳过失败项 */ }
            }
            uploadingAtt = false
        }
    }

    fun submit() {
        if (title.isBlank() || content.isBlank()) { showToast(ctx, "标题和内容都要填"); return }
        scope.launch {
            posting = true
            try {
                val body = JSONObject().put("title", title.trim()).put("content", content.trim())
                val arr = JSONArray()
                atts.forEach { arr.put(it.first) }
                body.put("attachments", arr)
                Api.post("/api/v1/community", body)
                showToast(ctx, "发布成功")
                showCompose = false
                title = ""; content = ""; atts = emptyList()
                load()
            } catch (e: ApiException) { showToast(ctx, e.message) }
            catch (e: Exception) { showToast(ctx, "发布失败") }
            posting = false
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("社区", onBack = { navController.goBackOrHome() })
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Button(onClick = { showCompose = true }, modifier = Modifier.weight(1f)) { Text("发帖") }
        }
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Primary) }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error!!, color = TextSub); Spacer(Modifier.height(10.dp))
                    Button(onClick = { load() }) { Text("重试") }
                }
            }
            list.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("暂无帖子，点上方「发帖」聊聊", color = TextSub) }
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(list) { p ->
                    Card(
                        Modifier.fillMaxWidth().clickable { navController.navigate("community_detail/${p.optInt("id")}") },
                        colors = CardDefaults.cardColors(containerColor = CardBg), shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(p.optString("title").ifBlank { "无标题" }, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextMain)
                            Spacer(Modifier.height(6.dp))
                            Row {
                                Text(p.optString("nickname").ifBlank { p.optString("username") }, fontSize = 12.sp, color = TextSub, modifier = Modifier.weight(1f))
                                Text("💬 ${p.optInt("reply_count")}", fontSize = 12.sp, color = TextSub)
                            }
                        }
                    }
                }
            }
        }
    }

    if (showCompose) {
        AlertDialog(
            onDismissRequest = { if (!posting) showCompose = false },
            title = { Text("发帖") },
            text = {
                Column {
                    OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("标题") }, singleLine = true)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(content, { content = it }, Modifier.fillMaxWidth(), label = { Text("内容") }, minLines = 4)
                    Spacer(Modifier.height(8.dp))
                    Text("附件：${atts.size} 个", fontSize = 12.sp, color = TextSub)
                    atts.forEach { (_, n) -> Text("📎 $n", fontSize = 12.sp, color = TextMain, maxLines = 1) }
                }
            },
            confirmButton = {
                Button(onClick = { submit() }, enabled = !posting && !uploadingAtt) { Text(if (posting) "发布中…" else "发布") }
            },
            dismissButton = {
                Row {
                    OutlinedButton(onClick = { attLauncher.launch("*/*") }, enabled = !uploadingAtt) { Text(if (uploadingAtt) "上传中…" else "加附件") }
                    TextButton(onClick = { showCompose = false }) { Text("取消") }
                }
            },
        )
    }
}

// ===== 社区详情 + 回复 =====
@Composable
fun CommunityDetailScreen(navController: NavHostController, id: String) {
    var title by remember { mutableStateOf("帖子") }
    var content by remember { mutableStateOf("") }
    var author by remember { mutableStateOf("") }
    var replies by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var attachments by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var reply by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(true) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    fun load() {
        scope.launch {
            loading = true
            try {
                val data = Api.get("/api/v1/community/$id")
                val post = data.optJSONObject("post")
                title = post?.optString("title")?.ifBlank { "帖子" } ?: "帖子"
                content = post?.optString("content") ?: ""
                author = post?.optString("nickname")?.ifBlank { post?.optString("username") } ?: ""
                replies = jsonArrayToList(data.optJSONArray("replies"))
                attachments = jsonArrayToList(data.optJSONArray("attachments"))
            } catch (e: ApiException) { showToast(ctx, e.message) } catch (e: Exception) { showToast(ctx, "网络错误") }
            loading = false
        }
    }
    LaunchedEffect(id) { load() }

    fun downloadAtt(fid: Int, name: String) {
        scope.launch {
            try {
                val dir = ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: ctx.filesDir
                val dest = File(dir, name)
                Api.download("/api/v1/files/$fid/download", dest)
                showToast(ctx, "已保存：${dest.absolutePath}")
            } catch (e: ApiException) { showToast(ctx, e.message) }
            catch (e: Exception) { showToast(ctx, "下载失败") }
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar(title, onBack = { navController.goBackOrHome() })
        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Primary) }
        } else {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                    Column(Modifier.padding(16.dp)) {
                        if (author.isNotBlank()) { Text("作者：$author", fontSize = 12.sp, color = TextSub); Spacer(Modifier.height(6.dp)) }
                        Text(content.ifBlank { "（无内容）" }, fontSize = 14.sp, color = TextMain, lineHeight = 21.sp)
                    }
                }
                // 附件
                if (attachments.isNotEmpty()) {
                    Text("附件（${attachments.size}）", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = TextMain)
                    attachments.forEach { a ->
                        val fid = a.optInt("id")
                        val name = a.optString("original_name").ifBlank { "附件" }
                        val size = humanSize(a.optLong("size"))
                        val ext = name.substringAfterLast('.', "").lowercase()
                        if (ext in listOf("png", "jpg", "jpeg", "gif", "webp", "bmp")) {
                            AsyncImage(
                                model = "https://your-server.example.com/api/v1/files/$fid/download?token=${Session.token.value}",
                                contentDescription = name,
                                modifier = Modifier.fillMaxWidth().height(200.dp),
                                contentScale = ContentScale.Fit,
                            )
                        } else {
                            Card(
                                Modifier.fillMaxWidth().clickable { downloadAtt(fid, name) },
                                colors = CardDefaults.cardColors(containerColor = CardBg),
                            ) {
                                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                                    Text("📎", fontSize = 18.sp)
                                    Spacer(Modifier.padding(start = 10.dp))
                                    Column(Modifier.weight(1f)) {
                                        Text(name, fontSize = 13.sp, color = TextMain, maxLines = 1)
                                        Text(size, fontSize = 12.sp, color = TextSub)
                                    }
                                    Text("下载", fontSize = 13.sp, color = Primary)
                                }
                            }
                        }
                    }
                }
                Text("回复（${replies.size}）", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = TextMain)
                replies.forEach { r ->
                    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = CardBg)) {
                        Column(Modifier.padding(14.dp)) {
                            Text(r.optString("nickname").ifBlank { r.optString("username") }, fontSize = 12.sp, color = TextSub)
                            Spacer(Modifier.height(4.dp))
                            Text(r.optString("content"), fontSize = 14.sp, color = TextMain)
                        }
                    }
                }
                // 回复输入
                OutlinedTextField(reply, { reply = it }, Modifier.fillMaxWidth(), label = { Text("写下你的回复…") }, minLines = 2)
                Button(
                    onClick = {
                        if (reply.isBlank()) { showToast(ctx, "回复内容不能为空"); return@Button }
                        scope.launch {
                            try {
                                Api.post("/api/v1/community/$id/reply", JSONObject().put("content", reply.trim()))
                                reply = ""
                                showToast(ctx, "回复成功")
                                load()
                            } catch (e: ApiException) { showToast(ctx, e.message) } catch (e: Exception) { showToast(ctx, "网络错误") }
                        }
                    },
                    Modifier.fillMaxWidth(),
                ) { Text("回复") }
            }
        }
    }
}

// ===== 云盘 =====
@Composable
fun DriveScreen(navController: NavHostController) {
    var files by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var usage by remember { mutableStateOf("") }
    var quota by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var uploading by remember { mutableStateOf(false) }
    var downloadingId by remember { mutableStateOf<Int?>(null) }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    fun load() {
        scope.launch {
            loading = true; error = null
            try {
                val data = Api.get("/api/v1/drive")
                files = jsonArrayToList(data.optJSONArray("files"))
                val used = data.optJSONObject("usage")?.optLong("bytes") ?: 0L
                usage = humanSize(used)
                quota = "${data.optInt("quota")}"
            } catch (e: ApiException) { error = e.message } catch (e: Exception) { error = "网络错误" }
            loading = false
        }
    }
    LaunchedEffect(Unit) { load() }

    // 上传：系统文件选择器（多选）
    val pickLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        scope.launch {
            uploading = true
            var ok = 0; var fail = 0
            for (uri in uris) {
                try {
                    val (name, mime) = queryNameMime(ctx, uri)
                    val bytes = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: byteArrayOf()
                    if (bytes.isEmpty()) { fail++; continue }
                    Api.upload("/api/v1/drive/upload", "file", name, bytes, mime)
                    ok++
                } catch (e: Exception) { fail++ }
            }
            uploading = false
            showToast(ctx, if (fail == 0) "已上传 $ok 个文件" else "上传完成：成功 $ok，失败 $fail")
            load()
        }
    }

    // 下载：真正下载到本地（app 专属下载目录），不跳浏览器
    fun download(f: JSONObject) {
        val fid = f.optInt("id")
        val name = f.optString("original_name").ifBlank { "file" }
        scope.launch {
            downloadingId = fid
            try {
                val dir = ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: ctx.filesDir
                val dest = File(dir, name)
                Api.download("/api/v1/files/$fid/download", dest)
                showToast(ctx, "已保存：${dest.absolutePath}")
            } catch (e: ApiException) { showToast(ctx, e.message) }
            catch (e: Exception) { showToast(ctx, "下载失败") }
            downloadingId = null
        }
    }

    fun remove(f: JSONObject) {
        val fid = f.optInt("id")
        scope.launch {
            try {
                Api.post("/api/v1/drive/$fid/delete", JSONObject())
                showToast(ctx, "已删除")
                load()
            } catch (e: ApiException) { showToast(ctx, e.message) }
            catch (e: Exception) { showToast(ctx, "删除失败") }
        }
    }

    Column(Modifier.fillMaxSize().background(Background)) {
        SimpleTopBar("我的云盘", onBack = { navController.goBackOrHome() })
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Button(
                onClick = { pickLauncher.launch("*/*") },
                enabled = !uploading,
                modifier = Modifier.weight(1f),
            ) { Text(if (uploading) "上传中…" else "上传文件") }
        }
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Primary) }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error!!, color = TextSub); Spacer(Modifier.height(10.dp))
                    Button(onClick = { load() }) { Text("重试") }
                }
            }
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                item { Text("已用 $usage / 配额 $quota MB", fontSize = 13.sp, color = TextSub) }
                if (files.isEmpty()) item { Box(Modifier.fillMaxWidth().padding(vertical = 30.dp), contentAlignment = Alignment.Center) { Text("云盘为空，点上方「上传文件」添加", color = TextSub) } }
                items(files) { f ->
                    val fid = f.optInt("id")
                    val name = f.optString("original_name").ifBlank { f.optString("stored_name").ifBlank { "未命名文件" } }
                    val size = humanSize(f.optLong("size"))
                    Card(
                        Modifier.fillMaxWidth().clickable { download(f) },
                        colors = CardDefaults.cardColors(containerColor = CardBg), shape = RoundedCornerShape(12.dp),
                    ) {
                        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("📄", fontSize = 20.sp)
                            Spacer(Modifier.padding(start = 10.dp))
                            Column(Modifier.weight(1f)) {
                                Text(name, fontSize = 14.sp, color = TextMain, maxLines = 1)
                                Text(size, fontSize = 12.sp, color = TextSub)
                            }
                            if (downloadingId == fid) Text("下载中…", fontSize = 13.sp, color = TextSub)
                            else Text("下载", fontSize = 13.sp, color = Primary)
                            Spacer(Modifier.padding(start = 12.dp))
                            Text("🗑", fontSize = 16.sp, modifier = Modifier.clickable { remove(f) })
                        }
                    }
                }
            }
        }
    }
}
