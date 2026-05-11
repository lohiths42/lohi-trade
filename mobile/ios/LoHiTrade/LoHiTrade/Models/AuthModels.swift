import Foundation

// MARK: - Request models

struct LoginRequest: Encodable {
    let email: String
    let password: String
}

struct RegisterRequest: Encodable {
    let email: String
    let password: String
    let phone: String
    let name: String
}

struct GoogleLoginRequest: Encodable {
    let idToken: String

    enum CodingKeys: String, CodingKey {
        case idToken = "id_token"
    }
}

struct AppleLoginRequest: Encodable {
    let authCode: String
    let userName: String?

    enum CodingKeys: String, CodingKey {
        case authCode = "auth_code"
        case userName = "user_name"
    }
}

struct RefreshTokenRequest: Encodable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

// MARK: - Response models

struct TokenResponse: Decodable, Equatable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
    }
}

struct RegisterResponse: Decodable {
    let userId: String
    let email: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case email, message
    }
}

struct ErrorResponse: Decodable {
    let detail: String
}

// MARK: - JWT payload (decoded locally for expiry checks)

struct JWTPayload {
    let sub: String
    let email: String
    let role: String
    let type: String
    let iat: Int
    let exp: Int

    /// Seconds remaining until token expires.
    var secondsUntilExpiry: TimeInterval {
        TimeInterval(exp) - Date().timeIntervalSince1970
    }

    /// Whether the token has expired.
    var isExpired: Bool { secondsUntilExpiry <= 0 }

    /// Whether the token will expire within the given threshold (default 60s).
    func expiresWithin(_ seconds: TimeInterval = 60) -> Bool {
        secondsUntilExpiry < seconds
    }
}
