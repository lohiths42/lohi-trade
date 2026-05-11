import XCTest
@testable import LoHiTrade

/// Unit tests for AuthService — JWT auth, token lifecycle, and JWT decoding.
final class AuthServiceTests: XCTestCase {

    // MARK: - JWT Decoder tests

    func testDecodeValidJWT() {
        // Create a JWT with known payload: {"sub":"user-123","email":"test@example.com","role":"TRADER","type":"access","iat":1700000000,"exp":1700000900}
        let header = base64URLEncode(#"{"alg":"HS256","typ":"JWT"}"#)
        let payload = base64URLEncode(#"{"sub":"user-123","email":"test@example.com","role":"TRADER","type":"access","iat":1700000000,"exp":1700000900}"#)
        let token = "\(header).\(payload).fake-signature"

        let decoded = JWTDecoder.decode(token)
        XCTAssertNotNil(decoded)
        XCTAssertEqual(decoded?.sub, "user-123")
        XCTAssertEqual(decoded?.email, "test@example.com")
        XCTAssertEqual(decoded?.role, "TRADER")
        XCTAssertEqual(decoded?.type, "access")
        XCTAssertEqual(decoded?.iat, 1700000000)
        XCTAssertEqual(decoded?.exp, 1700000900)
    }

    func testDecodeInvalidJWT() {
        XCTAssertNil(JWTDecoder.decode("not-a-jwt"))
        XCTAssertNil(JWTDecoder.decode(""))
        XCTAssertNil(JWTDecoder.decode("a.b"))
    }

    func testDecodeJWTMissingFields() {
        // Payload missing "sub"
        let header = base64URLEncode(#"{"alg":"HS256"}"#)
        let payload = base64URLEncode(#"{"email":"test@example.com"}"#)
        let token = "\(header).\(payload).sig"

        let decoded = JWTDecoder.decode(token)
        XCTAssertNil(decoded, "Should return nil when required fields are missing")
    }

    // MARK: - JWTPayload expiry logic

    func testPayloadIsExpired() {
        let pastPayload = JWTPayload(
            sub: "user-1", email: "a@b.com", role: "TRADER",
            type: "access", iat: 1000, exp: 1001
        )
        XCTAssertTrue(pastPayload.isExpired)
    }

    func testPayloadNotExpired() {
        let futureExp = Int(Date().timeIntervalSince1970) + 3600
        let payload = JWTPayload(
            sub: "user-1", email: "a@b.com", role: "TRADER",
            type: "access", iat: 1000, exp: futureExp
        )
        XCTAssertFalse(payload.isExpired)
    }

    func testPayloadExpiresWithinThreshold() {
        let soonExp = Int(Date().timeIntervalSince1970) + 30
        let payload = JWTPayload(
            sub: "user-1", email: "a@b.com", role: "TRADER",
            type: "access", iat: 1000, exp: soonExp
        )
        XCTAssertTrue(payload.expiresWithin(60), "Should be expiring within 60s")
        XCTAssertFalse(payload.expiresWithin(10), "Should not be expiring within 10s")
    }

    // MARK: - Token response model

    func testTokenResponseDecoding() throws {
        let json = """
        {
            "access_token": "abc123",
            "refresh_token": "def456",
            "token_type": "bearer"
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(TokenResponse.self, from: json)
        XCTAssertEqual(response.accessToken, "abc123")
        XCTAssertEqual(response.refreshToken, "def456")
        XCTAssertEqual(response.tokenType, "bearer")
    }

    func testRegisterResponseDecoding() throws {
        let json = """
        {
            "user_id": "uuid-123",
            "email": "test@example.com",
            "message": "Registration successful. Please verify your email."
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(RegisterResponse.self, from: json)
        XCTAssertEqual(response.userId, "uuid-123")
        XCTAssertEqual(response.email, "test@example.com")
    }

    // MARK: - Request model encoding

    func testLoginRequestEncoding() throws {
        let request = LoginRequest(email: "test@example.com", password: "Pass123!")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["email"], "test@example.com")
        XCTAssertEqual(json?["password"], "Pass123!")
    }

    func testRefreshTokenRequestEncoding() throws {
        let request = RefreshTokenRequest(refreshToken: "my-refresh-token")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["refresh_token"], "my-refresh-token")
    }

    func testGoogleLoginRequestEncoding() throws {
        let request = GoogleLoginRequest(idToken: "google-id-token-xyz")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        XCTAssertEqual(json?["id_token"], "google-id-token-xyz")
    }

    func testAppleLoginRequestEncoding() throws {
        let request = AppleLoginRequest(authCode: "apple-auth-code", userName: "John Doe")
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["auth_code"] as? String, "apple-auth-code")
        XCTAssertEqual(json?["user_name"] as? String, "John Doe")
    }

    func testAppleLoginRequestEncodingNilName() throws {
        let request = AppleLoginRequest(authCode: "code", userName: nil)
        let data = try JSONEncoder().encode(request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["auth_code"] as? String, "code")
        // user_name should be null or absent
        XCTAssertTrue(json?["user_name"] is NSNull || json?["user_name"] == nil)
    }

    // MARK: - APIError

    func testAPIErrorDescriptions() {
        XCTAssertNotNil(APIError.invalidURL.errorDescription)
        XCTAssertNotNil(APIError.unauthorized.errorDescription)
        XCTAssertNotNil(APIError.rateLimited.errorDescription)
        XCTAssertNotNil(APIError.serverError(500, "Internal").errorDescription)
    }

    // MARK: - Helpers

    private func base64URLEncode(_ string: String) -> String {
        Data(string.utf8)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
