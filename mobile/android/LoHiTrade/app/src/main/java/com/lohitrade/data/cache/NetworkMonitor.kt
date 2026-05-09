package com.lohitrade.data.cache

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * ConnectivityManager wrapper that publishes connectivity status and
 * triggers sync on connectivity restore within 5 seconds (Req 14.2, 14.3).
 */
class NetworkMonitor(
    private val connectivityManager: ConnectivityManager,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
) {
    private val _isConnected = MutableStateFlow(true)
    val isConnected: StateFlow<Boolean> = _isConnected.asStateFlow()

    private val _connectionType = MutableStateFlow(ConnectionType.UNKNOWN)
    val connectionType: StateFlow<ConnectionType> = _connectionType.asStateFlow()

    /** Emits when connectivity is restored after being offline. */
    private val _connectivityRestored = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val connectivityRestored: SharedFlow<Unit> = _connectivityRestored.asSharedFlow()

    private var wasDisconnected = false
    private var syncJob: Job? = null

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            updateConnectionStatus(true)
        }

        override fun onLost(network: Network) {
            updateConnectionStatus(false)
        }

        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
            _connectionType.value = mapConnectionType(caps)
            val connected = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            updateConnectionStatus(connected)
        }
    }

    enum class ConnectionType {
        WIFI, CELLULAR, ETHERNET, UNKNOWN
    }

    constructor(context: Context) : this(
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    )

    fun start() {
        // Set initial state
        val activeNetwork = connectivityManager.activeNetwork
        val caps = activeNetwork?.let { connectivityManager.getNetworkCapabilities(it) }
        _isConnected.value = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        _connectionType.value = caps?.let { mapConnectionType(it) } ?: ConnectionType.UNKNOWN

        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        connectivityManager.registerNetworkCallback(request, networkCallback)
    }

    fun stop() {
        syncJob?.cancel()
        try {
            connectivityManager.unregisterNetworkCallback(networkCallback)
        } catch (_: IllegalArgumentException) {
            // Callback was not registered
        }
    }

    // -- Sync trigger (Req 14.3) --

    private fun updateConnectionStatus(connected: Boolean) {
        _isConnected.value = connected
        if (connected && wasDisconnected) {
            wasDisconnected = false
            triggerSync()
        } else if (!connected) {
            wasDisconnected = true
        }
    }

    /** Triggers server sync within 5 seconds of connectivity restore. */
    private fun triggerSync() {
        syncJob?.cancel()
        syncJob = scope.launch {
            // Small delay to let the network stabilize
            delay(500)
            if (isActive) {
                _connectivityRestored.emit(Unit)
            }
        }
    }

    private fun mapConnectionType(caps: NetworkCapabilities): ConnectionType {
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> ConnectionType.WIFI
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> ConnectionType.CELLULAR
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> ConnectionType.ETHERNET
            else -> ConnectionType.UNKNOWN
        }
    }
}
