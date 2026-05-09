import Foundation
import SwiftUI

/// Main authentication service orchestrating JWT auth, biometric login,
/// token storage, and automatic refresh (Req 12.2, 12.3, 12.4, 12.5).
@MainActor
final class AuthService: ObservableObject {
    @Published var isAuthenticated = false
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient: APIClient
    private let keychain: KeychainService
    private let biometric: BiometricService
    private var refreshTimer: Timer?

    init(
        apiClient: APIClient = .shared,
        keychain: KeychainService = .shared,
        biometric: BiometricService = .shared
    ) {
        self.apiClient = apiClient
        self.keychain = keychain
        self.biometric = biometric

        // Check for existing valid tokens on launch
        if let token = keychain.get(.accessToken),
           let payload = JWTDecoder.decode(token),
           !payload.isExpired {
            isAuthenticated = true
            scheduleTokenRefresh(payload: payload)
        } else if keychain.get(.refreshToken) != nil {
            // Access token expired but refresh token exists — try refresh
            Task { await attemptSilentRefresh() }
        }
    }

    // MARK: - Email/password login (Req 12.2)

    func login(email: String, password: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let body = LoginRequest(email: email, password: password)
            let response: TokenResponse = try await apiClient.request(.post, path: "/auth/login", body: body)
            storeTokens(response)
            isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Registration

    func register(email: String, password: String, phone: String, name: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let body = RegisterRequest(email: email, password: password, phone: phone, name: name)
            let _: RegisterResponse = try await apiClient.request(.post, path: "/auth/register", body: body)
            // After registration, auto-login
            await login(email: email, password: password)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Social login (Google / Apple)

    func loginWithGoogle(idToken: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let body = GoogleLoginRequest(idToken: idToken)
            let response: TokenResponse = try await apiClient.request(.post, path: "/auth/google", body: body)
            storeTokens(response)
            isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loginWithApple(authCode: String, userName: String?) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let body = AppleLoginRequest(authCode: authCode, userName: userName)
            let response: TokenResponse = try await apiClient.request(.post, path: "/auth/apple", body: body)
            storeTokens(response)
            isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Biometric login (Req 12.3)

    /// Attempt biometric authentication. On success, verifies stored tokens are valid.
    func loginWithBiometric() async {
        guard biometric.isBiometricAvailable else {
            errorMessage = "Biometric authentication is not available on this device."
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        let result = await biometric.authenticate(reason: "Log in to LoHi-TRADE")
        switch result {
        case .success:
            // Biometric passed — check if we have valid tokens
            if let token = keychain.get(.accessToken),
               let payload = JWTDecoder.decode(token),
               !payload.isExpired {
                isAuthenticated = true
                scheduleTokenRefresh(payload: payload)
            } else {
                // Try refreshing
                await attemptSilentRefresh()
            }
        case .failure(let error):
            errorMessage = error.localizedDescription
        case .notAvailable:
            errorMessage = "Biometric authentication is not available."
        case .cancelled:
            break // User cancelled, no error
        }
    }

    // MARK: - Logout

    func logout() async {
        refreshTimer?.invalidate()
        refreshTimer = nil
        keychain.deleteAll()
        isAuthenticated = false
        errorMessage = nil
    }

    // MARK: - Token management (Req 12.4, 12.5)

    private func storeTokens(_ response: TokenResponse) {
        keychain.save(response.accessToken, for: .accessToken)
        keychain.save(response.refreshToken, for: .refreshToken)

        if let payload = JWTDecoder.decode(response.accessToken) {
            scheduleTokenRefresh(payload: payload)
        }
    }

    /// Schedule a timer to refresh the access token 60 seconds before expiry.
    private func scheduleTokenRefresh(payload: JWTPayload) {
        refreshTimer?.invalidate()
        let refreshIn = max(payload.secondsUntilExpiry - 60, 1)
        refreshTimer = Timer.scheduledTimer(withTimeInterval: refreshIn, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                await self?.attemptSilentRefresh()
            }
        }
    }

    /// Silently refresh the access token using the stored refresh token.
    private func attemptSilentRefresh() async {
        do {
            try await apiClient.refreshTokenIfNeeded()
            if let token = keychain.get(.accessToken),
               let payload = JWTDecoder.decode(token),
               !payload.isExpired {
                isAuthenticated = true
                scheduleTokenRefresh(payload: payload)
            } else {
                isAuthenticated = false
            }
        } catch {
            isAuthenticated = false
        }
    }
}

// MARK: - JWT Decoder (local, no verification — server is source of truth)

enum JWTDecoder {
    /// Decode a JWT token's payload without signature verification.
    /// Used only for reading expiry locally; the server validates signatures.
    static func decode(_ token: String) -> JWTPayload? {
        let parts = token.split(separator: ".")
        guard parts.count == 3 else { return nil }

        let payload = String(parts[1])
        guard let data = base64URLDecode(payload) else { return nil }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let sub = json["sub"] as? String,
              let exp = json["exp"] as? Int,
              let iat = json["iat"] as? Int else {
            return nil
        }

        return JWTPayload(
            sub: sub,
            email: json["email"] as? String ?? "",
            role: json["role"] as? String ?? "TRADER",
            type: json["type"] as? String ?? "access",
            iat: iat,
            exp: exp
        )
    }

    private static func base64URLDecode(_ string: String) -> Data? {
        var base64 = string
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        // Pad to multiple of 4
        let remainder = base64.count % 4
        if remainder > 0 {
            base64 += String(repeating: "=", count: 4 - remainder)
        }
        return Data(base64Encoded: base64)
    }
}
