import Foundation

// MARK: - Chat Message (Req 18.1)

/// Role of a chat message participant.
enum ChatRole: String, Codable, Equatable {
    case user
    case assistant
}

/// A single message in a chatbot conversation.
struct ChatMessage: Codable, Identifiable, Equatable {
    let id: String
    let role: ChatRole
    let content: String
    let chartImageURL: String?
    let timestamp: String

    enum CodingKeys: String, CodingKey {
        case id, role, content
        case chartImageURL = "chart_image_url"
        case timestamp
    }

    /// Convenience URL for the chart image, if present.
    var chartURL: URL? {
        guard let chartImageURL else { return nil }
        return URL(string: chartImageURL)
    }
}

// MARK: - Chat Session

/// Represents a chatbot conversation session.
struct ChatSession: Codable, Identifiable, Equatable {
    let id: String
    let messages: [ChatMessage]
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, messages
        case createdAt = "created_at"
    }
}

// MARK: - API Request / Response

/// Request body for POST /chatbot/message.
struct ChatMessageRequest: Encodable {
    let message: String
}

/// Response from POST /chatbot/message.
struct ChatMessageResponse: Decodable {
    let message: ChatMessage
}

/// Response from GET /chatbot/history.
struct ChatHistoryResponse: Decodable {
    let messages: [ChatMessage]
}

/// Response from DELETE /chatbot/session.
struct ChatSessionDeleteResponse: Decodable {
    let success: Bool
    let message: String
}
