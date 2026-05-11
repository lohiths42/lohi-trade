import Foundation

/// Watchlist CRUD API service (Req 13.7).
@MainActor
final class WatchlistService: ObservableObject {
    static let shared = WatchlistService()

    @Published var watchlists: [Watchlist] = []
    @Published var currentWatchlist: WatchlistDetail?
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    // MARK: - List

    func fetchWatchlists() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            watchlists = try await apiClient.authenticatedRequest(.get, path: "/watchlists")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Detail

    func fetchWatchlistDetail(id: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            currentWatchlist = try await apiClient.authenticatedRequest(.get, path: "/watchlists/\(id)")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Create

    func createWatchlist(name: String) async -> Bool {
        errorMessage = nil
        do {
            let body = CreateWatchlistRequest(name: name)
            let _: WatchlistResponse = try await apiClient.authenticatedRequest(
                .post, path: "/watchlists", body: body
            )
            await fetchWatchlists()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Rename

    func renameWatchlist(id: String, name: String) async -> Bool {
        errorMessage = nil
        do {
            let body = RenameWatchlistRequest(name: name)
            let _: WatchlistResponse = try await apiClient.authenticatedRequest(
                .put, path: "/watchlists/\(id)", body: body
            )
            await fetchWatchlists()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Delete

    func deleteWatchlist(id: String) async -> Bool {
        errorMessage = nil
        do {
            let _: EmptyResponse = try await apiClient.authenticatedRequest(
                .delete, path: "/watchlists/\(id)"
            )
            watchlists.removeAll { $0.id == id }
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    // MARK: - Add/Remove Securities

    func addSecurity(watchlistId: String, symbol: String) async -> Bool {
        errorMessage = nil
        do {
            let body = AddSecurityRequest(symbol: symbol)
            let _: EmptyResponse = try await apiClient.authenticatedRequest(
                .post, path: "/watchlists/\(watchlistId)/securities", body: body
            )
            await fetchWatchlistDetail(id: watchlistId)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func removeSecurity(watchlistId: String, symbol: String) async -> Bool {
        errorMessage = nil
        do {
            let _: EmptyResponse = try await apiClient.authenticatedRequest(
                .delete, path: "/watchlists/\(watchlistId)/securities/\(symbol)"
            )
            await fetchWatchlistDetail(id: watchlistId)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}
