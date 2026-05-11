package com.lohitrade.data.models

import com.google.gson.annotations.SerializedName

// -- Dashboard --

data class DashboardSummary(
    @SerializedName("total_pnl") val totalPnl: Double,
    @SerializedName("total_pnl_percent") val totalPnlPercent: Double,
    @SerializedName("realized_pnl") val realizedPnl: Double,
    @SerializedName("unrealized_pnl") val unrealizedPnl: Double,
    @SerializedName("open_position_count") val openPositionCount: Int,
    @SerializedName("today_trade_count") val todayTradeCount: Int
)

// -- Positions --

data class Position(
    val id: String,
    val symbol: String,
    val exchange: String,
    val quantity: Int,
    @SerializedName("avg_price") val avgPrice: Double,
    val ltp: Double,
    val pnl: Double,
    @SerializedName("pnl_percent") val pnlPercent: Double,
    val side: String,
    val product: String,
    val strategy: String? = null
)

data class ClosePositionRequest(
    @SerializedName("position_id") val positionId: String
)

data class ClosePositionResponse(
    val success: Boolean,
    val message: String
)

// -- Orders --

data class Order(
    val id: String,
    val symbol: String,
    val exchange: String,
    val side: String,
    @SerializedName("order_type") val orderType: String,
    val quantity: Int,
    val price: Double?,
    @SerializedName("trigger_price") val triggerPrice: Double?,
    @SerializedName("filled_quantity") val filledQuantity: Int,
    @SerializedName("avg_fill_price") val avgFillPrice: Double?,
    val status: String,
    @SerializedName("rejection_reason") val rejectionReason: String?,
    @SerializedName("placed_at") val placedAt: String,
    @SerializedName("updated_at") val updatedAt: String
)

// -- Signals --

data class Signal(
    val id: String,
    val symbol: String,
    val strategy: String,
    val side: String,
    val price: Double,
    val timestamp: String,
    val status: String
)

// -- Kill Switch --

data class KillSwitchStatus(
    @SerializedName("is_active") val isActive: Boolean,
    @SerializedName("activated_at") val activatedAt: String?,
    @SerializedName("activated_by") val activatedBy: String?,
    val reason: String?
)

data class KillSwitchToggleRequest(
    val activate: Boolean,
    val reason: String? = null
)

data class KillSwitchToggleResponse(
    @SerializedName("is_active") val isActive: Boolean,
    val message: String
)

// -- Analytics --

data class AnalyticsData(
    @SerializedName("equity_curve") val equityCurve: List<EquityCurvePoint>,
    @SerializedName("daily_pnl") val dailyPnl: List<DailyPnL>,
    val strategies: List<StrategyPerformance>
)

data class EquityCurvePoint(
    val date: String,
    val equity: Double
)

data class DailyPnL(
    val date: String,
    val pnl: Double
)

data class StrategyPerformance(
    val name: String,
    @SerializedName("total_pnl") val totalPnl: Double,
    @SerializedName("win_rate") val winRate: Double,
    @SerializedName("trade_count") val tradeCount: Int,
    @SerializedName("sharpe_ratio") val sharpeRatio: Double?
)

// -- WebSocket Price Tick --

data class PriceTick(
    val symbol: String,
    val ltp: Double,
    val change: Double,
    @SerializedName("change_percent") val changePercent: Double,
    val volume: Long? = null
)

// -- Watchlists --

data class Watchlist(
    val id: String,
    val name: String,
    @SerializedName("is_prebuilt") val isPrebuilt: Boolean,
    @SerializedName("item_count") val itemCount: Int
)

data class WatchlistDetail(
    val id: String,
    val name: String,
    @SerializedName("is_prebuilt") val isPrebuilt: Boolean,
    val items: List<WatchlistItem>
)

data class WatchlistItem(
    val symbol: String,
    @SerializedName("company_name") val companyName: String,
    val ltp: Double?,
    val change: Double?,
    @SerializedName("change_percent") val changePercent: Double?
)

data class CreateWatchlistRequest(val name: String)
data class RenameWatchlistRequest(val name: String)
data class AddSecurityRequest(val symbol: String)

// -- Screener --

data class ScreenerRequest(
    val filters: ScreenerFilters = ScreenerFilters(),
    @SerializedName("sort_by") val sortBy: String = "market_cap",
    @SerializedName("sort_order") val sortOrder: String = "desc",
    val page: Int = 1
)

data class ScreenerFilters(
    @SerializedName("pe_ratio") val peRatio: ScreenerRange? = null,
    @SerializedName("pb_ratio") val pbRatio: ScreenerRange? = null,
    @SerializedName("dividend_yield") val dividendYield: ScreenerRange? = null,
    val roe: ScreenerRange? = null,
    @SerializedName("debt_to_equity") val debtToEquity: ScreenerRange? = null,
    @SerializedName("rsi_14") val rsi14: ScreenerRange? = null,
    @SerializedName("price_change_1d") val priceChange1d: ScreenerRange? = null,
    @SerializedName("price_change_1w") val priceChange1w: ScreenerRange? = null,
    @SerializedName("price_change_1m") val priceChange1m: ScreenerRange? = null,
    val exchange: String? = null,
    @SerializedName("market_cap_category") val marketCapCategory: String? = null
)

data class ScreenerRange(
    val min: Double? = null,
    val max: Double? = null
)

data class ScreenerResponse(
    val results: List<ScreenerResult>,
    @SerializedName("total_count") val totalCount: Int,
    val page: Int,
    @SerializedName("page_size") val pageSize: Int
)

data class ScreenerResult(
    val symbol: String,
    @SerializedName("company_name") val companyName: String,
    val sector: String?,
    val ltp: Double,
    @SerializedName("change_percent") val changePercent: Double,
    @SerializedName("market_cap") val marketCap: Double?,
    @SerializedName("pe_ratio") val peRatio: Double?
)

data class ScreenerPreset(
    val id: String,
    val name: String,
    val filters: ScreenerFilters
)

// -- Notifications --

data class AppNotification(
    val id: String,
    val type: String,
    val title: String,
    val message: String,
    @SerializedName("is_read") val isRead: Boolean,
    @SerializedName("created_at") val createdAt: String
)

data class EmptyResponse(val success: Boolean? = null)
