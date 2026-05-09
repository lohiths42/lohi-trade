import Foundation

/// HTTP client for communicating with the FastAPI backend (Req 12.2).
///
/// The base URL is configurable. All authenticated requests include the
/// JWT Bearer token and automatically refresh on 401 responses.
final class APIClient {
    static let shared = APIClient()

    /// Configurable backend API base URL.
    var baseURL: String {
        get { _baseURL }
        set { _baseURL = newValue.hasSuffix("/") ? String(newValue.dropLast()) : newValue }
    }
    private var _baseURL: String

    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(
        baseURL: String = ProcessInfo.processInfo.environment["API_BASE_URL"] ?? "https://api.lohitrade.com",
        session: URLSession = .shared
    ) {
        self._baseURL = baseURL.hasSuffix("/") ? String(baseURL.dropLast()) : baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - Public API

    /// Perform an unauthenticated request (login, register).
    func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil
    ) async throws -> T {
        let request = try buildRequest(method: method, path: path, body: body, token: nil)
        return try await execute(request)
    }

    /// Perform an authenticated request with automatic token refresh on 401.
    func authenticatedRequest<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil
    ) async throws -> T {
        // Get current access token
        guard let accessToken = KeychainService.shared.get(.accessToken) else {
            throw APIError.unauthorized
        }

        // Check if token is about to expire and proactively refresh
        if let payload = JWTDecoder.decode(accessToken), payload.expiresWithin(60) {
            try await refreshTokenIfNeeded()
        }

        guard let token = KeychainService.shared.get(.accessToken) else {
            throw APIError.unauthorized
        }

        let req = try buildRequest(method: method, path: path, body: body, token: token)

        do {
            return try await execute(req)
        } catch APIError.unauthorized {
            // Token expired mid-flight — try refresh once
            try await refreshTokenIfNeeded()
            guard let newToken = KeychainService.shared.get(.accessToken) else {
                throw APIError.unauthorized
            }
            let retryReq = try buildRequest(method: method, path: path, body: body, token: newToken)
            return try await execute(retryReq)
        }
    }

    // MARK: - Token refresh (Req 12.5)

    private var isRefreshing = false

    func refreshTokenIfNeeded() async throws {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }

        guard let refreshToken = KeychainService.shared.get(.refreshToken) else {
            throw APIError.unauthorized
        }

        let body = RefreshTokenRequest(refreshToken: refreshToken)
        let response: TokenResponse = try await request(.post, path: "/auth/refresh", body: body)

        KeychainService.shared.save(response.accessToken, for: .accessToken)
        KeychainService.shared.save(response.refreshToken, for: .refreshToken)
    }

    // MARK: - Internals

    private func buildRequest(
        method: HTTPMethod,
        path: String,
        body: (any Encodable)?,
        token: String?
    ) throws -> URLRequest {
        guard let url = URL(string: _baseURL + path) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body {
            request.httpBody = try encoder.encode(body)
        }

        return request
    }

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        switch httpResponse.statusCode {
        case 200...299:
            return try decoder.decode(T.self, from: data)
        case 401:
            throw APIError.unauthorized
        case 429:
            throw APIError.rateLimited
        default:
            if let errorBody = try? decoder.decode(ErrorResponse.self, from: data) {
                throw APIError.serverError(httpResponse.statusCode, errorBody.detail)
            }
            throw APIError.serverError(httpResponse.statusCode, "Unknown error")
        }
    }
}

// MARK: - Supporting types

enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case delete = "DELETE"
}

enum APIError: LocalizedError, Equatable {
    case invalidURL
    case invalidResponse
    case unauthorized
    case rateLimited
    case serverError(Int, String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid URL"
        case .invalidResponse: return "Invalid server response"
        case .unauthorized: return "Authentication required"
        case .rateLimited: return "Too many requests. Please try again later."
        case .serverError(let code, let msg): return "Server error (\(code)): \(msg)"
        }
    }
}
