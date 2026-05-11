package com.lohitrade

import com.lohitrade.data.cache.CacheDao
import com.lohitrade.data.cache.CacheEntry
import com.lohitrade.data.cache.OfflineCacheService
import com.lohitrade.data.models.*
import io.mockk.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for OfflineCacheService (Req 14.1).
 *
 * Verifies save/load round-trip for all data types, timestamp tracking,
 * and clear functionality using a mocked Room DAO.
 */
class OfflineCacheServiceTest {

    private lateinit var cacheDao: CacheDao
    private lateinit var sut: OfflineCacheService
    private val storedEntries = mutableMapOf<String, CacheEntry>()

    @Before
    fun setUp() {
        cacheDao = mockk()
        storedEntries.clear()

        // Simulate Room DAO behavior with in-memory map
        coEvery { cacheDao.upsert(any()) } answers {
            val entry = firstArg<CacheEntry>()
            storedEntries[entry.key] = entry
        }
        coEvery { cacheDao.get(any()) } answers {
            storedEntries[firstArg<String>()]
        }
        coEvery { cacheDao.getTimestamp(any()) } answers {
            storedEntries[firstArg<String>()]?.updatedAt
        }
        coEvery { cacheDao.deleteAll() } answers {
            storedEntries.clear()
        }

        sut = OfflineCacheService(cacheDao)
    }

    // -- Dashboard Summary --

    @Test
    fun `save and load dashboard summary round-trip`() = runTest {
        val summary = DashboardSummary(
            totalPnl = 1500.50,
            totalPnlPercent = 3.25,
            realizedPnl = 800.0,
            unrealizedPnl = 700.50,
            openPositionCount = 3,
            todayTradeCount = 7
        )

        sut.saveDashboardSummary(summary)
        val loaded = sut.loadDashboardSummary()

        assertNotNull(loaded)
        assertEquals(summary.totalPnl, loaded!!.totalPnl, 0.01)
        assertEquals(summary.totalPnlPercent, loaded.totalPnlPercent, 0.01)
        assertEquals(summary.realizedPnl, loaded.realizedPnl, 0.01)
        assertEquals(summary.unrealizedPnl, loaded.unrealizedPnl, 0.01)
        assertEquals(summary.openPositionCount, loaded.openPositionCount)
        assertEquals(summary.todayTradeCount, loaded.todayTradeCount)
    }

    // -- Positions --

    @Test
    fun `save and load positions round-trip`() = runTest {
        val positions = listOf(
            Position(
                id = "p1", symbol = "RELIANCE", exchange = "NSE",
                quantity = 10, avgPrice = 2500.0, ltp = 2550.0,
                pnl = 500.0, pnlPercent = 2.0, side = "BUY",
                product = "CNC", strategy = "MeanReversion"
            )
        )

        sut.savePositions(positions)
        val loaded = sut.loadPositions()

        assertNotNull(loaded)
        assertEquals(1, loaded!!.size)
        assertEquals("RELIANCE", loaded[0].symbol)
        assertEquals(10, loaded[0].quantity)
        assertEquals(2500.0, loaded[0].avgPrice, 0.01)
    }

    // -- Orders --

    @Test
    fun `save and load orders round-trip`() = runTest {
        val orders = listOf(
            Order(
                id = "o1", symbol = "TCS", exchange = "NSE",
                side = "BUY", orderType = "LIMIT", quantity = 5,
                price = 3400.0, triggerPrice = null, filledQuantity = 5,
                avgFillPrice = 3400.0, status = "COMPLETE",
                rejectionReason = null, placedAt = "2024-01-15T10:30:00Z",
                updatedAt = "2024-01-15T10:30:05Z"
            )
        )

        sut.saveOrders(orders)
        val loaded = sut.loadOrders()

        assertNotNull(loaded)
        assertEquals(1, loaded!!.size)
        assertEquals("TCS", loaded[0].symbol)
        assertEquals("COMPLETE", loaded[0].status)
    }

    // -- Watchlists --

    @Test
    fun `save and load watchlists round-trip`() = runTest {
        val watchlists = listOf(
            Watchlist(id = "w1", name = "Nifty 50", isPrebuilt = true, itemCount = 50),
            Watchlist(id = "w2", name = "My Picks", isPrebuilt = false, itemCount = 12)
        )

        sut.saveWatchlists(watchlists)
        val loaded = sut.loadWatchlists()

        assertNotNull(loaded)
        assertEquals(2, loaded!!.size)
        assertEquals("Nifty 50", loaded[0].name)
        assertTrue(loaded[0].isPrebuilt)
    }

    // -- Signals --

    @Test
    fun `save and load signals round-trip`() = runTest {
        val signals = listOf(
            Signal(
                id = "s1", symbol = "INFY", strategy = "TrendFollowing",
                side = "BUY", price = 1450.0,
                timestamp = "2024-01-15T11:00:00Z", status = "ACTIVE"
            )
        )

        sut.saveSignals(signals)
        val loaded = sut.loadSignals()

        assertNotNull(loaded)
        assertEquals(1, loaded!!.size)
        assertEquals("INFY", loaded[0].symbol)
    }

    // -- Timestamps --

    @Test
    fun `lastUpdated tracks per data type`() = runTest {
        val summary = DashboardSummary(0.0, 0.0, 0.0, 0.0, 0, 0)
        sut.saveDashboardSummary(summary)
        sut.savePositions(emptyList())

        assertNotNull(sut.lastUpdatedDate(OfflineCacheService.KEY_DASHBOARD))
        assertNotNull(sut.lastUpdatedDate(OfflineCacheService.KEY_POSITIONS))
        assertNotNull(sut.mostRecentUpdate)
    }

    // -- Clear --

    @Test
    fun `clearAll removes all data`() = runTest {
        val summary = DashboardSummary(100.0, 1.0, 50.0, 50.0, 1, 2)
        sut.saveDashboardSummary(summary)
        assertNotNull(sut.loadDashboardSummary())

        sut.clearAll()

        assertNull(sut.loadDashboardSummary())
        assertTrue(sut.lastUpdated.value.isEmpty())
    }

    // -- Overwrite --

    @Test
    fun `save overwrites previous data`() = runTest {
        val summary1 = DashboardSummary(100.0, 1.0, 50.0, 50.0, 1, 2)
        val summary2 = DashboardSummary(200.0, 2.0, 100.0, 100.0, 3, 5)

        sut.saveDashboardSummary(summary1)
        sut.saveDashboardSummary(summary2)

        val loaded = sut.loadDashboardSummary()
        assertNotNull(loaded)
        assertEquals(200.0, loaded!!.totalPnl, 0.01)
    }

    // -- Load missing key --

    @Test
    fun `load non-existent key returns null`() = runTest {
        val loaded = sut.loadDashboardSummary()
        assertNull(loaded)
    }
}
