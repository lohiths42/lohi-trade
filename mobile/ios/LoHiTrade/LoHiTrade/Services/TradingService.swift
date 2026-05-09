import Foundation

/// Trading API service for positions, orders, kill switch, and analytics (Req 13.1-13.6).
@MainActor
final class TradingService: ObservableObject {
    static let shared = TradingService()

    @Published var dashboardSummary: DashboardSummary?
    @Published var positions: [Position] = []
    @Published var orders: [Order] = []
    @Published var signals: [Signal] = []
    @Published var killSwitchStatus: KillSwitchStatus?
    @Published var analyticsData: AnalyticsData?
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    // MARK: - Dashboard (Req 13.1)

    func fetchDashboard() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            async let summary: DashboardSummary = apiClient.authenticatedRequest(.get, path: "/dashboard/summary")
            async let pos: [Position] = apiClient.authenticatedRequest(.get, path: "/positions")
            async let sigs: [Signal] = apiClient.authenticatedRequest(.get, path: "/signals/recent")

            dashboardSummary = try await summary
            positions = try await pos
            signals = try await sigs
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Positions (Req 13.3)

    func fetchPositions() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            positions = try await apiClient.authenticatedRequest(.get, path: "/positions")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func closePosition(positionId: String) async -> Bool {
        errorMessage = nil
        do {
            let body = ClosePositionRequest(positionId: positionId)
            let _: ClosePositionResponse = try await apiClient.authenticatedRequest(
                .post, path: "/positions/close", body: body
            )
            await fetchPositions()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Orders (Req 13.4)

    func fetchOrders(page: Int = 1) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            orders = try await apiClient.authenticatedRequest(.get, path: "/orders?page=\(page)")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Kill Switch (Req 13.5)

    func fetchKillSwitchStatus() async {
        do {
            killSwitchStatus = try await apiClient.authenticatedRequest(.get, path: "/kill-switch/status")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func toggleKillSwitch(activate: Bool, reason: String? = nil) async -> Bool {
        errorMessage = nil
        do {
            let body = KillSwitchToggleRequest(activate: activate, reason: reason)
            let response: KillSwitchToggleResponse = try await apiClient.authenticatedRequest(
                .post, path: "/kill-switch/toggle", body: body
            )
            killSwitchStatus = KillSwitchStatus(
                isActive: response.isActive,
                activatedAt: response.isActive ? ISO8601DateFormatter().string(from: Date()) : nil,
                activatedBy: response.isActive ? "user" : nil,
                reason: reason
            )
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Analytics (Req 13.6)

    func fetchAnalytics(period: String = "30d") async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            analyticsData = try await apiClient.authenticatedRequest(
                .get, path: "/analytics?period=\(period)"
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
