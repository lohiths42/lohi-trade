import Foundation

// MARK: - Screener Filter

struct ScreenerRange: Codable, Equatable {
    var min: Double?
    var max: Double?
}

struct ScreenerFilter: Codable, Equatable {
    // Fundamental
    var peRatio: ScreenerRange?
    var pbRatio: ScreenerRange?
    var marketCap: ScreenerRange?
    var dividendYield: ScreenerRange?
    var eps: ScreenerRange?
    var roe: ScreenerRange?
    var debtToEquity: ScreenerRange?
    var revenueGrowth1y: ScreenerRange?
    var profitGrowth1y: ScreenerRange?
    // Technical
    var rsi14: ScreenerRange?
    var near52wHigh: Bool?
    var near52wLow: Bool?
    var avgVolume: ScreenerRange?
    var priceChange1d: ScreenerRange?
    var priceChange1w: ScreenerRange?
    var priceChange1m: ScreenerRange?
    // Meta
    var exchange: String?
    var sector: String?
    var marketCapCategory: String?
    // Sort
    var sortBy: String?
    var sortOrder: String?

    enum CodingKeys: String, CodingKey {
        case peRatio = "pe_ratio"
        case pbRatio = "pb_ratio"
        case marketCap = "market_cap"
        case dividendYield = "dividend_yield"
        case eps, roe
        case debtToEquity = "debt_to_equity"
        case revenueGrowth1y = "revenue_growth_1y"
        case profitGrowth1y = "profit_growth_1y"
        case rsi14 = "rsi_14"
        case near52wHigh = "near_52w_high"
        case near52wLow = "near_52w_low"
        case avgVolume = "avg_volume"
        case priceChange1d = "price_change_1d"
        case priceChange1w = "price_change_1w"
        case priceChange1m = "price_change_1m"
        case exchange, sector
        case marketCapCategory = "market_cap_category"
        case sortBy = "sort_by"
        case sortOrder = "sort_order"
    }
}

// MARK: - Screener Result

struct ScreenerResult: Codable, Identifiable, Equatable {
    var id: String { symbol }
    let symbol: String
    let companyName: String
    let sector: String?
    let ltp: Double
    let changePercent: Double
    let marketCap: Double?
    let peRatio: Double?
    let dividendYield: Double?
    let rsi14: Double?

    enum CodingKeys: String, CodingKey {
        case symbol
        case companyName = "company_name"
        case sector, ltp
        case changePercent = "change_percent"
        case marketCap = "market_cap"
        case peRatio = "pe_ratio"
        case dividendYield = "dividend_yield"
        case rsi14 = "rsi_14"
    }
}

struct ScreenerResponse: Codable, Equatable {
    let results: [ScreenerResult]
    let totalCount: Int
    let page: Int
    let pageSize: Int

    enum CodingKeys: String, CodingKey {
        case results
        case totalCount = "total_count"
        case page
        case pageSize = "page_size"
    }
}

// MARK: - Screener Preset

struct ScreenerPreset: Codable, Identifiable, Equatable {
    let id: String
    let name: String
    let isPrebuilt: Bool
    let filters: ScreenerFilter

    enum CodingKeys: String, CodingKey {
        case id, name
        case isPrebuilt = "is_prebuilt"
        case filters
    }
}
