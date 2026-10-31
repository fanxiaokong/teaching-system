package com.teachingsystem.web.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import com.teachingsystem.web.BuildConfig
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream

/** 一次可用的更新信息 */
data class UpdateInfo(
    val versionCode: Int,
    val versionName: String,
    val releaseNotes: String,
    val downloadUrl: String,
    val fileSize: Long,
)

/** 版本检查结果 */
sealed class CheckResult {
    data class Available(val info: UpdateInfo) : CheckResult()
    object Latest : CheckResult()
    object NetworkError : CheckResult()
}

/** 在线更新：检查版本、下载 APK、调起系统安装器。 */
object Updater {

    private val client = OkHttpClient.Builder().build()

    /** 检查更新，返回三种结果：有新版本 / 已是最新 / 网络错误。 */
    suspend fun check(): CheckResult {
        return try {
            val data = Api.get("/api/v1/app/version")
            val code = data.optInt("version_code", 0)
            if (code <= BuildConfig.VERSION_CODE) CheckResult.Latest
            else CheckResult.Available(
                UpdateInfo(
                    versionCode = code,
                    versionName = data.optString("version_name"),
                    releaseNotes = data.optString("release_notes"),
                    downloadUrl = data.optString("download_url"),
                    fileSize = data.optLong("file_size", 0),
                )
            )
        } catch (e: Exception) {
            CheckResult.NetworkError
        }
    }

    /** 下载 APK 到应用缓存目录，回调 [onProgress]（0~100）。 */
    suspend fun download(
        context: Context,
        url: String,
        onProgress: (Int) -> Unit,
    ): File = withContext(Dispatchers.IO) {
        val dir = File(context.cacheDir, "apk").apply { mkdirs() }
        val file = File(dir, "update.apk")
        val fullUrl = if (url.startsWith("http")) url else BASE_URL + url
        val request = Request.Builder().url(fullUrl).build()
        client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) throw ApiException("下载失败(${resp.code})")
            val body = resp.body ?: throw ApiException("下载失败")
            val total = body.contentLength()
            val input: InputStream = body.byteStream()
            val output = FileOutputStream(file)
            val buffer = ByteArray(8192)
            var read: Int
            var loaded = 0L
            while (input.read(buffer).also { read = it } != -1) {
                output.write(buffer, 0, read)
                loaded += read
                if (total > 0) onProgress(((loaded * 100) / total).toInt())
            }
            output.close()
            input.close()
        }
        file
    }

    /** 调起系统安装器安装 [file]。 */
    fun install(context: Context, file: File) {
        val uri = FileProvider.getUriForFile(
            context, "${context.packageName}.fileprovider", file
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(intent)
    }
}
