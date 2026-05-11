import Foundation

// MARK: - Position

struct Position: Codable, Identifiable, Equatable {
    let id: String
    let symbol: String
    let exchange: String
    let quantity: Int
    let avgPrice: Double
    let ltp: Double
    let pnl: Double
    let pnlPercent: Double
    let side: String // BUY or SELL
    let product: String
    let strategy: String?

    enum CodingKeys: String, CodingKey {
        case id, symbol, exchange, quantity
        case avgPrice = "avg_price"
        case ltp, pnl
        case pnlPercent = "pnl_percent"
        case side, product, strategy
    }
}

// MARK: - Order

struct Order: Codable, Identifiable, Equatable {
    let id: String
    let symbol: String
    let exchange: String
    let side: String
    let orderType: String
    let quantity: Int
    let price: Double?
    let triggerPrice: Double?
    let filledQuantity: Int
    let avgFillPrice: Double?
    let status: OrderStatus
    let rejectionReason: String?
    let placedAt: String
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, symbol, exchange, side
        case orderType = "order_type"
        case quantity, price
        case triggerPrice = "trigger_price"
        case filledQuantity = "filled_quantity"
        case avgFillPrice = "avg_fill_price"
        case status
        case rejectionReason = "rejection_reason"
        case placedAt = "placed_at"
        case updatedAt = "updated_at"
    }
}

enum OrderStatus: String, Codable, Equatable {
    case pending = "PENDING"
    case open = "OPEN"
    case complete = "COMPLETE"
    case cancelled = "CANCELLED"
    case rejected = "REJECTED"

    var displayColor: String {
        switch self {
        case .complete: return "green"
        case .rejected: return "red"
        case .cancelled: return "orange"
        case .pending, .open: return "blue"
        }
    }
}

// MARK: - Signal

struct Signal: Codable, Identifiable, Equatable {
    let id: String
    let symbol: String
    let strategy: String
    let side: String
    let price: Double
    let timestamp: String
    let status: String
}

// MARK: - Kill Switch

struct KillSwitchStatus: Codable, Equatable {
    let isActive: Bool
    let activatedAt: String?
    let activatedBy: String?
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case isActive = "is_active"
        case activatedAt = "activated_at"
        case activatedBy = "activated_by"
        case reason
    }
}

// MARK: - Dashboard Summary

struct DashboardSummary: Codable, Equatable {
    let totalPnl: Double
    let totalPnlPercent: Double
    let realizedPnl: Double
    let unrealizedPnl: Double
    let openPositionCount: Int
    let todayTradeCount: Int

    enum CodingKeys: String, CodingKey {
        case totalPnl = "total_pnl"
        case totalPnlPercent = "total_pnl_percent"
        case realizedPnl = "realized_pnl"
        case unrealizedPnl = "unrealized_pnl"
        case openPositionCount = "open_position_count"
        case todayTradeCount = "today_trade_count"
    }
}

// MARK: - Analytics

struct EquityCurvePoint: Codable, Equatable {
    let date: String
    let equity: Double
}

struct DailyPnL: Codable, Equatable {
    let date: String
    let pnl: Double
}

struct StrategyPerformance: Codable, Identifiable, Equatable {
    var id: String { name }
    let name: String
    let totalPnl: Double
    let winRate: Double
    let tradeCount: Int
    let sharpeRatio: Double?

    enum CodingKeys: String, CodingKey {
        case name
        case totalPnl = "total_pnl"
        case winRate = "win_rate"
        case tradeCount = "trade_count"
        case sharpeRatio = "sharpe_ratio"
    }
}

struct AnalyticsData: Codable, Equatable {
    let equityCurve: [EquityCurvePoint]
    let dailyPnl: [DailyPnL]
    let strategies: [StrategyPerformance]

    enum CodingKeys: String, CodingKey {
        case equityCurve = "equity_curve"
        case dailyPnl = "daily_pnl"
        case strategies
    }
}

// MARK: - Close Position Request

struct ClosePositionRequest: Encodable {
    let positionId: String

    enum CodingKeys: String, CodingKey {
        case positionId = "position_id"
    }
}

struct ClosePositionResponse: Decodable {
    let orderId: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case orderId = "order_id"
        case message
    }
}

// MARK: - Kill Switch Toggle

struct KillSwitchToggleRequest: Encodable {
    let activate: Bool
    let reason: String?
}

struct KillSwitchToggleResponse: Decodable {
    let isActive: Bool
    let message: String

    enum CodingKeys: String, CodingKey {
        case isActive = "is_active"
        case message
    }
}
