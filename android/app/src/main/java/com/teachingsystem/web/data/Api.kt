package com.teachingsystem.web.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

const val BASE_URL = "https://your-server.example.com"

/** 后端返回的业务错误 */
class ApiException(override val message: String) : Exception(message)

/** 登录态（token + 用户信息）本地存储 */
class AuthStore(context: Context) {
    private val sp: SharedPreferences =
        context.getSharedPreferences("teaching_system_auth", Context.MODE_PRIVATE)

    fun save(token: String, userJson: String) {
        sp.edit().putString("token", token).putString("user", userJson).apply()
    }

    fun saveUser(userJson: String) {
        sp.edit().putString("user", userJson).apply()
    }

    fun token(): String = sp.getString("token", "") ?: ""
    fun userJson(): String? = sp.getString("user", null)
    fun isLoggedIn(): Boolean = token().isNotEmpty()

    fun logout() {
        sp.edit().remove("token").remove("user").apply()
    }
}

/** 统一网络层：自动带 Bearer token，解析 { ok, data, error } */
object Api {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    @Volatile
    var tokenProvider: () -> String = { "" }

    suspend fun get(path: String): JSONObject = request(path, "GET", null)
    suspend fun post(path: String, body: JSONObject): JSONObject = request(path, "POST", body)

    /** multipart 上传单个文件，返回 { ok, data, error } */
    suspend fun upload(
        path: String,
        fieldName: String,
        fileName: String,
        bytes: ByteArray,
        contentType: String,
    ): JSONObject = withContext(Dispatchers.IO) {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart(fieldName, fileName, bytes.toRequestBody(contentType.toMediaType()))
            .build()
        val rb = Request.Builder().url(BASE_URL + path).post(body)
        val token = tokenProvider()
        if (token.isNotEmpty()) rb.header("Authorization", "Bearer $token")
        client.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string() ?: ""
            val json = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
            if (json.optBoolean("ok")) {
                json.opt("data") as? JSONObject ?: JSONObject()
            } else {
                val err = json.optString("error")
                throw ApiException(if (err.isBlank()) "上传失败(${resp.code})" else err)
            }
        }
    }

    /** 下载到本地文件（带 Bearer），失败抛 ApiException */
    suspend fun download(path: String, dest: File) = withContext(Dispatchers.IO) {
        val rb = Request.Builder().url(BASE_URL + path)
        val token = tokenProvider()
        if (token.isNotEmpty()) rb.header("Authorization", "Bearer $token")
        client.newCall(rb.build()).execute().use { resp ->
            if (!resp.isSuccessful) {
                val text = resp.body?.string() ?: ""
                val err = try { JSONObject(text).optString("error") } catch (e: Exception) { "" }
                throw ApiException(if (err.isBlank()) "下载失败(${resp.code})" else err)
            }
            dest.parentFile?.mkdirs()
            resp.body?.byteStream()?.use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
        }
    }

    private suspend fun request(path: String, method: String, body: JSONObject?): JSONObject =
        withContext(Dispatchers.IO) {
            val rb = Request.Builder().url(BASE_URL + path)
            val token = tokenProvider()
            if (token.isNotEmpty()) rb.header("Authorization", "Bearer $token")
            if (body != null) {
                rb.post(body.toString().toRequestBody("application/json".toMediaType()))
            }
            client.newCall(rb.build()).execute().use { resp ->
                val text = resp.body?.string() ?: ""
                val json = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
                if (json.optBoolean("ok")) {
                    json.opt("data") as? JSONObject ?: JSONObject()
                } else {
                    val err = json.optString("error")
                    throw ApiException(if (err.isBlank()) "请求失败(${resp.code})" else err)
                }
            }
        }
}

// ===== 首页数据模型（字段与后端 /api/v1/home 一致）=====
data class TileLink(val title: String, val url: String, val icon: String)
data class TileGroup(val name: String, val links: List<TileLink>)
data class HomeData(
    val heroTag: String,
    val heroTitle: String,
    val heroDesc: String,
    val joinOpen: Boolean,
    val siteIntro: String,
    val groupQrcode: String,
    val statsTotal: String,
    val statsToday: String,
    val statsRate: String,
    val groups: List<TileGroup>,
)

fun parseHome(data: JSONObject): HomeData {
    val groups = mutableListOf<TileGroup>()
    val gArr = data.optJSONArray("tile_groups")
    if (gArr != null) {
        for (i in 0 until gArr.length()) {
            val g = gArr.optJSONObject(i) ?: continue
            val links = mutableListOf<TileLink>()
            val lArr = g.optJSONArray("links")
            if (lArr != null) {
                for (j in 0 until lArr.length()) {
                    val l = lArr.optJSONObject(j) ?: continue
                    links.add(
                        TileLink(
                            title = l.optString("title"),
                            url = l.optString("url"),
                            icon = l.optString("icon"),
                        )
                    )
                }
            }
            groups.add(TileGroup(name = g.optString("name"), links = links))
        }
    }
    val stats = data.optJSONObject("stats")
    return HomeData(
        heroTag = data.optString("hero_tag"),
        heroTitle = data.optString("hero_title"),
        heroDesc = data.optString("hero_desc"),
        joinOpen = data.optBoolean("join_open"),
        siteIntro = data.optString("site_intro"),
        groupQrcode = data.optString("group_qrcode"),
        statsTotal = stats?.optString("total") ?: "",
        statsToday = stats?.optString("today") ?: "",
        statsRate = stats?.optString("rate") ?: "",
        groups = groups,
    )
}
