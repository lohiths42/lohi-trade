package com.lohitrade

import com.google.gson.Gson
import com.lohitrade.data.models.*
import org.junit.Assert.*
import org.junit.Test

/**
 * Unit tests for trading model JSON serialization/deserialization.
 */
class TradingModelsTest {

    private val gson = Gson()

    @Test
    fun `DashboardSummary deserializes correctly`() {
        val json = """
        {
            "total_pnl": 15250.75,
            "total_pnl_percent": 3.45,
            "realized_pnl": 10000.00,
            "unrealized_pnl": 5250.75,
            "open_position_count": 3,
            "today_trade_count": 12
        }
        """.trimIndent()

        val summary = gson.fromJson(json, DashboardSummary::class.java)
        assertEquals(15250.75, summary.totalPnl, 0.001)
        assertEquals(3.45, summary.totalPnlPercent, 0.001)
        assertEquals(3, summary.openPositionCount)
        assertEquals(12, summary.todayTradeCount)
    }

    @Test
    fun `Position deserializes with strategy`() {
        val json = """
        {
            "id": "pos-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 10,
            "avg_price": 2450.50,
            "ltp": 2480.00,
            "pnl": 295.00,
            "pnl_percent": 1.20,
            "side": "BUY",
            "product": "CNC",
            "strategy": "MeanReversion"
        }
        """.trimIndent()

        val position = gson.fromJson(json, Position::class.java)
        assertEquals("pos-1", position.id)
        assertEquals("RELIANCE", position.symbol)
        assertEquals(10, position.quantity)
        assertEquals(2450.50, position.avgPrice, 0.001)
        assertEquals("MeanReversion", position.strategy)
    }

    @Test
    fun `Position deserializes with null strategy`() {
        val json = """
        {
            "id": "pos-2",
            "symbol": "TCS",
            "exchange": "NSE",
            "quantity": 5,
            "avg_price": 3500.00,
            "ltp": 3480.00,
            "pnl": -100.00,
            "pnl_percent": -0.57,
            "side": "BUY",
            "product": "MIS",
            "strategy": null
        }
        """.trimIndent()

        val position = gson.fromJson(json, Position::class.java)
        assertNull(position.strategy)
    }

    @Test
    fun `Order deserializes complete order`() {
        val json = """
        {
            "id": "ord-1",
            "symbol": "INFY",
            "exchange": "NSE",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 20,
            "price": 1500.00,
            "trigger_price": null,
            "filled_quantity": 20,
            "avg_fill_price": 1499.50,
            "status": "COMPLETE",
            "rejection_reason": null,
            "placed_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-15T10:30:05Z"
        }
        """.trimIndent()

        val order = gson.fromJson(json, Order::class.java)
        assertEquals("COMPLETE", order.status)
        assertEquals(20, order.filledQuantity)
        assertEquals(1499.50, order.avgFillPrice!!, 0.001)
        assertNull(order.rejectionReason)
    }

    @Test
    fun `Order deserializes rejected order`() {
        val json = """
        {
            "id": "ord-2",
            "symbol": "HDFC",
            "exchange": "NSE",
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": 10,
            "price": null,
            "trigger_price": null,
            "filled_quantity": 0,
            "avg_fill_price": null,
            "status": "REJECTED",
            "rejection_reason": "Insufficient margin",
            "placed_at": "2024-01-15T11:00:00Z",
            "updated_at": "2024-01-15T11:00:01Z"
        }
        """.trimIndent()

        val order = gson.fromJson(json, Order::class.java)
        assertEquals("REJECTED", order.status)
        assertEquals("Insufficient margin", order.rejectionReason)
        assertEquals(0, order.filledQuantity)
    }

    @Test
    fun `Signal deserializes correctly`() {
        val json = """
        {
            "id": "sig-1",
            "symbol": "SBIN",
            "strategy": "ORB",
            "side": "BUY",
            "price": 620.50,
            "timestamp": "2024-01-15T09:20:00Z",
            "status": "EXECUTED"
        }
        """.trimIndent()

        val signal = gson.fromJson(json, Signal::class.java)
        assertEquals("SBIN", signal.symbol)
        assertEquals("ORB", signal.strategy)
        assertEquals("BUY", signal.side)
    }

    @Test
    fun `KillSwitchStatus deserializes active state`() {
        val json = """
        {
            "is_active": true,
            "activated_at": "2024-01-15T12:00:00Z",
            "activated_by": "user",
            "reason": "Manual activation"
        }
        """.trimIndent()

        val status = gson.fromJson(json, KillSwitchStatus::class.java)
        assertTrue(status.isActive)
        assertEquals("Manual activation", status.reason)
    }

    @Test
    fun `KillSwitchStatus deserializes inactive state`() {
        val json = """
        {
            "is_active": false,
            "activated_at": null,
            "activated_by": null,
            "reason": null
        }
        """.trimIndent()

        val status = gson.fromJson(json, KillSwitchStatus::class.java)
        assertFalse(status.isActive)
        assertNull(status.activatedAt)
    }

    @Test
    fun `AnalyticsData deserializes correctly`() {
        val json = """
        {
            "equity_curve": [
                {"date": "2024-01-01", "equity": 100000},
                {"date": "2024-01-02", "equity": 101500}
            ],
            "daily_pnl": [
                {"date": "2024-01-01", "pnl": 500},
                {"date": "2024-01-02", "pnl": -200}
            ],
            "strategies": [
                {
                    "name": "MeanReversion",
                    "total_pnl": 5000,
                    "win_rate": 0.65,
                    "trade_count": 20,
                    "sharpe_ratio": 1.8
                }
            ]
        }
        """.trimIndent()

        val analytics = gson.fromJson(json, AnalyticsData::class.java)
        assertEquals(2, analytics.equityCurve.size)
        assertEquals(2, analytics.dailyPnl.size)
        assertEquals(1, analytics.strategies.size)
        assertEquals(0.65, analytics.strategies[0].winRate, 0.001)
    }

    @Test
    fun `PriceTick deserializes correctly`() {
        val json = """
        {
            "symbol": "RELIANCE",
            "ltp": 2480.50,
            "change": 30.50,
            "change_percent": 1.25,
            "volume": 1500000
        }
        """.trimIndent()

        val tick = gson.fromJson(json, PriceTick::class.java)
        assertEquals("RELIANCE", tick.symbol)
        assertEquals(2480.50, tick.ltp, 0.001)
        assertEquals(1.25, tick.changePercent, 0.001)
        assertEquals(1500000L, tick.volume)
    }

    @Test
    fun `ClosePositionRequest serializes correctly`() {
        val request = ClosePositionRequest("pos-123")
        val json = gson.toJson(request)
        assertTrue(json.contains("\"position_id\":\"pos-123\""))
    }

    @Test
    fun `KillSwitchToggleRequest serializes correctly`() {
        val request = KillSwitchToggleRequest(true, "Emergency")
        val json = gson.toJson(request)
        assertTrue(json.contains("\"activate\":true"))
        assertTrue(json.contains("\"reason\":\"Emergency\""))
    }

    @Test
    fun `ScreenerRequest serializes with filters`() {
        val request = ScreenerRequest(
            filters = ScreenerFilters(peRatio = ScreenerRange(min = 5.0, max = 25.0)),
            sortBy = "pe_ratio",
            sortOrder = "asc",
            page = 1
        )
        val json = gson.toJson(request)
        assertTrue(json.contains("\"pe_ratio\""))
        assertTrue(json.contains("\"sort_by\":\"pe_ratio\""))
    }

    @Test
    fun `AppNotification deserializes correctly`() {
        val json = """
        {
            "id": "n-1",
            "type": "TRADE",
            "title": "Order Filled",
            "message": "RELIANCE BUY 10 @ 2450",
            "is_read": false,
            "created_at": "2024-01-15T10:30:00Z"
        }
        """.trimIndent()

        val notification = gson.fromJson(json, AppNotification::class.java)
        assertEquals("TRADE", notification.type)
        assertFalse(notification.isRead)
    }
}
