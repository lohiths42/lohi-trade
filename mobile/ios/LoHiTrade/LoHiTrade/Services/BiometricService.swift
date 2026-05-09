import Foundation
import LocalAuthentication

/// Biometric authentication (Face ID / Touch ID) as secondary login (Req 12.3).
///
/// After initial JWT authentication, users can enable biometric unlock so
/// subsequent app opens skip the password prompt and use the stored tokens.
final class BiometricService {
    static let shared = BiometricService()

    /// The type of biometric available on this device.
    enum BiometricType {
        case none
        case touchID
        case faceID
    }

    /// Result of a biometric authentication attempt.
    enum AuthResult {
        case success
        case failure(Error)
        case notAvailable
        case cancelled
    }

    // MARK: - Availability

    /// Returns the biometric type available on the current device.
    func availableBiometricType() -> BiometricType {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
            return .none
        }
        switch context.biometryType {
        case .faceID: return .faceID
        case .touchID: return .touchID
        default: return .none
        }
    }

    /// Whether any biometric authentication is available.
    var isBiometricAvailable: Bool {
        availableBiometricType() != .none
    }

    // MARK: - Authentication

    /// Prompt the user for biometric authentication.
    func authenticate(reason: String = "Unlock LoHi-TRADE") async -> AuthResult {
        let context = LAContext()
        var error: NSError?

        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
            return .notAvailable
        }

        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: reason
            )
            return success ? .success : .failure(BiometricError.evaluationFailed)
        } catch let authError as LAError where authError.code == .userCancel || authError.code == .appCancel {
            return .cancelled
        } catch {
            return .failure(error)
        }
    }
}

enum BiometricError: LocalizedError {
    case evaluationFailed

    var errorDescription: String? {
        switch self {
        case .evaluationFailed:
            return "Biometric evaluation failed."
        }
    }
}
