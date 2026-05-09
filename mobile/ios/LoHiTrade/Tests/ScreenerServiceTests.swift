import XCTest
@testable import LoHiTrade

/// Unit tests for ScreenerModels and ScreenerService data handling.
final class ScreenerServiceTests: XCTestCase {

    // MARK: - ScreenerFilter encoding

    func testScreenerFilterEncoding() throws {
        var filter = ScreenerFilter()
        filter.peRatio = ScreenerRange(min: 5, max: 25)
        filter.exchange = "NSE"
        filter.sortBy = "market_cap"
        filter.sortOrder = "desc"

        let data = try JSONEncoder().encode(filter)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        let peRatio = json?["pe_ratio"] as? [String: Any]
        XCTAssertEqual(peRatio?["min"] as? Double, 5)
        XCTAssertEqual(peRatio?["max"] as? Double, 25)
        XCTAssertEqual(json?["exchange"] as? String, "NSE")
        XCTAssertEqual(json?["sort_by"] as? String, "market_cap")
    }

    func testScreenerFilterEmptyEncoding() throws {
        let filter = ScreenerFilter()
        let data = try JSONEncoder().encode(filter)
        // Should encode without error even with all nil fields
        XCTAssertNotNil(data)
    }

    // MARK: - ScreenerResult decoding

    func testScreenerResultDecoding() throws {
        let json = """
        {
            "symbol": "RELIANCE",
            "company_name": "Reliance Industries Ltd",
            "sector": "Energy",
            "ltp": 2480.50,
            "change_percent": 1.23,
            "market_cap": 1680000,
            "pe_ratio": 28.5,
            "dividend_yield": 0.35,
            "rsi_14": 55.2
        }
        """.data(using: .utf8)!

        let result = try JSONDecoder().decode(ScreenerResult.self, from: json)
        XCTAssertEqual(result.symbol, "RELIANCE")
        XCTAssertEqual(result.sector, "Energy")
        XCTAssertEqual(result.peRatio, 28.5)
        XCTAssertEqual(result.rsi14, 55.2)
    }

    func testScreenerResultNullOptionals() throws {
        let json = """
        {
            "symbol": "SMALLCO",
            "company_name": "Small Company Ltd",
            "sector": null,
            "ltp": 50.00,
            "change_percent": -2.5,
            "market_cap": null,
            "pe_ratio": null,
            "dividend_yield": null,
            "rsi_14": null
        }
        """.data(using: .utf8)!

        let result = try JSONDecoder().decode(ScreenerResult.self, from: json)
        XCTAssertNil(result.sector)
        XCTAssertNil(result.marketCap)
        XCTAssertNil(result.peRatio)
    }

    // MARK: - ScreenerResponse decoding

    func testScreenerResponseDecoding() throws {
        let json = """
        {
            "results": [
                {
                    "symbol": "TCS",
                    "company_name": "TCS Ltd",
                    "sector": "IT",
                    "ltp": 3500.00,
                    "change_percent": 0.5,
                    "market_cap": 1200000,
                    "pe_ratio": 30.0,
                    "dividend_yield": 1.2,
                    "rsi_14": 60.0
                }
            ],
            "total_count": 150,
            "page": 1,
            "page_size": 50
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(ScreenerResponse.self, from: json)
        XCTAssertEqual(response.results.count, 1)
        XCTAssertEqual(response.totalCount, 150)
        XCTAssertEqual(response.page, 1)
        XCTAssertEqual(response.pageSize, 50)
    }

    // MARK: - ScreenerPreset decoding

    func testScreenerPresetDecoding() throws {
        let json = """
        {
            "id": "preset-1",
            "name": "High Dividend Yield",
            "is_prebuilt": true,
            "filters": {
                "dividend_yield": {"min": 3.0, "max": null},
                "market_cap_category": "large-cap",
                "sort_by": "dividend_yield",
                "sort_order": "desc"
            }
        }
        """.data(using: .utf8)!

        let preset = try JSONDecoder().decode(ScreenerPreset.self, from: json)
        XCTAssertEqual(preset.name, "High Dividend Yield")
        XCTAssertTrue(preset.isPrebuilt)
        XCTAssertEqual(preset.filters.dividendYield?.min, 3.0)
        XCTAssertEqual(preset.filters.marketCapCategory, "large-cap")
    }

    // MARK: - ScreenerRange

    func testScreenerRangeEncoding() throws {
        let range = ScreenerRange(min: 10, max: 50)
        let data = try JSONEncoder().encode(range)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["min"] as? Double, 10)
        XCTAssertEqual(json?["max"] as? Double, 50)
    }

    func testScreenerRangePartialEncoding() throws {
        let range = ScreenerRange(min: 5, max: nil)
        let data = try JSONEncoder().encode(range)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["min"] as? Double, 5)
    }
}
