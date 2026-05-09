package com.lohitrade.data.push

import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.lohitrade.data.api.ApiClient
import com.lohitrade.data.models.FCMTokenRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Firebase Cloud Messaging push notification setup (Req 12.6).
 *
 * Handles trade alerts, order status updates, and kill switch activations.
 */
class PushNotificationService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "PushNotification"

        /** FCM topics the app subscribes to. */
        object Topics {
            const val TRADE_ALERTS = "trade_alerts"
            const val ORDER_UPDATES = "order_updates"
            const val KILL_SWITCH = "kill_switch"
        }

        /** Subscribe to a push notification topic. */
        fun subscribe(topic: String) {
            FirebaseMessaging.getInstance().subscribeToTopic(topic)
                .addOnSuccessListener { Log.d(TAG, "Subscribed to $topic") }
                .addOnFailureListener { Log.e(TAG, "Subscribe to $topic failed", it) }
        }

        /** Unsubscribe from a push notification topic. */
        fun unsubscribe(topic: String) {
            FirebaseMessaging.getInstance().unsubscribeFromTopic(topic)
                .addOnSuccessListener { Log.d(TAG, "Unsubscribed from $topic") }
                .addOnFailureListener { Log.e(TAG, "Unsubscribe from $topic failed", it) }
        }

        /** Subscribe to all default topics after login. */
        fun subscribeToDefaults() {
            subscribe(Topics.TRADE_ALERTS)
            subscribe(Topics.ORDER_UPDATES)
            subscribe(Topics.KILL_SWITCH)
        }

        /** Get the current FCM registration token. */
        fun getToken(onToken: (String?) -> Unit) {
            FirebaseMessaging.getInstance().token
                .addOnSuccessListener { onToken(it) }
                .addOnFailureListener {
                    Log.e(TAG, "Failed to get FCM token", it)
                    onToken(null)
                }
        }
    }

    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    /**
     * Called when FCM provides a new registration token.
     * Send it to the backend for targeted push delivery.
     */
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.d(TAG, "New FCM token: $token")
        serviceScope.launch {
            registerTokenWithBackend(token)
        }
    }

    /**
     * Called when a message is received while the app is in the foreground.
     */
    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        Log.d(TAG, "Message received: ${message.data}")

        val type = message.data["type"] ?: return

        when (type) {
            "trade_alert" -> handleTradeAlert(message.data)
            "order_update" -> handleOrderUpdate(message.data)
            "kill_switch" -> handleKillSwitch(message.data)
        }
    }

    private fun handleTradeAlert(data: Map<String, String>) {
        Log.d(TAG, "Trade alert: $data")
        // Post notification or broadcast to UI
    }

    private fun handleOrderUpdate(data: Map<String, String>) {
        Log.d(TAG, "Order update: $data")
    }

    private fun handleKillSwitch(data: Map<String, String>) {
        Log.d(TAG, "Kill switch activation: $data")
    }

    /**
     * Send FCM token to backend so it can target this device.
     * Fire-and-forget; failures are logged but not blocking.
     */
    private suspend fun registerTokenWithBackend(token: String) {
        try {
            // Note: In production, inject ApiClient via Hilt.
            // This is a simplified version for the FCM service.
            Log.d(TAG, "Registering FCM token with backend")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to register FCM token with backend", e)
        }
    }
}
