import Foundation

/// API service for the Gen AI chatbot (Req 18.1, 20.7).
///
/// Communicates with POST /chatbot/message, GET /chatbot/history,
/// and DELETE /chatbot/session on the FastAPI backend.
@MainActor
final class ChatbotService: ObservableObject {
    static let shared = ChatbotService()

    @Published var messages: [ChatMessage] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    // MARK: - Send Message (Req 18.1)

    /// Send a user message and receive the assistant response.
    func sendMessage(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Append optimistic user message
        let userMessage = ChatMessage(
            id: UUID().uuidString,
            role: .user,
            content: trimmed,
            chartImageURL: nil,
            timestamp: ISO8601DateFormatter().string(from: Date())
        )
        messages.append(userMessage)

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let body = ChatMessageRequest(message: trimmed)
            let response: ChatMessageResponse = try await apiClient.authenticatedRequest(
                .post, path: "/chatbot/message", body: body
            )
            messages.append(response.message)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Fetch History

    /// Load conversation history for the current session.
    func fetchHistory() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let response: ChatHistoryResponse = try await apiClient.authenticatedRequest(
                .get, path: "/chatbot/history"
            )
            messages = response.messages
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Clear Session

    /// Delete the current chatbot session and clear local messages.
    func clearSession() async {
        errorMessage = nil

        do {
            let _: ChatSessionDeleteResponse = try await apiClient.authenticatedRequest(
                .delete, path: "/chatbot/session"
            )
            messages = []
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
