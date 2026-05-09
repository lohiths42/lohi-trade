import XCTest
@testable import LoHiTrade

/// Unit tests for WatchlistModels and WatchlistService data handling.
final class WatchlistServiceTests: XCTestCase {

    // MARK: - Watchlist model

    func testWatchlistDecoding() throws {
        let json = """
        {
            "id": "wl-1",
            "name": "My Favorites",
            "is_prebuilt": false,
            "item_count": 15
        }
        """.data(using: .utf8)!

        let watchlist = try JSONDecoder().decode(Watchlist.self, from: json)
        XCTAssertEqual(watchlist.id, "wl-1")
        XCTAssertEqual(watchlist.name, "My Favorites")
        XCTAssertFalse(watchlist.isPrebuilt)
        XCTAssertEqual(watchlist.itemCount, 15)
    }

    func testPrebuiltWatchlistDecoding() throws {
        let json = """
        {
            "id": "wl-nifty50",
            "name": "Nifty 50",
            "is_prebuilt": true,
            "item_count": 50
        }
        """.data(using: .utf8)!

        let watchlist = try JSONDecoder().decode(Watchlist.self, from: json)
        XCTAssertTrue(watchlist.isPrebuilt)
        XCTAssertEqual(watchlist.itemCount, 50)
    }

    // MARK: - WatchlistItem model

    func testWatchlistItemDecoding() throws {
        let json = """
        {
            "symbol": "RELIANCE",
            "company_name": "Reliance Industries Ltd",
            "ltp": 2480.50,
            "change": 30.25,
            "change_percent": 1.23,
            "volume": 5000000
        }
        """.data(using: .utf8)!

        let item = try JSONDecoder().decode(WatchlistItem.self, from: json)
        XCTAssertEqual(item.symbol, "RELIANCE")
        XCTAssertEqual(item.companyName, "Reliance Industries Ltd")
        XCTAssertEqual(item.ltp, 2480.50)
        XCTAssertEqual(item.changePercent, 1.23)
    }

    func testWatchlistItemNullPrices() throws {
        let json = """
        {
            "symbol": "NEWSTOCK",
            "company_name": "New Stock Ltd",
            "ltp": null,
            "change": null,
            "change_percent": null,
            "volume": null
        }
        """.data(using: .utf8)!

        let item = try JSONDecoder().decode(WatchlistItem.self, from: json)
        XCTAssertNil(item.ltp)
        XCTAssertNil(item.change)
    }

    // MARK: - WatchlistDetail model

    func testWatchlistDetailDecoding() throws {
        let json = """
        {
            "id": "wl-1",
            "name": "Tech Stocks",
            "is_prebuilt": false,
            "items": [
                {
                    "symbol": "TCS",
                    "company_name": "Tata Consultancy Services",
                    "ltp": 3500.00,
                    "change": -20.00,
                    "change_percent": -0.57,
                    "volume": 2000000
                }
            ]
        }
        """.data(using: .utf8)!

        let detail = try JSONDecoder().decode(WatchlistDetail.self, from: json)
        XCTAssertEqual(detail.id, "wl-1")
        XCTAssertEqual(detail.items.count, 1)
        XCTAssertEqual(detail.items.first?.symbol, "TCS")
    }

    // MARK: - Request encoding

    func testCreateWatchlistRequestEncoding() throws {
        let request = CreateWatchlistRequest(name: "My Watchlist")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["name"], "My Watchlist")
    }

    func testAddSecurityRequestEncoding() throws {
        let request = AddSecurityRequest(symbol: "INFY")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["symbol"], "INFY")
    }

    func testRenameWatchlistRequestEncoding() throws {
        let request = RenameWatchlistRequest(name: "Renamed List")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["name"], "Renamed List")
    }
}
