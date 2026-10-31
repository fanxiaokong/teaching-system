package com.teachingsystem.web

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.teachingsystem.web.data.Api
import com.teachingsystem.web.data.AuthStore
import com.teachingsystem.web.data.Session
import com.teachingsystem.web.ui.App
import com.teachingsystem.web.ui.theme.AppTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val auth = AuthStore(applicationContext)
        Api.tokenProvider = { auth.token() }
        Session.init(auth)
        setContent {
            AppTheme {
                App()
            }
        }
    }
}
