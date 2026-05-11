import XCTest
@testable import LoHiTrade

/// Unit tests for TradingModels and TradingService data handling.
final class TradingServiceTests: XCTestCase {

    // MARK: - Position model

    func testPositionDecoding() throws {
        let json = """
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
        """.data(using: .utf8)!

        let position = try JSONDecoder().decode(Position.self, from: json)
        XCTAssertEqual(position.id, "pos-1")
        XCTAssertEqual(position.symbol, "RELIANCE")
        XCTAssertEqual(position.quantity, 10)
        XCTAssertEqual(position.avgPrice, 2450.50)
        XCTAssertEqual(position.ltp, 2480.00)
        XCTAssertEqual(position.pnl, 295.00)
        XCTAssertEqual(position.side, "BUY")
        XCTAssertEqual(position.strategy, "MeanReversion")
    }

    func testPositionDecodingNullStrategy() throws {
        let json = """
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
        """.data(using: .utf8)!

        let position = try JSONDecoder().decode(Position.self, from: json)
        XCTAssertNil(position.strategy)
    }

    // MARK: - Order model

    func testOrderDecoding() throws {
        let json = """
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
        """.data(using: .utf8)!

        let order = try JSONDecoder().decode(Order.self, from: json)
        XCTAssertEqual(order.id, "ord-1")
        XCTAssertEqual(order.status, .complete)
        XCTAssertEqual(order.filledQuantity, 20)
        XCTAssertEqual(order.avgFillPrice, 1499.50)
        XCTAssertNil(order.rejectionReason)
    }

    func testRejectedOrderDecoding() throws {
        let json = """
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
        """.data(using: .utf8)!

        let order = try JSONDecoder().decode(Order.self, from: json)
        XCTAssertEqual(order.status, .rejected)
        XCTAssertEqual(order.rejectionReason, "Insufficient margin")
        XCTAssertEqual(order.filledQuantity, 0)
    }

    // MARK: - OrderStatus

    func testOrderStatusValues() {
        XCTAssertEqual(OrderStatus.complete.rawValue, "COMPLETE")
        XCTAssertEqual(OrderStatus.rejected.rawValue, "REJECTED")
        XCTAssertEqual(OrderStatus.cancelled.rawValue, "CANCELLED")
        XCTAssertEqual(OrderStatus.pending.rawValue, "PENDING")
        XCTAssertEqual(OrderStatus.open.rawValue, "OPEN")
    }

    func testOrderStatusDisplayColor() {
        XCTAssertEqual(OrderStatus.complete.displayColor, "green")
        XCTAssertEqual(OrderStatus.rejected.displayColor, "red")
        XCTAssertEqual(OrderStatus.cancelled.displayColor, "orange")
        XCTAssertEqual(OrderStatus.pending.displayColor, "blue")
    }

    // MARK: - Signal model

    func testSignalDecoding() throws {
        let json = """
        {
            "id": "sig-1",
            "symbol": "SBIN",
            "strategy": "ORB",
            "side": "BUY",
            "price": 620.50,
            "timestamp": "2024-01-15T09:20:00Z",
            "status": "EXECUTED"
        }
        """.data(using: .utf8)!

        let signal = try JSONDecoder().decode(Signal.self, from: json)
        XCTAssertEqual(signal.symbol, "SBIN")
        XCTAssertEqual(signal.strategy, "ORB")
        XCTAssertEqual(signal.side, "BUY")
    }

    // MARK: - KillSwitchStatus

    func testKillSwitchActiveDecoding() throws {
        let json = """
        {
            "is_active": true,
            "activated_at": "2024-01-15T12:00:00Z",
            "activated_by": "user",
            "reason": "Manual activation"
        }
        """.data(using: .utf8)!

        let status = try JSONDecoder().decode(KillSwitchStatus.self, from: json)
        XCTAssertTrue(status.isActive)
        XCTAssertEqual(status.reason, "Manual activation")
    }

    func testKillSwitchInactiveDecoding() throws {
        let json = """
        {
            "is_active": false,
            "activated_at": null,
            "activated_by": null,
            "reason": null
        }
        """.data(using: .utf8)!

        let status = try JSONDecoder().decode(KillSwitchStatus.self, from: json)
        XCTAssertFalse(status.isActive)
        XCTAssertNil(status.activatedAt)
    }

    // MARK: - DashboardSummary

    func testDashboardSummaryDecoding() throws {
        let json = """
        {
            "total_pnl": 15250.75,
            "total_pnl_percent": 3.45,
            "realized_pnl": 10000.00,
            "unrealized_pnl": 5250.75,
            "open_position_count": 3,
            "today_trade_count": 12
        }
        """.data(using: .utf8)!

        let summary = try JSONDecoder().decode(DashboardSummary.self, from: json)
        XCTAssertEqual(summary.totalPnl, 15250.75)
        XCTAssertEqual(summary.openPositionCount, 3)
        XCTAssertEqual(summary.todayTradeCount, 12)
    }

    // MARK: - AnalyticsData

    func testAnalyticsDataDecoding() throws {
        let json = """
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
        """.data(using: .utf8)!

        let analytics = try JSONDecoder().decode(AnalyticsData.self, from: json)
        XCTAssertEqual(analytics.equityCurve.count, 2)
        XCTAssertEqual(analytics.dailyPnl.count, 2)
        XCTAssertEqual(analytics.strategies.count, 1)
        XCTAssertEqual(analytics.strategies.first?.winRate, 0.65)
    }

    // MARK: - Request encoding

    func testClosePositionRequestEncoding() throws {
        let request = ClosePositionRequest(positionId: "pos-123")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["position_id"], "pos-123")
    }

    func testKillSwitchToggleRequestEncoding() throws {
        let request = KillSwitchToggleRequest(activate: true, reason: "Emergency")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["activate"] as? Bool, true)
        XCTAssertEqual(json?["reason"] as? String, "Emergency")
    }
}
