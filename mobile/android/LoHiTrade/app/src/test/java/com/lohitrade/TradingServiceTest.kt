package com.lohitrade

import com.lohitrade.data.api.TradingApi
import com.lohitrade.data.models.*
import com.lohitrade.data.trading.TradingService
import io.mockk.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import retrofit2.Response

/**
 * Unit tests for TradingService data handling and API interactions.
 */
class TradingServiceTest {

    private lateinit var tradingApi: TradingApi
    private lateinit var tradingService: TradingService

    @Before
    fun setup() {
        tradingApi = mockk()
        tradingService = TradingService(tradingApi)
    }

    // -- Dashboard (Req 13.1) --

    @Test
    fun `fetchDashboard populates summary, positions, and signals`() = runTest {
        val summary = DashboardSummary(15250.75, 3.45, 10000.0, 5250.75, 3, 12)
        val positions = listOf(
            Position("pos-1", "RELIANCE", "NSE", 10, 2450.50, 2480.0, 295.0, 1.2, "BUY", "CNC", "MeanReversion")
        )
        val signals = listOf(
            Signal("sig-1", "SBIN", "ORB", "BUY", 620.50, "2024-01-15T09:20:00Z", "EXECUTED")
        )

        coEvery { tradingApi.getDashboardSummary() } returns Response.success(summary)
        coEvery { tradingApi.getPositions() } returns Response.success(positions)
        coEvery { tradingApi.getRecentSignals() } returns Response.success(signals)

        tradingService.fetchDashboard()

        assertEquals(summary, tradingService.dashboardSummary.value)
        assertEquals(1, tradingService.positions.value.size)
        assertEquals("RELIANCE", tradingService.positions.value[0].symbol)
        assertEquals(1, tradingService.signals.value.size)
        assertEquals("SBIN", tradingService.signals.value[0].symbol)
        assertFalse(tradingService.isLoading.value)
    }

    @Test
    fun `fetchDashboard sets error on exception`() = runTest {
        coEvery { tradingApi.getDashboardSummary() } throws RuntimeException("Network error")

        tradingService.fetchDashboard()

        assertNotNull(tradingService.errorMessage.value)
        assertFalse(tradingService.isLoading.value)
    }

    // -- Positions (Req 13.3) --

    @Test
    fun `fetchPositions populates positions list`() = runTest {
        val positions = listOf(
            Position("pos-1", "TCS", "NSE", 5, 3500.0, 3480.0, -100.0, -0.57, "BUY", "MIS", null)
        )
        coEvery { tradingApi.getPositions() } returns Response.success(positions)

        tradingService.fetchPositions()

        assertEquals(1, tradingService.positions.value.size)
        assertEquals("TCS", tradingService.positions.value[0].symbol)
        assertNull(tradingService.positions.value[0].strategy)
    }

    @Test
    fun `closePosition calls API and refreshes positions`() = runTest {
        coEvery { tradingApi.closePosition(any()) } returns Response.success(
            ClosePositionResponse(true, "Position closed")
        )
        coEvery { tradingApi.getPositions() } returns Response.success(emptyList())

        val result = tradingService.closePosition("pos-1")

        assertTrue(result)
        coVerify { tradingApi.closePosition(ClosePositionRequest("pos-1")) }
        coVerify(exactly = 1) { tradingApi.getPositions() }
    }

    // -- Orders (Req 13.4) --

    @Test
    fun `fetchOrders populates orders list`() = runTest {
        val orders = listOf(
            Order("ord-1", "INFY", "NSE", "BUY", "LIMIT", 20, 1500.0, null,
                20, 1499.50, "COMPLETE", null, "2024-01-15T10:30:00Z", "2024-01-15T10:30:05Z"),
            Order("ord-2", "HDFC", "NSE", "SELL", "MARKET", 10, null, null,
                0, null, "REJECTED", "Insufficient margin", "2024-01-15T11:00:00Z", "2024-01-15T11:00:01Z")
        )
        coEvery { tradingApi.getOrders(1) } returns Response.success(orders)

        tradingService.fetchOrders()

        assertEquals(2, tradingService.orders.value.size)
        assertEquals("COMPLETE", tradingService.orders.value[0].status)
        assertEquals("Insufficient margin", tradingService.orders.value[1].rejectionReason)
    }

    // -- Kill Switch (Req 13.5) --

    @Test
    fun `fetchKillSwitchStatus populates status`() = runTest {
        val status = KillSwitchStatus(true, "2024-01-15T12:00:00Z", "user", "Manual activation")
        coEvery { tradingApi.getKillSwitchStatus() } returns Response.success(status)

        tradingService.fetchKillSwitchStatus()

        assertTrue(tradingService.killSwitchStatus.value!!.isActive)
        assertEquals("Manual activation", tradingService.killSwitchStatus.value!!.reason)
    }

    @Test
    fun `toggleKillSwitch activates and updates status`() = runTest {
        coEvery { tradingApi.toggleKillSwitch(any()) } returns Response.success(
            KillSwitchToggleResponse(true, "Kill switch activated")
        )

        val result = tradingService.toggleKillSwitch(true, "Emergency")

        assertTrue(result)
        assertTrue(tradingService.killSwitchStatus.value!!.isActive)
        assertEquals("Emergency", tradingService.killSwitchStatus.value!!.reason)
    }

    @Test
    fun `toggleKillSwitch deactivates and updates status`() = runTest {
        coEvery { tradingApi.toggleKillSwitch(any()) } returns Response.success(
            KillSwitchToggleResponse(false, "Kill switch deactivated")
        )

        val result = tradingService.toggleKillSwitch(false)

        assertTrue(result)
        assertFalse(tradingService.killSwitchStatus.value!!.isActive)
    }

    // -- Analytics (Req 13.6) --

    @Test
    fun `fetchAnalytics populates analytics data`() = runTest {
        val analytics = AnalyticsData(
            equityCurve = listOf(EquityCurvePoint("2024-01-01", 100000.0), EquityCurvePoint("2024-01-02", 101500.0)),
            dailyPnl = listOf(DailyPnL("2024-01-01", 500.0), DailyPnL("2024-01-02", -200.0)),
            strategies = listOf(StrategyPerformance("MeanReversion", 5000.0, 0.65, 20, 1.8))
        )
        coEvery { tradingApi.getAnalytics("30d") } returns Response.success(analytics)

        tradingService.fetchAnalytics("30d")

        assertNotNull(tradingService.analyticsData.value)
        assertEquals(2, tradingService.analyticsData.value!!.equityCurve.size)
        assertEquals(0.65, tradingService.analyticsData.value!!.strategies[0].winRate, 0.001)
    }

    // -- Watchlists (Req 13.7) --

    @Test
    fun `fetchWatchlists populates watchlist list`() = runTest {
        val watchlists = listOf(
            Watchlist("wl-1", "My Stocks", false, 5),
            Watchlist("wl-2", "Nifty 50", true, 50)
        )
        coEvery { tradingApi.getWatchlists() } returns Response.success(watchlists)

        tradingService.fetchWatchlists()

        assertEquals(2, tradingService.watchlists.value.size)
        assertTrue(tradingService.watchlists.value[1].isPrebuilt)
    }

    @Test
    fun `createWatchlist calls API and refreshes list`() = runTest {
        coEvery { tradingApi.createWatchlist(any()) } returns Response.success(
            Watchlist("wl-3", "New List", false, 0)
        )
        coEvery { tradingApi.getWatchlists() } returns Response.success(emptyList())

        val result = tradingService.createWatchlist("New List")

        assertTrue(result)
        coVerify { tradingApi.createWatchlist(CreateWatchlistRequest("New List")) }
    }

    @Test
    fun `deleteWatchlist calls API and refreshes list`() = runTest {
        coEvery { tradingApi.deleteWatchlist("wl-1") } returns Response.success(EmptyResponse())
        coEvery { tradingApi.getWatchlists() } returns Response.success(emptyList())

        val result = tradingService.deleteWatchlist("wl-1")

        assertTrue(result)
        coVerify { tradingApi.deleteWatchlist("wl-1") }
    }

    @Test
    fun `addSecurity calls API and refreshes detail`() = runTest {
        coEvery { tradingApi.addSecurity("wl-1", any()) } returns Response.success(EmptyResponse())
        coEvery { tradingApi.getWatchlistDetail("wl-1") } returns Response.success(
            WatchlistDetail("wl-1", "My Stocks", false, emptyList())
        )

        val result = tradingService.addSecurity("wl-1", "RELIANCE")

        assertTrue(result)
        coVerify { tradingApi.addSecurity("wl-1", AddSecurityRequest("RELIANCE")) }
    }

    // -- Screener (Req 13.8) --

    @Test
    fun `searchScreener populates results`() = runTest {
        val response = ScreenerResponse(
            results = listOf(
                ScreenerResult("RELIANCE", "Reliance Industries", "Energy", 2480.0, 1.5, 1800000.0, 28.5)
            ),
            totalCount = 1, page = 1, pageSize = 50
        )
        coEvery { tradingApi.searchScreener(any()) } returns Response.success(response)

        tradingService.searchScreener(ScreenerRequest())

        assertNotNull(tradingService.screenerResults.value)
        assertEquals(1, tradingService.screenerResults.value!!.results.size)
        assertEquals("RELIANCE", tradingService.screenerResults.value!!.results[0].symbol)
    }

    // -- Notifications (Req 13.9) --

    @Test
    fun `fetchNotifications populates notification list`() = runTest {
        val notifications = listOf(
            AppNotification("n-1", "TRADE", "Order Filled", "RELIANCE BUY 10 @ 2450", false, "2024-01-15T10:30:00Z"),
            AppNotification("n-2", "SYSTEM", "Market Open", "Trading session started", true, "2024-01-15T09:15:00Z")
        )
        coEvery { tradingApi.getNotifications() } returns Response.success(notifications)

        tradingService.fetchNotifications()

        assertEquals(2, tradingService.notifications.value.size)
        assertFalse(tradingService.notifications.value[0].isRead)
    }

    @Test
    fun `markAllNotificationsRead updates local state`() = runTest {
        // Pre-populate with unread notifications
        val notifications = listOf(
            AppNotification("n-1", "TRADE", "Order Filled", "msg", false, "2024-01-15T10:30:00Z")
        )
        coEvery { tradingApi.getNotifications() } returns Response.success(notifications)
        tradingService.fetchNotifications()

        coEvery { tradingApi.markAllNotificationsRead() } returns Response.success(EmptyResponse())

        val result = tradingService.markAllNotificationsRead()

        assertTrue(result)
        assertTrue(tradingService.notifications.value.all { it.isRead })
    }
}
