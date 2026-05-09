package com.lohitrade

import android.app.Application
import com.google.firebase.FirebaseApp

/**
 * Application class for LoHi-TRADE Android app.
 *
 * Initializes Firebase and Hilt dependency injection.
 * In a full Hilt setup, annotate with @HiltAndroidApp.
 */
class LoHiTradeApp : Application() {

    override fun onCreate() {
        super.onCreate()
        // Initialize Firebase for push notifications (Req 12.6)
        FirebaseApp.initializeApp(this)
    }
}
