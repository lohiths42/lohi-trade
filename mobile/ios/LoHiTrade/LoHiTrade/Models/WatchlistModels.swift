import Foundation

// MARK: - Watchlist

struct Watchlist: Codable, Identifiable, Equatable {
    let id: String
    let name: String
    let isPrebuilt: Bool
    let itemCount: Int

    enum CodingKeys: String, CodingKey {
        case id, name
        case isPrebuilt = "is_prebuilt"
        case itemCount = "item_count"
    }
}

struct WatchlistItem: Codable, Identifiable, Equatable {
    var id: String { symbol }
    let symbol: String
    let companyName: String
    let ltp: Double?
    let change: Double?
    let changePercent: Double?
    let volume: Int?

    enum CodingKeys: String, CodingKey {
        case symbol
        case companyName = "company_name"
        case ltp, change
        case changePercent = "change_percent"
        case volume
    }
}

struct WatchlistDetail: Codable, Equatable {
    let id: String
    let name: String
    let isPrebuilt: Bool
    let items: [WatchlistItem]

    enum CodingKeys: String, CodingKey {
        case id, name
        case isPrebuilt = "is_prebuilt"
        case items
    }
}

// MARK: - Requests

struct CreateWatchlistRequest: Encodable {
    let name: String
}

struct RenameWatchlistRequest: Encodable {
    let name: String
}

struct AddSecurityRequest: Encodable {
    let symbol: String
}

// MARK: - Responses

struct WatchlistResponse: Decodable {
    let id: String
    let name: String
    let message: String?
}

struct EmptyResponse: Decodable {}
