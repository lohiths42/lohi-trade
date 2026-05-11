import Foundation
import Network
import Combine

/// NWPathMonitor wrapper that publishes connectivity status and triggers
/// sync on connectivity restore within 5 seconds (Req 14.2, 14.3).
@MainActor
final class NetworkMonitor: ObservableObject {
    static let shared = NetworkMonitor()

    @Published private(set) var isConnected = true
    @Published private(set) var connectionType: ConnectionType = .unknown

    /// Fires when connectivity is restored after being offline.
    let connectivityRestored = PassthroughSubject<Void, Never>()

    private let monitor: NWPathMonitor
    private let queue = DispatchQueue(label: "com.lohitrade.networkmonitor")
    private var wasDisconnected = false
    private var syncTask: Task<Void, Never>?

    enum ConnectionType: String {
        case wifi, cellular, wiredEthernet, unknown
    }

    init(monitor: NWPathMonitor = NWPathMonitor()) {
        self.monitor = monitor
    }

    func start() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
                let connected = path.status == .satisfied
                self.isConnected = connected
                self.connectionType = self.mapConnectionType(path)

                if connected && self.wasDisconnected {
                    self.wasDisconnected = false
                    self.triggerSync()
                } else if !connected {
                    self.wasDisconnected = true
                }
            }
        }
        monitor.start(queue: queue)
    }

    func stop() {
        monitor.cancel()
        syncTask?.cancel()
    }

    // MARK: - Sync Trigger (Req 14.3)

    /// Triggers server sync within 5 seconds of connectivity restore.
    private func triggerSync() {
        syncTask?.cancel()
        syncTask = Task {
            // Small delay to let the network stabilize
            try? await Task.sleep(nanoseconds: 500_000_000) // 0.5s
            guard !Task.isCancelled else { return }
            connectivityRestored.send()
        }
    }

    private func mapConnectionType(_ path: NWPath) -> ConnectionType {
        if path.usesInterfaceType(.wifi) { return .wifi }
        if path.usesInterfaceType(.cellular) { return .cellular }
        if path.usesInterfaceType(.wiredEthernet) { return .wiredEthernet }
        return .unknown
    }
}
