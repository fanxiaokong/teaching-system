package com.teachingsystem.web.ui

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import com.google.zxing.integration.android.IntentIntegrator
import org.json.JSONObject
import com.teachingsystem.web.data.Api
import com.teachingsystem.web.data.Session

/**
 * 返回一个「触发扫码」的 lambda。点一下直接调起相机，扫完通过 [onResult] 回调：
 *  - 识别成功：content 为识别到的字符串
 *  - 取消 / 未识别：content 为 null
 * 不落地到任何中间页面，扫码界面关闭后停留原页面。
 */
@Composable
fun rememberScanLauncher(
    context: Context,
    onResult: (String?) -> Unit,
): () -> Unit {
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { activityResult ->
        val scan = IntentIntegrator.parseActivityResult(
            activityResult.resultCode, activityResult.data
        )
        onResult(scan?.contents)
    }
    return {
        val activity = context as? Activity
        if (activity != null) {
            val integrator = IntentIntegrator(activity)
            integrator.setDesiredBarcodeFormats(IntentIntegrator.ALL_CODE_TYPES)
            integrator.setPrompt("对准二维码或条码")
            integrator.setOrientationLocked(false) // 横竖屏都可扫（配合 manifest 里的 sensor 覆盖）
            integrator.setBeepEnabled(true)
            launcher.launch(integrator.createScanIntent())
        }
    }
}

/**
 * 处理扫码结果，返回一句给用户看的提示文案。
 * 登录码（/scan-login/）会直接调接口确认登录；普通内容自动复制到剪贴板。
 */
suspend fun processScanResult(context: Context, content: String): String {
    if (content.contains("/scan-login/")) {
        val token = content.substringAfter("/scan-login/").trim().trimEnd('/')
        if (!Session.isLoggedIn()) {
            return "请先在 App「我的」登录后再扫码登录"
        }
        return try {
            Api.post("/api/v1/scan/confirm", JSONObject().put("token", token))
            "✅ 已确认登录，请在网页端继续操作"
        } catch (e: Exception) {
            "确认失败：${e.message}"
        }
    }
    // 普通二维码 / 条码：复制到剪贴板，方便直接粘贴
    try {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("scan", content))
        return "已识别并复制：$content"
    } catch (e: Exception) {
        return "已识别：$content"
    }
}
