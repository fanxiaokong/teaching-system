package com.teachingsystem.web.ui.screens

import android.graphics.Bitmap
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import com.google.zxing.BarcodeFormat
import com.google.zxing.common.BitMatrix
import com.google.zxing.qrcode.QRCodeWriter
import com.teachingsystem.web.ui.showToast
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub
import java.net.URLDecoder
import java.net.URLEncoder
import java.security.MessageDigest

// ===================== 二维码生成 =====================
@Composable
fun QrGenScreen(navController: NavHostController) {
    var text by remember { mutableStateOf("") }
    var bitmap by remember { mutableStateOf<Bitmap?>(null) }
    val ctx = LocalContext.current

    ToolPage("二维码生成", navController) {
        OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth(),
            label = { Text("输入文字或链接") }, minLines = 3)
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                val t = text.trim()
                if (t.isEmpty()) { showToast(ctx, "请输入内容"); return@Button }
                bitmap = try { generateQrBitmap(t, 600) } catch (e: Exception) {
                    showToast(ctx, "生成失败：${e.message}"); null
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("生成二维码") }
        Spacer(Modifier.height(16.dp))
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            bitmap?.let {
                Image(it.asImageBitmap(), contentDescription = "二维码",
                    modifier = Modifier.size(240.dp))
            }
        }
    }
}

private fun generateQrBitmap(text: String, size: Int): Bitmap {
    val matrix: BitMatrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size)
    val pixels = IntArray(size * size)
    for (y in 0 until size) for (x in 0 until size) {
        pixels[y * size + x] = if (matrix[x, y]) 0xFF000000.toInt() else 0xFFFFFFFF.toInt()
    }
    return Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        .apply { setPixels(pixels, 0, size, 0, 0, size, size) }
}

// ===================== Base64 编解码 =====================
@Composable
fun Base64Screen(navController: NavHostController) {
    var input by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    val ctx = LocalContext.current

    ToolPage("Base64 编解码", navController) {
        OutlinedTextField(input, { input = it }, Modifier.fillMaxWidth(),
            label = { Text("输入内容") }, minLines = 4)
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth()) {
            Button(
                onClick = {
                    val t = input
                    if (t.isEmpty()) { showToast(ctx, "请输入内容"); return@Button }
                    output = try { Base64.encodeToString(t.toByteArray(), Base64.NO_WRAP) }
                    catch (e: Exception) { "编码失败：${e.message}" }
                },
                modifier = Modifier.weight(1f),
            ) { Text("编码") }
            Spacer(Modifier.size(12.dp))
            OutlinedButton(
                onClick = {
                    val t = input.trim()
                    if (t.isEmpty()) { showToast(ctx, "请输入内容"); return@OutlinedButton }
                    output = try { String(Base64.decode(t, Base64.DEFAULT)) }
                    catch (e: Exception) { "解码失败（不是合法 Base64）" }
                },
                modifier = Modifier.weight(1f),
            ) { Text("解码") }
        }
        Spacer(Modifier.height(12.dp))
        Text("结果", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(output, fontSize = 13.sp, color = TextMain, fontFamily = FontFamily.Monospace,
            modifier = Modifier.verticalScroll(rememberScrollState()))
    }
}

// ===================== URL 编解码 =====================
@Composable
fun UrlScreen(navController: NavHostController) {
    var input by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    val ctx = LocalContext.current

    ToolPage("URL 编解码", navController) {
        OutlinedTextField(input, { input = it }, Modifier.fillMaxWidth(),
            label = { Text("输入内容") }, minLines = 4)
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth()) {
            Button(
                onClick = {
                    val t = input
                    if (t.isEmpty()) { showToast(ctx, "请输入内容"); return@Button }
                    output = try { URLEncoder.encode(t, "UTF-8") }
                    catch (e: Exception) { "编码失败：${e.message}" }
                },
                modifier = Modifier.weight(1f),
            ) { Text("编码") }
            Spacer(Modifier.size(12.dp))
            OutlinedButton(
                onClick = {
                    val t = input
                    if (t.isEmpty()) { showToast(ctx, "请输入内容"); return@OutlinedButton }
                    output = try { URLDecoder.decode(t, "UTF-8") }
                    catch (e: Exception) { "解码失败：${e.message}" }
                },
                modifier = Modifier.weight(1f),
            ) { Text("解码") }
        }
        Spacer(Modifier.height(12.dp))
        Text("结果", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(output, fontSize = 13.sp, color = TextMain, fontFamily = FontFamily.Monospace,
            modifier = Modifier.verticalScroll(rememberScrollState()))
    }
}

// ===================== 哈希计算 =====================
@Composable
fun HashScreen(navController: NavHostController) {
    var input by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    val ctx = LocalContext.current
    val algos = listOf("MD5", "SHA-1", "SHA-256", "SHA-512")

    ToolPage("哈希计算", navController) {
        OutlinedTextField(input, { input = it }, Modifier.fillMaxWidth(),
            label = { Text("输入内容") }, minLines = 3)
        Spacer(Modifier.height(12.dp))
        algos.chunked(2).forEach { rowAlgos ->
            Row(Modifier.fillMaxWidth()) {
                rowAlgos.forEach { algo ->
                    Button(
                        onClick = {
                            val t = input
                            if (t.isEmpty()) { showToast(ctx, "请输入内容"); return@Button }
                            output = try { hash(t, algo) }
                            catch (e: Exception) { "计算失败：${e.message}" }
                        },
                        modifier = Modifier.weight(1f).padding(horizontal = 4.dp),
                    ) { Text(algo) }
                }
                if (rowAlgos.size == 1) Spacer(Modifier.weight(1f))
            }
            Spacer(Modifier.height(10.dp))
        }
        Spacer(Modifier.height(4.dp))
        Text("结果", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        Text(output, fontSize = 13.sp, color = TextMain, fontFamily = FontFamily.Monospace,
            modifier = Modifier.verticalScroll(rememberScrollState()))
    }
}

private fun hash(input: String, algo: String): String {
    val md = MessageDigest.getInstance(algo)
    return md.digest(input.toByteArray()).joinToString("") { "%02x".format(it) }
}
