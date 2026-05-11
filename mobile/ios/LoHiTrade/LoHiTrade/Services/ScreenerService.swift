import Foundation

/// Stock screener API service (Req 13.8).
@MainActor
final class ScreenerService: ObservableObject {
    static let shared = ScreenerService()

    @Published var results: ScreenerResponse?
    @Published var presets: [ScreenerPreset] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    // MARK: - Search

    func search(filter: ScreenerFilter, page: Int = 1) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            results = try await apiClient.authenticatedRequest(
                .post, path: "/screener/search?page=\(page)", body: filter
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Presets

    func fetchPresets() async {
        do {
            presets = try await apiClient.authenticatedRequest(.get, path: "/screener/presets")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func fetchTemplates() async {
        do {
            let templates: [ScreenerPreset] = try await apiClient.authenticatedRequest(
                .get, path: "/screener/templates"
            )
            // Merge templates into presets list
            let existingIds = Set(presets.map(\.id))
            let newTemplates = templates.filter { !existingIds.contains($0.id) }
            presets.append(contentsOf: newTemplates)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func applyPreset(_ preset: ScreenerPreset) async {
        await search(filter: preset.filters)
    }
}
