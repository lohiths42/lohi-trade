package com.lohitrade.data.trading

import com.lohitrade.data.api.TradingApi
import com.lohitrade.data.models.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Trading API service for positions, orders, kill switch, analytics,
 * watchlists, screener, and notifications (Req 13.1-13.9).
 */
class TradingService(private val tradingApi: TradingApi) {

    private val _dashboardSummary = MutableStateFlow<DashboardSummary?>(null)
    val dashboardSummary: StateFlow<DashboardSummary?> = _dashboardSummary.asStateFlow()

    private val _positions = MutableStateFlow<List<Position>>(emptyList())
    val positions: StateFlow<List<Position>> = _positions.asStateFlow()

    private val _orders = MutableStateFlow<List<Order>>(emptyList())
    val orders: StateFlow<List<Order>> = _orders.asStateFlow()

    private val _signals = MutableStateFlow<List<Signal>>(emptyList())
    val signals: StateFlow<List<Signal>> = _signals.asStateFlow()

    private val _killSwitchStatus = MutableStateFlow<KillSwitchStatus?>(null)
    val killSwitchStatus: StateFlow<KillSwitchStatus?> = _killSwitchStatus.asStateFlow()

    private val _analyticsData = MutableStateFlow<AnalyticsData?>(null)
    val analyticsData: StateFlow<AnalyticsData?> = _analyticsData.asStateFlow()

    private val _watchlists = MutableStateFlow<List<Watchlist>>(emptyList())
    val watchlists: StateFlow<List<Watchlist>> = _watchlists.asStateFlow()

    private val _currentWatchlist = MutableStateFlow<WatchlistDetail?>(null)
    val currentWatchlist: StateFlow<WatchlistDetail?> = _currentWatchlist.asStateFlow()

    private val _screenerResults = MutableStateFlow<ScreenerResponse?>(null)
    val screenerResults: StateFlow<ScreenerResponse?> = _screenerResults.asStateFlow()

    private val _screenerPresets = MutableStateFlow<List<ScreenerPreset>>(emptyList())
    val screenerPresets: StateFlow<List<ScreenerPreset>> = _screenerPresets.asStateFlow()

    private val _screenerTemplates = MutableStateFlow<List<ScreenerPreset>>(emptyList())
    val screenerTemplates: StateFlow<List<ScreenerPreset>> = _screenerTemplates.asStateFlow()

    private val _notifications = MutableStateFlow<List<AppNotification>>(emptyList())
    val notifications: StateFlow<List<AppNotification>> = _notifications.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    // -- Dashboard (Req 13.1) --

    suspend fun fetchDashboard() {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val summaryResp = tradingApi.getDashboardSummary()
            if (summaryResp.isSuccessful) _dashboardSummary.value = summaryResp.body()

            val posResp = tradingApi.getPositions()
            if (posResp.isSuccessful) _positions.value = posResp.body() ?: emptyList()

            val sigResp = tradingApi.getRecentSignals()
            if (sigResp.isSuccessful) _signals.value = sigResp.body() ?: emptyList()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load dashboard"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Positions (Req 13.3) --

    suspend fun fetchPositions() {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val resp = tradingApi.getPositions()
            if (resp.isSuccessful) _positions.value = resp.body() ?: emptyList()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load positions"
        } finally {
            _isLoading.value = false
        }
    }

    suspend fun closePosition(positionId: String): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.closePosition(ClosePositionRequest(positionId))
            if (resp.isSuccessful) {
                fetchPositions()
                true
            } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to close position"
            false
        }
    }

    // -- Orders (Req 13.4) --

    suspend fun fetchOrders(page: Int = 1) {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val resp = tradingApi.getOrders(page)
            if (resp.isSuccessful) _orders.value = resp.body() ?: emptyList()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load orders"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Kill Switch (Req 13.5) --

    suspend fun fetchKillSwitchStatus() {
        _errorMessage.value = null
        try {
            val resp = tradingApi.getKillSwitchStatus()
            if (resp.isSuccessful) _killSwitchStatus.value = resp.body()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load kill switch status"
        }
    }

    suspend fun toggleKillSwitch(activate: Boolean, reason: String? = null): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.toggleKillSwitch(KillSwitchToggleRequest(activate, reason))
            if (resp.isSuccessful) {
                val body = resp.body()
                _killSwitchStatus.value = KillSwitchStatus(
                    isActive = body?.isActive ?: activate,
                    activatedAt = if (activate) java.time.Instant.now().toString() else null,
                    activatedBy = if (activate) "user" else null,
                    reason = reason
                )
                true
            } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to toggle kill switch"
            false
        }
    }

    // -- Analytics (Req 13.6) --

    suspend fun fetchAnalytics(period: String = "30d") {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val resp = tradingApi.getAnalytics(period)
            if (resp.isSuccessful) _analyticsData.value = resp.body()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load analytics"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Watchlists (Req 13.7) --

    suspend fun fetchWatchlists() {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val resp = tradingApi.getWatchlists()
            if (resp.isSuccessful) _watchlists.value = resp.body() ?: emptyList()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load watchlists"
        } finally {
            _isLoading.value = false
        }
    }

    suspend fun createWatchlist(name: String): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.createWatchlist(CreateWatchlistRequest(name))
            if (resp.isSuccessful) { fetchWatchlists(); true } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to create watchlist"
            false
        }
    }

    suspend fun fetchWatchlistDetail(id: String) {
        _errorMessage.value = null
        try {
            val resp = tradingApi.getWatchlistDetail(id)
            if (resp.isSuccessful) _currentWatchlist.value = resp.body()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load watchlist"
        }
    }

    suspend fun renameWatchlist(id: String, name: String): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.renameWatchlist(id, RenameWatchlistRequest(name))
            if (resp.isSuccessful) { fetchWatchlists(); true } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to rename watchlist"
            false
        }
    }

    suspend fun deleteWatchlist(id: String): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.deleteWatchlist(id)
            if (resp.isSuccessful) { fetchWatchlists(); true } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to delete watchlist"
            false
        }
    }

    suspend fun addSecurity(watchlistId: String, symbol: String): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.addSecurity(watchlistId, AddSecurityRequest(symbol))
            if (resp.isSuccessful) { fetchWatchlistDetail(watchlistId); true } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to add security"
            false
        }
    }

    suspend fun removeSecurity(watchlistId: String, symbol: String): Boolean {
        _errorMessage.value = null
        return try {
            val resp = tradingApi.removeSecurity(watchlistId, symbol)
            if (resp.isSuccessful) { fetchWatchlistDetail(watchlistId); true } else false
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to remove security"
            false
        }
    }

    // -- Screener (Req 13.8) --

    suspend fun searchScreener(request: ScreenerRequest) {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val resp = tradingApi.searchScreener(request)
            if (resp.isSuccessful) _screenerResults.value = resp.body()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to search screener"
        } finally {
            _isLoading.value = false
        }
    }

    suspend fun fetchScreenerTemplates() {
        try {
            val resp = tradingApi.getScreenerTemplates()
            if (resp.isSuccessful) _screenerTemplates.value = resp.body() ?: emptyList()
        } catch (_: Exception) {}
    }

    suspend fun fetchScreenerPresets() {
        try {
            val resp = tradingApi.getScreenerPresets()
            if (resp.isSuccessful) _screenerPresets.value = resp.body() ?: emptyList()
        } catch (_: Exception) {}
    }

    // -- Notifications (Req 13.9) --

    suspend fun fetchNotifications() {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val resp = tradingApi.getNotifications()
            if (resp.isSuccessful) _notifications.value = resp.body() ?: emptyList()
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load notifications"
        } finally {
            _isLoading.value = false
        }
    }

    suspend fun markAllNotificationsRead(): Boolean {
        return try {
            val resp = tradingApi.markAllNotificationsRead()
            if (resp.isSuccessful) {
                _notifications.value = _notifications.value.map {
                    AppNotification(it.id, it.type, it.title, it.message, true, it.createdAt)
                }
                true
            } else false
        } catch (_: Exception) { false }
    }
}
