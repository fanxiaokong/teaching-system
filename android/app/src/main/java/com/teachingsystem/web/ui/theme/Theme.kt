package com.teachingsystem.web.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Primary = Color(0xFF1F4E79)
val Secondary = Color(0xFF3B82F6)
val Background = Color(0xFFF4F7FB)
val CardBg = Color(0xFFFFFFFF)
val TextMain = Color(0xFF1F2937)
val TextSub = Color(0xFF6B7280)

private val LightColors = lightColorScheme(
    primary = Primary,
    onPrimary = Color.White,
    secondary = Secondary,
    background = Background,
    surface = CardBg,
    onBackground = TextMain,
    onSurface = TextMain,
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = LightColors, content = content)
}
