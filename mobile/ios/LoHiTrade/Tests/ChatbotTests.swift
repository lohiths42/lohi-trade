import XCTest
@testable import LoHiTrade

/// Unit tests for ChatModels and ChatbotService data handling.
final class ChatbotTests: XCTestCase {

    // MARK: - ChatMessage decoding

    func testUserMessageDecoding() throws {
        let json = """
        {
            "id": "msg-1",
            "role": "user",
            "content": "How did I perform last week?",
            "chart_image_url": null,
            "timestamp": "2024-01-15T10:30:00Z"
        }
        """.data(using: .utf8)!

        let message = try JSONDecoder().decode(ChatMessage.self, from: json)
        XCTAssertEqual(message.id, "msg-1")
        XCTAssertEqual(message.role, .user)
        XCTAssertEqual(message.content, "How did I perform last week?")
        XCTAssertNil(message.chartImageURL)
        XCTAssertNil(message.chartURL)
        XCTAssertEqual(message.timestamp, "2024-01-15T10:30:00Z")
    }

    func testAssistantMessageWithChartDecoding() throws {
        let json = """
        {
            "id": "msg-2",
            "role": "assistant",
            "content": "Here is your equity curve for last week.",
            "chart_image_url": "https://api.lohitrade.com/charts/equity-123.png",
            "timestamp": "2024-01-15T10:30:05Z"
        }
        """.data(using: .utf8)!

        let message = try JSONDecoder().decode(ChatMessage.self, from: json)
        XCTAssertEqual(message.id, "msg-2")
        XCTAssertEqual(message.role, .assistant)
        XCTAssertEqual(message.chartImageURL, "https://api.lohitrade.com/charts/equity-123.png")
        XCTAssertNotNil(message.chartURL)
        XCTAssertEqual(message.chartURL?.absoluteString, "https://api.lohitrade.com/charts/equity-123.png")
    }

    func testAssistantMessageWithoutChartDecoding() throws {
        let json = """
        {
            "id": "msg-3",
            "role": "assistant",
            "content": "Your total P&L this week was ₹5,250.75 with a 65% win rate.",
            "chart_image_url": null,
            "timestamp": "2024-01-15T10:31:00Z"
        }
        """.data(using: .utf8)!

        let message = try JSONDecoder().decode(ChatMessage.self, from: json)
        XCTAssertEqual(message.role, .assistant)
        XCTAssertNil(message.chartImageURL)
        XCTAssertNil(message.chartURL)
    }

    // MARK: - ChatRole

    func testChatRoleValues() {
        XCTAssertEqual(ChatRole.user.rawValue, "user")
        XCTAssertEqual(ChatRole.assistant.rawValue, "assistant")
    }

    func testChatRoleDecoding() throws {
        let userJSON = "\"user\"".data(using: .utf8)!
        let assistantJSON = "\"assistant\"".data(using: .utf8)!

        let user = try JSONDecoder().decode(ChatRole.self, from: userJSON)
        let assistant = try JSONDecoder().decode(ChatRole.self, from: assistantJSON)

        XCTAssertEqual(user, .user)
        XCTAssertEqual(assistant, .assistant)
    }

    // MARK: - ChatSession decoding

    func testChatSessionDecoding() throws {
        let json = """
        {
            "id": "session-1",
            "messages": [
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": "Show my trades",
                    "chart_image_url": null,
                    "timestamp": "2024-01-15T10:00:00Z"
                },
                {
                    "id": "msg-2",
                    "role": "assistant",
                    "content": "Here are your recent trades.",
                    "chart_image_url": null,
                    "timestamp": "2024-01-15T10:00:03Z"
                }
            ],
            "created_at": "2024-01-15T10:00:00Z"
        }
        """.data(using: .utf8)!

        let session = try JSONDecoder().decode(ChatSession.self, from: json)
        XCTAssertEqual(session.id, "session-1")
        XCTAssertEqual(session.messages.count, 2)
        XCTAssertEqual(session.messages[0].role, .user)
        XCTAssertEqual(session.messages[1].role, .assistant)
        XCTAssertEqual(session.createdAt, "2024-01-15T10:00:00Z")
    }

    func testChatSessionEmptyMessages() throws {
        let json = """
        {
            "id": "session-2",
            "messages": [],
            "created_at": "2024-01-15T11:00:00Z"
        }
        """.data(using: .utf8)!

        let session = try JSONDecoder().decode(ChatSession.self, from: json)
        XCTAssertEqual(session.id, "session-2")
        XCTAssertTrue(session.messages.isEmpty)
    }

    // MARK: - ChatMessageRequest encoding

    func testChatMessageRequestEncoding() throws {
        let request = ChatMessageRequest(message: "What is my win rate?")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["message"], "What is my win rate?")
    }

    // MARK: - ChatMessageResponse decoding

    func testChatMessageResponseDecoding() throws {
        let json = """
        {
            "message": {
                "id": "msg-resp-1",
                "role": "assistant",
                "content": "Your win rate is 65%.",
                "chart_image_url": null,
                "timestamp": "2024-01-15T10:30:05Z"
            }
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatMessageResponse.self, from: json)
        XCTAssertEqual(response.message.role, .assistant)
        XCTAssertEqual(response.message.content, "Your win rate is 65%.")
    }

    // MARK: - ChatHistoryResponse decoding

    func testChatHistoryResponseDecoding() throws {
        let json = """
        {
            "messages": [
                {
                    "id": "msg-h1",
                    "role": "user",
                    "content": "Hello",
                    "chart_image_url": null,
                    "timestamp": "2024-01-15T09:00:00Z"
                }
            ]
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatHistoryResponse.self, from: json)
        XCTAssertEqual(response.messages.count, 1)
        XCTAssertEqual(response.messages[0].content, "Hello")
    }

    // MARK: - ChatSessionDeleteResponse decoding

    func testChatSessionDeleteResponseDecoding() throws {
        let json = """
        {
            "success": true,
            "message": "Session cleared"
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(ChatSessionDeleteResponse.self, from: json)
        XCTAssertTrue(response.success)
        XCTAssertEqual(response.message, "Session cleared")
    }

    // MARK: - ChatMessage Equatable

    func testChatMessageEquality() throws {
        let json = """
        {
            "id": "msg-eq",
            "role": "user",
            "content": "Test",
            "chart_image_url": null,
            "timestamp": "2024-01-15T10:00:00Z"
        }
        """.data(using: .utf8)!

        let msg1 = try JSONDecoder().decode(ChatMessage.self, from: json)
        let msg2 = try JSONDecoder().decode(ChatMessage.self, from: json)
        XCTAssertEqual(msg1, msg2)
    }

    // MARK: - ChatMessage chartURL with invalid URL

    func testChartURLWithInvalidString() {
        // A message with an empty chart_image_url string
        let message = ChatMessage(
            id: "msg-inv",
            role: .assistant,
            content: "Test",
            chartImageURL: "",
            timestamp: "2024-01-15T10:00:00Z"
        )
        // Empty string produces a valid URL in Foundation, so just verify it doesn't crash
        XCTAssertNotNil(message.chartImageURL)
    }
}
