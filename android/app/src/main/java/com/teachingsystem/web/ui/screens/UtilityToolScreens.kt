package com.teachingsystem.web.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import com.teachingsystem.web.ui.theme.TextMain
import com.teachingsystem.web.ui.theme.TextSub
import kotlin.math.roundToInt

// ===================== 单位换算 =====================
private data class UnitDef(val name: String, val factor: Double) // factor 相对基准单位
private data class UnitCategory(val name: String, val base: String, val units: List<UnitDef>)

@Composable
fun UnitScreen(navController: NavHostController) {
    val categories = listOf(
        UnitCategory("长度", "米", listOf(
            UnitDef("米", 1.0), UnitDef("千米", 1000.0), UnitDef("厘米", 0.01),
            UnitDef("毫米", 0.001), UnitDef("英尺", 0.3048), UnitDef("英寸", 0.0254),
            UnitDef("英里", 1609.344),
        )),
        UnitCategory("重量", "千克", listOf(
            UnitDef("千克", 1.0), UnitDef("克", 0.001), UnitDef("吨", 1000.0),
            UnitDef("磅", 0.45359237), UnitDef("盎司", 0.0283495),
        )),
        UnitCategory("面积", "平方米", listOf(
            UnitDef("平方米", 1.0), UnitDef("平方千米", 1000000.0),
            UnitDef("公顷", 10000.0), UnitDef("亩", 666.667),
        )),
    )
    var catIndex by remember { mutableStateOf(0) }
    var unitIndex by remember { mutableStateOf(0) }
    var value by remember { mutableStateOf("") }

    val cat = categories[catIndex]

    ToolPage("单位换算", navController) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            categories.forEachIndexed { i, c ->
                FilterChip(
                    selected = i == catIndex,
                    onClick = { catIndex = i; unitIndex = 0 },
                    label = { Text(c.name) },
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(value, { value = it }, Modifier.fillMaxWidth(),
            label = { Text("数值") }, singleLine = true)
        Spacer(Modifier.height(12.dp))
        Text("输入单位", fontSize = 13.sp, color = TextSub)
        Spacer(Modifier.height(6.dp))
        cat.units.chunked(4).forEach { rowUnits ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                rowUnits.forEach { u ->
                    val idx = cat.units.indexOf(u)
                    FilterChip(
                        selected = idx == unitIndex,
                        onClick = { unitIndex = idx },
                        label = { Text(u.name) },
                    )
                }
            }
            Spacer(Modifier.height(6.dp))
        }
        Spacer(Modifier.height(8.dp))
        Text("换算结果", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = TextMain)
        Spacer(Modifier.height(8.dp))
        val v = value.toDoubleOrNull()
        Text(
            if (v == null) "请输入有效数值"
            else cat.units.filterIndexed { i, _ -> i != unitIndex }.joinToString("\n") { u ->
                val r = v * cat.units[unitIndex].factor / u.factor
                "%s %s = %s %s".format(fmt(v), cat.units[unitIndex].name, fmt(r), u.name)
            },
            fontSize = 14.sp, color = TextMain,
            modifier = Modifier.verticalScroll(rememberScrollState()),
        )
    }
}

private fun fmt(d: Double): String {
    val r = (d * 10000).roundToInt() / 10000.0
    return if (r == r.toLong().toDouble()) r.toLong().toString() else r.toString()
}

// ===================== 计算器 =====================
@Composable
fun CalcScreen(navController: NavHostController) {
    var display by remember { mutableStateOf("0") }
    var stored by remember { mutableStateOf(0.0) }
    var pendingOp by remember { mutableStateOf("") }
    var startNew by remember { mutableStateOf(true) }

    fun inputDigit(d: String) {
        display = if (startNew) d else display + d
        startNew = false
    }
    fun inputDot() {
        if (startNew) { display = "0."; startNew = false }
        else if (!display.contains('.')) display += "."
    }
    fun applyOp(op: String) {
        val cur = display.toDoubleOrNull() ?: 0.0
        if (pendingOp.isNotEmpty() && !startNew) {
            stored = compute(stored, cur, pendingOp)
            display = fmt(stored)
        } else {
            stored = cur
        }
        pendingOp = op
        startNew = true
    }
    fun equals() {
        val cur = display.toDoubleOrNull() ?: 0.0
        if (pendingOp.isNotEmpty()) {
            stored = compute(stored, cur, pendingOp)
            display = fmt(stored)
            pendingOp = ""
            startNew = true
        }
    }
    fun clear() {
        display = "0"; stored = 0.0; pendingOp = ""; startNew = true
    }
    fun backspace() {
        if (!startNew && display.length > 1) display = display.dropLast(1)
        else { display = "0"; startNew = true }
    }

    val rows = listOf(
        listOf("7", "8", "9", "÷"),
        listOf("4", "5", "6", "×"),
        listOf("1", "2", "3", "−"),
        listOf("0", ".", "=", "+"),
    )

    ToolPage("计算器", navController) {
        Text(display, fontSize = 40.sp, fontWeight = FontWeight.Bold, color = TextMain,
            modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { clear() }, modifier = Modifier.weight(1f)) { Text("C") }
            OutlinedButton(onClick = { backspace() }, modifier = Modifier.weight(1f)) { Text("⌫") }
        }
        Spacer(Modifier.height(8.dp))
        rows.forEach { row ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { key ->
                    val isOp = key in listOf("÷", "×", "−", "+")
                    val onClick: () -> Unit = when (key) {
                        "=" -> { { equals() } }
                        "÷" -> { { applyOp("/") } }
                        "×" -> { { applyOp("*") } }
                        "−" -> { { applyOp("-") } }
                        "+" -> { { applyOp("+") } }
                        "." -> { { inputDot() } }
                        else -> { { inputDigit(key) } }
                    }
                    Button(onClick = onClick, modifier = Modifier.weight(1f)) { Text(key) }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

private fun compute(a: Double, b: Double, op: String): Double = when (op) {
    "+" -> a + b
    "-" -> a - b
    "*" -> a * b
    "/" -> if (b == 0.0) a else a / b
    else -> b
}
