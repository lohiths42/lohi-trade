import Foundation

// MARK: - Price Tick (WebSocket)

struct PriceTick: Codable, Equatable {
    let symbol: String
    let ltp: Double
    let change: Double
    let changePercent: Double
    let volume: Int
    let high: Double
    let low: Double
    let open: Double
    let close: Double
    let timestamp: String

    enum CodingKeys: String, CodingKey {
        case symbol, ltp, change
        case changePercent = "change_percent"
        case volume, high, low, open, close, timestamp
    }
}

// MARK: - Order Book Depth

struct OrderBookLevel: Codable, Equatable {
    let price: Double
    let quantity: Int
}

struct OrderBookDepth: Codable, Equatable {
    let symbol: String
    let bids: [OrderBookLevel]
    let asks: [OrderBookLevel]
    let timestamp: String
}

// MARK: - WebSocket Message

enum WebSocketMessageType: String, Codable {
    case priceTick = "price_tick"
    case orderBookUpdate = "order_book"
    case orderUpdate = "order_update"
    case killSwitchAlert = "kill_switch"
}

struct WebSocketMessage: Codable {
    let type: WebSocketMessageType
    let data: WebSocketPayload
}

enum WebSocketPayload: Codable {
    case priceTick(PriceTick)
    case raw(Data)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let tick = try? container.decode(PriceTick.self) {
            self = .priceTick(tick)
        } else {
            let data = try container.decode(Data.self)
            self = .raw(data)
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .priceTick(let tick):
            try container.encode(tick)
        case .raw(let data):
            try container.encode(data)
        }
    }
}
