package com.lohitrade.data.trading

import com.google.gson.Gson
import com.lohitrade.data.auth.KeystoreService
import com.lohitrade.data.models.PriceTick
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.*
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.pow

/**
 * Real-time price ticker service via WebSocket (Req 12.7, 13.2).
 *
 * Maintains a persistent OkHttp WebSocket connection with automatic
 * reconnection on failure using exponential backoff.
 */
class WebSocketService(
    private val baseUrl: String = "ws://10.0.2.2:8000",
    private val keystoreService: KeystoreService? = null,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
) {
    private val gson = Gson()

    private val _priceTicks = MutableStateFlow<Map<String, PriceTick>>(emptyMap())
    val priceTicks: StateFlow<Map<String, PriceTick>> = _priceTicks.asStateFlow()

    private val _isConnected = MutableStateFlow(false)
    val isConnected: StateFlow<Boolean> = _isConnected.asStateFlow()

    private var webSocket: WebSocket? = null
    private val subscribedSymbols = mutableSetOf<String>()
    private var reconnectAttempts = 0
    private var reconnectJob: Job? = null

    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    companion object {
        const val MAX_RECONNECT_ATTEMPTS = 10
        const val BASE_RECONNECT_DELAY_MS = 1000L
        const val MAX_RECONNECT_DELAY_MS = 30000L
    }

    // MARK: - Connection

    fun connect() {
        if (_isConnected.value) return

        val wsUrl = baseUrl
            .replace("https://", "wss://")
            .replace("http://", "ws://")
            .trimEnd('/') + "/ws/prices"

        val requestBuilder = Request.Builder().url(wsUrl)
        keystoreService?.getAccessToken()?.let { token ->
            requestBuilder.header("Authorization", "Bearer $token")
        }

        webSocket = client.newWebSocket(requestBuilder.build(), createListener())
    }

    fun disconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        reconnectAttempts = 0
        webSocket?.close(1000, "Client disconnect")
        webSocket = null
        _isConnected.value = false
    }

    // MARK: - Subscriptions

    fun subscribe(symbols: List<String>) {
        subscribedSymbols.addAll(symbols)
        if (!_isConnected.value) return
        sendMessage(mapOf("action" to "subscribe", "symbols" to symbols))
    }

    fun unsubscribe(symbols: List<String>) {
        subscribedSymbols.removeAll(symbols.toSet())
        if (!_isConnected.value) return
        sendMessage(mapOf("action" to "unsubscribe", "symbols" to symbols))
    }

    // MARK: - Internal

    private fun sendMessage(message: Map<String, Any>) {
        try {
            val json = gson.toJson(message)
            webSocket?.send(json)
        } catch (e: Exception) {
            // Log send error silently
        }
    }

    private fun handleMessage(text: String) {
        try {
            val tick = gson.fromJson(text, PriceTick::class.java)
            if (tick.symbol.isNotEmpty()) {
                _priceTicks.value = _priceTicks.value + (tick.symbol to tick)
            }
        } catch (_: Exception) {
            // Ignore malformed messages
        }
    }

    private fun attemptReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return
        reconnectAttempts++

        val delay = min(
            BASE_RECONNECT_DELAY_MS * 2.0.pow(reconnectAttempts - 1).toLong(),
            MAX_RECONNECT_DELAY_MS
        )

        reconnectJob = scope.launch {
            delay(delay)
            connect()
        }
    }

    private fun createListener() = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            _isConnected.value = true
            reconnectAttempts = 0
            // Re-subscribe to previously subscribed symbols
            if (subscribedSymbols.isNotEmpty()) {
                subscribe(subscribedSymbols.toList())
            }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            handleMessage(text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            _isConnected.value = false
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            _isConnected.value = false
            attemptReconnect()
        }
    }
}
