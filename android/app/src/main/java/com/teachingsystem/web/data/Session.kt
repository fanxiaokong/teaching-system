package com.teachingsystem.web.data

import androidx.compose.runtime.mutableStateOf
import org.json.JSONObject

/** 全局会话状态：登录/退出后自动触发依赖它的界面重组 */
object Session {
    lateinit var auth: AuthStore

    val token = mutableStateOf("")
    val user = mutableStateOf<JSONObject?>(null)

    fun init(a: AuthStore) {
        auth = a
        refresh()
    }

    fun refresh() {
        token.value = auth.token()
        user.value = auth.userJson()?.let { runCatching { JSONObject(it) }.getOrNull() }
    }

    fun isLoggedIn(): Boolean = token.value.isNotEmpty()

    fun saveLogin(t: String, u: JSONObject) {
        auth.save(t, u.toString())
        refresh()
    }

    fun saveUser(u: JSONObject) {
        auth.saveUser(u.toString())
        user.value = u
    }

    fun logout() {
        auth.logout()
        refresh()
    }
}
