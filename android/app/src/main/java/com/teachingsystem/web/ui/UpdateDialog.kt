package com.teachingsystem.web.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import com.teachingsystem.web.data.CheckResult
import com.teachingsystem.web.data.UpdateInfo
import com.teachingsystem.web.data.Updater
import com.teachingsystem.web.ui.theme.TextSub
import java.io.File

/** 全局更新触发中心。 */
object UpdateCenter {
    /** 启动时自动检查（初始值 0 触发一次，静默，已是最新不提示） */
    val requestCheck = mutableStateOf(0)
    /** 手动检查（每次 +1 触发，已是最新会提示） */
    val manualCheck = mutableStateOf(0)
}

private sealed class UpdateStage {
    object None : UpdateStage()
    object Checking : UpdateStage()
    data class Available(val info: UpdateInfo) : UpdateStage()
    data class Downloading(val progress: Int) : UpdateStage()
    data class Downloaded(val file: File) : UpdateStage()
}

/** 在线更新宿主：启动时自动检查一次；监听 [UpdateCenter.manualCheck] 响应手动「检查更新」。 */
@Composable
fun UpdateHost() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var stage by remember { mutableStateOf<UpdateStage>(UpdateStage.Checking) }

    LaunchedEffect(UpdateCenter.requestCheck.value) {
        if (stage is UpdateStage.Downloading || stage is UpdateStage.Downloaded) return@LaunchedEffect
        stage = UpdateStage.Checking
        val result = Updater.check()
        stage = if (result is CheckResult.Available) UpdateStage.Available(result.info) else UpdateStage.None
    }

    // 手动触发「检查更新」：已是最新 / 网络错误都给出明确提示
    LaunchedEffect(UpdateCenter.manualCheck.value) {
        if (UpdateCenter.manualCheck.value == 0) return@LaunchedEffect
        if (stage is UpdateStage.Downloading || stage is UpdateStage.Downloaded) return@LaunchedEffect
        stage = UpdateStage.Checking
        when (val result = Updater.check()) {
            is CheckResult.Available -> stage = UpdateStage.Available(result.info)
            CheckResult.Latest -> {
                stage = UpdateStage.None
                showToast(context, "当前已经是最新版本了")
            }
            CheckResult.NetworkError -> {
                stage = UpdateStage.None
                showToast(context, "网络异常，请稍后重试")
            }
        }
    }

    // 下载完成后自动调起系统安装器
    LaunchedEffect(stage) {
        val s = stage
        if (s is UpdateStage.Downloaded) {
            Updater.install(context, s.file)
            stage = UpdateStage.None
        }
    }

    when (val s = stage) {
        is UpdateStage.Available -> AvailableDialog(context, scope, s.info) { newStage ->
            stage = newStage
        }
        is UpdateStage.Downloading -> DownloadingDialog(s.progress)
        else -> {}
    }
}

@Composable
private fun AvailableDialog(
    context: Context,
    scope: kotlinx.coroutines.CoroutineScope,
    info: UpdateInfo,
    onStage: (UpdateStage) -> Unit,
) {
    AlertDialog(
        onDismissRequest = { onStage(UpdateStage.None) },
        title = { Text("发现新版本 v${info.versionName}") },
        text = { Text(info.releaseNotes.ifBlank { "有新版本可用，是否立即更新？" }) },
        confirmButton = {
            TextButton(onClick = {
                if (Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
                    // Android 8.0+ 需先授权「安装未知来源应用」
                    val intent = Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:${context.packageName}")
                    )
                    context.startActivity(intent)
                    showToast(context, "请允许安装未知应用，再回来点「检查更新」")
                    onStage(UpdateStage.None)
                } else {
                    scope.launch {
                        onStage(UpdateStage.Downloading(0))
                        try {
                            val file = Updater.download(context, info.downloadUrl) { p ->
                                onStage(UpdateStage.Downloading(p))
                            }
                            onStage(UpdateStage.Downloaded(file))
                        } catch (e: Exception) {
                            showToast(context, "下载失败，请重试")
                            onStage(UpdateStage.Available(info))
                        }
                    }
                }
            }) { Text("立即更新") }
        },
        dismissButton = {
            TextButton(onClick = { onStage(UpdateStage.None) }) { Text("暂不更新") }
        },
    )
}

@Composable
private fun DownloadingDialog(progress: Int) {
    AlertDialog(
        onDismissRequest = {},
        title = { Text("正在下载更新") },
        text = {
            Column {
                LinearProgressIndicator(
                    progress = { progress / 100f },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Text("$progress%", color = TextSub)
            }
        },
        confirmButton = {},
    )
}
