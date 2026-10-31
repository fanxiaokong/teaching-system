package com.teachingsystem.web.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.teachingsystem.web.ui.screens.Base64Screen
import com.teachingsystem.web.ui.screens.CalcScreen
import com.teachingsystem.web.ui.screens.ChallengeDetailScreen
import com.teachingsystem.web.ui.screens.ChallengeScreen
import com.teachingsystem.web.ui.screens.CommunityDetailScreen
import com.teachingsystem.web.ui.screens.CommunityScreen
import com.teachingsystem.web.ui.screens.DnsScreen
import com.teachingsystem.web.ui.screens.DriveScreen
import com.teachingsystem.web.ui.screens.FilesScreen
import com.teachingsystem.web.ui.screens.HashScreen
import com.teachingsystem.web.ui.screens.HomeScreen
import com.teachingsystem.web.ui.screens.IpScanScreen
import com.teachingsystem.web.ui.screens.JoinScreen
import com.teachingsystem.web.ui.screens.LoginScreen
import com.teachingsystem.web.ui.screens.MeScreen
import com.teachingsystem.web.ui.screens.PingScreen
import com.teachingsystem.web.ui.screens.PortScanScreen
import com.teachingsystem.web.ui.screens.PublicIpScreen
import com.teachingsystem.web.ui.screens.QrGenScreen
import com.teachingsystem.web.ui.screens.RegisterScreen
import com.teachingsystem.web.ui.screens.ReportScreen
import com.teachingsystem.web.ui.screens.StaticTextScreen
import com.teachingsystem.web.ui.screens.ToolboxScreen
import com.teachingsystem.web.ui.screens.UnitScreen
import com.teachingsystem.web.ui.screens.UrlScreen

object Routes {
    const val HOME = "home"
    const val ME = "me"
    const val LOGIN = "login"
    const val REGISTER = "register"
    const val FILES = "files"
    const val JOIN = "join"
    const val REPORT = "report"
    const val CHALLENGES = "challenges"
    const val CHALLENGE_DETAIL = "challenge_detail/{id}"
    const val COMMUNITY = "community"
    const val COMMUNITY_DETAIL = "community_detail/{id}"
    const val DRIVE = "drive"
    const val TOOLBOX = "toolbox"
    const val TOOL_PING = "tool_ping"
    const val TOOL_IPSCAN = "tool_ipscan"
    const val TOOL_PORTSCAN = "tool_portscan"
    const val TOOL_DNS = "tool_dns"
    const val TOOL_PUBLIC_IP = "tool_public_ip"
    const val TOOL_QR = "tool_qr"
    const val TOOL_BASE64 = "tool_base64"
    const val TOOL_URL = "tool_url"
    const val TOOL_HASH = "tool_hash"
    const val TOOL_UNIT = "tool_unit"
    const val TOOL_CALC = "tool_calc"
    const val AGREEMENT = "agreement"
    const val PRIVACY = "privacy"
}

private data class TabItem(val route: String, val label: String, val icon: ImageVector)

@Composable
fun App() {
    val navController = rememberNavController()
    val tabs = listOf(
        TabItem(Routes.HOME, "首页", Icons.Filled.Home),
        TabItem(Routes.ME, "我的", Icons.Filled.Person),
    )
    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route
    val showBottomBar = tabs.any { it.route == currentRoute }

    // 在线更新：启动自动检查 + 手动触发
    UpdateHost()

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    tabs.forEach { tab ->
                        NavigationBarItem(
                            selected = currentRoute == tab.route,
                            onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(tab.icon, contentDescription = tab.label) },
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Routes.HOME,
            modifier = Modifier.padding(padding),
        ) {
            composable(Routes.HOME) { HomeScreen(navController) }
            composable(Routes.ME) { MeScreen(navController) }
            composable(Routes.LOGIN) { LoginScreen(navController) }
            composable(Routes.REGISTER) { RegisterScreen(navController) }
            composable(Routes.FILES) { FilesScreen(navController) }
            composable(Routes.JOIN) { JoinScreen(navController) }
            composable(Routes.REPORT) { ReportScreen(navController) }
            composable(Routes.CHALLENGES) { ChallengeScreen(navController) }
            composable(Routes.CHALLENGE_DETAIL) { entry ->
                val id = entry.arguments?.getString("id") ?: ""
                ChallengeDetailScreen(navController, id)
            }
            composable(Routes.COMMUNITY) { CommunityScreen(navController) }
            composable(Routes.COMMUNITY_DETAIL) { entry ->
                val id = entry.arguments?.getString("id") ?: ""
                CommunityDetailScreen(navController, id)
            }
            composable(Routes.DRIVE) { DriveScreen(navController) }
            composable(Routes.TOOLBOX) { ToolboxScreen(navController) }
            composable(Routes.TOOL_PING) { PingScreen(navController) }
            composable(Routes.TOOL_IPSCAN) { IpScanScreen(navController) }
            composable(Routes.TOOL_PORTSCAN) { PortScanScreen(navController) }
            composable(Routes.TOOL_DNS) { DnsScreen(navController) }
            composable(Routes.TOOL_PUBLIC_IP) { PublicIpScreen(navController) }
            composable(Routes.TOOL_QR) { QrGenScreen(navController) }
            composable(Routes.TOOL_BASE64) { Base64Screen(navController) }
            composable(Routes.TOOL_URL) { UrlScreen(navController) }
            composable(Routes.TOOL_HASH) { HashScreen(navController) }
            composable(Routes.TOOL_UNIT) { UnitScreen(navController) }
            composable(Routes.TOOL_CALC) { CalcScreen(navController) }
            composable(Routes.AGREEMENT) { StaticTextScreen("用户服务协议", navController) }
            composable(Routes.PRIVACY) { StaticTextScreen("隐私政策", navController) }
        }
    }
}

fun NavHostController.goBackOrHome() {
    if (previousBackStackEntry != null) popBackStack() else navigate(Routes.HOME)
}
