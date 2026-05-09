package com.lohitrade.data.api

import com.lohitrade.data.models.*
import retrofit2.Response
import retrofit2.http.*

/**
 * Trading API interface for positions, orders, kill switch, analytics,
 * watchlists, screener, and notifications (Req 13.1-13.9).
 */
interface TradingApi {

    // -- Dashboard (Req 13.1) --
    @GET("/dashboard/summary")
    suspend fun getDashboardSummary(): Response<DashboardSummary>

    // -- Positions (Req 13.3) --
    @GET("/positions")
    suspend fun getPositions(): Response<List<Position>>

    @POST("/positions/close")
    suspend fun closePosition(@Body request: ClosePositionRequest): Response<ClosePositionResponse>

    // -- Orders (Req 13.4) --
    @GET("/orders")
    suspend fun getOrders(@Query("page") page: Int = 1): Response<List<Order>>

    // -- Signals --
    @GET("/signals/recent")
    suspend fun getRecentSignals(): Response<List<Signal>>

    // -- Kill Switch (Req 13.5) --
    @GET("/kill-switch/status")
    suspend fun getKillSwitchStatus(): Response<KillSwitchStatus>

    @POST("/kill-switch/toggle")
    suspend fun toggleKillSwitch(@Body request: KillSwitchToggleRequest): Response<KillSwitchToggleResponse>

    // -- Analytics (Req 13.6) --
    @GET("/analytics")
    suspend fun getAnalytics(@Query("period") period: String = "30d"): Response<AnalyticsData>

    // -- Watchlists (Req 13.7) --
    @GET("/watchlists")
    suspend fun getWatchlists(): Response<List<Watchlist>>

    @POST("/watchlists")
    suspend fun createWatchlist(@Body request: CreateWatchlistRequest): Response<Watchlist>

    @GET("/watchlists/{id}")
    suspend fun getWatchlistDetail(@Path("id") id: String): Response<WatchlistDetail>

    @PUT("/watchlists/{id}")
    suspend fun renameWatchlist(@Path("id") id: String, @Body request: RenameWatchlistRequest): Response<Watchlist>

    @DELETE("/watchlists/{id}")
    suspend fun deleteWatchlist(@Path("id") id: String): Response<EmptyResponse>

    @POST("/watchlists/{id}/securities")
    suspend fun addSecurity(@Path("id") id: String, @Body request: AddSecurityRequest): Response<EmptyResponse>

    @DELETE("/watchlists/{id}/securities/{symbol}")
    suspend fun removeSecurity(@Path("id") id: String, @Path("symbol") symbol: String): Response<EmptyResponse>

    @GET("/watchlists/prebuilt")
    suspend fun getPrebuiltWatchlists(): Response<List<Watchlist>>

    // -- Screener (Req 13.8) --
    @POST("/screener/search")
    suspend fun searchScreener(@Body request: ScreenerRequest): Response<ScreenerResponse>

    @GET("/screener/templates")
    suspend fun getScreenerTemplates(): Response<List<ScreenerPreset>>

    @GET("/screener/presets")
    suspend fun getScreenerPresets(): Response<List<ScreenerPreset>>

    // -- Notifications (Req 13.9) --
    @GET("/notifications")
    suspend fun getNotifications(): Response<List<AppNotification>>

    @POST("/notifications/mark-all-read")
    suspend fun markAllNotificationsRead(): Response<EmptyResponse>
}
