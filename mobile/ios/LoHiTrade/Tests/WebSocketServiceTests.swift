import XCTest
@testable import LoHiTrade

/// Unit tests for MarketModels and WebSocket data handling.
final class WebSocketServiceTests: XCTestCase {

    // MARK: - PriceTick decoding

    func testPriceTickDecoding() throws {
        let json = """
        {
            "symbol": "RELIANCE",
            "ltp": 2480.50,
            "change": 30.25,
            "change_percent": 1.23,
            "volume": 5000000,
            "high": 2495.00,
            "low": 2440.00,
            "open": 2450.00,
            "close": 2450.25,
            "timestamp": "2024-01-15T10:30:00Z"
        }
        """.data(using: .utf8)!

        let tick = try JSONDecoder().decode(PriceTick.self, from: json)
        XCTAssertEqual(tick.symbol, "RELIANCE")
        XCTAssertEqual(tick.ltp, 2480.50)
        XCTAssertEqual(tick.change, 30.25)
        XCTAssertEqual(tick.changePercent, 1.23)
        XCTAssertEqual(tick.volume, 5000000)
        XCTAssertEqual(tick.high, 2495.00)
        XCTAssertEqual(tick.low, 2440.00)
    }

    func testPriceTickEquality() {
        let tick1 = PriceTick(
            symbol: "TCS", ltp: 3500, change: 10, changePercent: 0.29,
            volume: 1000000, high: 3520, low: 3480, open: 3490, close: 3490,
            timestamp: "2024-01-15T10:00:00Z"
        )
        let tick2 = PriceTick(
            symbol: "TCS", ltp: 3500, change: 10, changePercent: 0.29,
            volume: 1000000, high: 3520, low: 3480, open: 3490, close: 3490,
            timestamp: "2024-01-15T10:00:00Z"
        )
        XCTAssertEqual(tick1, tick2)
    }

    // MARK: - OrderBookDepth decoding

    func testOrderBookDepthDecoding() throws {
        let json = """
        {
            "symbol": "INFY",
            "bids": [
                {"price": 1500.00, "quantity": 100},
                {"price": 1499.50, "quantity": 200}
            ],
            "asks": [
                {"price": 1500.50, "quantity": 150},
                {"price": 1501.00, "quantity": 300}
            ],
            "timestamp": "2024-01-15T10:30:00Z"
        }
        """.data(using: .utf8)!

        let depth = try JSONDecoder().decode(OrderBookDepth.self, from: json)
        XCTAssertEqual(depth.symbol, "INFY")
        XCTAssertEqual(depth.bids.count, 2)
        XCTAssertEqual(depth.asks.count, 2)
        XCTAssertEqual(depth.bids.first?.price, 1500.00)
        XCTAssertEqual(depth.asks.first?.quantity, 150)
    }

    // MARK: - OrderBookLevel

    func testOrderBookLevelDecoding() throws {
        let json = """
        {"price": 2500.50, "quantity": 500}
        """.data(using: .utf8)!

        let level = try JSONDecoder().decode(OrderBookLevel.self, from: json)
        XCTAssertEqual(level.price, 2500.50)
        XCTAssertEqual(level.quantity, 500)
    }

    // MARK: - WebSocketMessageType

    func testWebSocketMessageTypeDecoding() throws {
        let types: [(String, WebSocketMessageType)] = [
            ("\"price_tick\"", .priceTick),
            ("\"order_book\"", .orderBookUpdate),
            ("\"order_update\"", .orderUpdate),
            ("\"kill_switch\"", .killSwitchAlert),
        ]

        for (jsonStr, expected) in types {
            let data = jsonStr.data(using: .utf8)!
            let decoded = try JSONDecoder().decode(WebSocketMessageType.self, from: data)
            XCTAssertEqual(decoded, expected)
        }
    }

    // MARK: - PriceTick encoding round-trip

    func testPriceTickEncodingRoundTrip() throws {
        let original = PriceTick(
            symbol: "SBIN", ltp: 620.50, change: 5.25, changePercent: 0.85,
            volume: 3000000, high: 625.00, low: 615.00, open: 618.00, close: 615.25,
            timestamp: "2024-01-15T09:15:00Z"
        )

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(PriceTick.self, from: data)
        XCTAssertEqual(original, decoded)
    }
}
