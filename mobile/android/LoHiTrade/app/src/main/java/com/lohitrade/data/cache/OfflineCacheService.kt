package com.lohitrade.data.cache

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.lohitrade.data.models.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Date

/**
 * Room-backed local cache for offline portfolio viewing (Req 14.1).
 *
 * Caches positions, orders, dashboard summary, watchlists, and signals
 * with per-data-type timestamps. Saves on every successful API response
 * and loads cached data on app launch for instant dashboard display.
 */
class OfflineCacheService(private val cacheDao: CacheDao) {

    private val gson = Gson()

    private val _lastUpdated = MutableStateFlow<Map<String, Date>>(emptyMap())
    val lastUpdated: StateFlow<Map<String, Date>> = _lastUpdated.asStateFlow()

    companion object {
        const val KEY_POSITIONS = "positions"
        const val KEY_ORDERS = "orders"
        const val KEY_DASHBOARD = "dashboard_summary"
        const val KEY_WATCHLISTS = "watchlists"
        const val KEY_SIGNALS = "signals"
    }

    // -- Save --

    suspend fun savePositions(positions: List<Position>) =
        save(positions, KEY_POSITIONS)

    suspend fun saveOrders(orders: List<Order>) =
        save(orders, KEY_ORDERS)

    suspend fun saveDashboardSummary(summary: DashboardSummary) =
        save(summary, KEY_DASHBOARD)

    suspend fun saveWatchlists(watchlists: List<Watchlist>) =
        save(watchlists, KEY_WATCHLISTS)

    suspend fun saveSignals(signals: List<Signal>) =
        save(signals, KEY_SIGNALS)

    // -- Load --

    suspend fun loadPositions(): List<Position>? =
        load(KEY_POSITIONS, object : TypeToken<List<Position>>() {}.type)

    suspend fun loadOrders(): List<Order>? =
        load(KEY_ORDERS, object : TypeToken<List<Order>>() {}.type)

    suspend fun loadDashboardSummary(): DashboardSummary? =
        load(KEY_DASHBOARD, DashboardSummary::class.java)

    suspend fun loadWatchlists(): List<Watchlist>? =
        load(KEY_WATCHLISTS, object : TypeToken<List<Watchlist>>() {}.type)

    suspend fun loadSignals(): List<Signal>? =
        load(KEY_SIGNALS, object : TypeToken<List<Signal>>() {}.type)

    // -- Timestamps --

    fun lastUpdatedDate(forKey: String): Date? = _lastUpdated.value[forKey]

    /** Most recent update timestamp across all cached data types. */
    val mostRecentUpdate: Date?
        get() = _lastUpdated.value.values.maxOrNull()

    // -- Clear --

    suspend fun clearAll() {
        cacheDao.deleteAll()
        _lastUpdated.value = emptyMap()
    }

    // -- Generic save/load --

    private suspend fun <T> save(value: T, key: String) {
        val json = gson.toJson(value)
        val now = System.currentTimeMillis()
        cacheDao.upsert(CacheEntry(key = key, data = json.toByteArray(Charsets.UTF_8), updatedAt = now))
        _lastUpdated.value = _lastUpdated.value + (key to Date(now))
    }

    private suspend fun <T> load(key: String, type: java.lang.reflect.Type): T? {
        val entry = cacheDao.get(key) ?: return null
        _lastUpdated.value = _lastUpdated.value + (key to Date(entry.updatedAt))
        return try {
            gson.fromJson(String(entry.data, Charsets.UTF_8), type)
        } catch (_: Exception) {
            null
        }
    }
}
