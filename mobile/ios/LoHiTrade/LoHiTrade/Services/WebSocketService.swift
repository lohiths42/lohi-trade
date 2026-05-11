import Foundation

/// Real-time price ticker service via WebSocket (Req 12.7, 13.2).
///
/// Uses URLSessionWebSocketTask for persistent connection with automatic
/// reconnection on network changes.
@MainActor
final class WebSocketService: ObservableObject {
    static let shared = WebSocketService()

    @Published var priceTicks: [String: PriceTick] = [:]
    @Published var isConnected = false

    private var webSocketTask: URLSessionWebSocketTask?
    private var session: URLSession
    private var subscribedSymbols: Set<String> = []
    private var reconnectAttempts = 0
    private let maxReconnectAttempts = 10
    private let baseReconnectDelay: TimeInterval = 1.0

    init(session: URLSession = .shared) {
        self.session = session
    }

    // MARK: - Connection

    func connect() {
        guard !isConnected else { return }
        let baseURL = APIClient.shared.baseURL
            .replacingOccurrences(of: "https://", with: "wss://")
            .replacingOccurrences(of: "http://", with: "ws://")
        guard let url = URL(string: "\(baseURL)/ws/prices") else { return }

        var request = URLRequest(url: url)
        if let token = KeychainService.shared.get(.accessToken) {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        webSocketTask = session.webSocketTask(with: request)
        webSocketTask?.resume()
        isConnected = true
        reconnectAttempts = 0
        receiveMessage()

        // Re-subscribe to previously subscribed symbols
        if !subscribedSymbols.isEmpty {
            subscribe(to: Array(subscribedSymbols))
        }
    }

    func disconnect() {
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        reconnectAttempts = 0
    }

    // MARK: - Subscriptions

    func subscribe(to symbols: [String]) {
        subscribedSymbols.formUnion(symbols)
        guard isConnected else { return }

        let message: [String: Any] = [
            "action": "subscribe",
            "symbols": symbols
        ]
        send(message)
    }

    func unsubscribe(from symbols: [String]) {
        subscribedSymbols.subtract(symbols)
        guard isConnected else { return }

        let message: [String: Any] = [
            "action": "unsubscribe",
            "symbols": symbols
        ]
        send(message)
    }

    // MARK: - Internal

    private func send(_ dict: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: dict),
              let string = String(data: data, encoding: .utf8) else { return }
        webSocketTask?.send(.string(string)) { error in
            if let error {
                print("[WS] Send error: \(error.localizedDescription)")
            }
        }
    }

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .success(let message):
                    self.handleMessage(message)
                    self.receiveMessage()
                case .failure(let error):
                    print("[WS] Receive error: \(error.localizedDescription)")
                    self.isConnected = false
                    self.attemptReconnect()
                }
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        let data: Data
        switch message {
        case .string(let text):
            guard let d = text.data(using: .utf8) else { return }
            data = d
        case .data(let d):
            data = d
        @unknown default:
            return
        }

        if let tick = try? JSONDecoder().decode(PriceTick.self, from: data) {
            priceTicks[tick.symbol] = tick
        }
    }

    private func attemptReconnect() {
        guard reconnectAttempts < maxReconnectAttempts else {
            print("[WS] Max reconnect attempts reached")
            return
        }
        reconnectAttempts += 1
        let delay = baseReconnectDelay * pow(2.0, Double(reconnectAttempts - 1))
        let clampedDelay = min(delay, 30.0)

        Task {
            try? await Task.sleep(nanoseconds: UInt64(clampedDelay * 1_000_000_000))
            await MainActor.run {
                self.connect()
            }
        }
    }
}
