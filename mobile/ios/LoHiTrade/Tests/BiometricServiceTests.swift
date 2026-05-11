import XCTest
@testable import LoHiTrade

/// Unit tests for BiometricService — Face ID / Touch ID availability and types (Req 12.3).
///
/// Note: Actual biometric evaluation requires a real device or simulator with
/// enrolled biometrics. These tests verify the service's logic and type mapping.
final class BiometricServiceTests: XCTestCase {
    private var biometricService: BiometricService!

    override func setUp() {
        super.setUp()
        biometricService = BiometricService.shared
    }

    // MARK: - BiometricType enum

    func testBiometricTypeValues() {
        // Verify all cases exist
        let types: [BiometricService.BiometricType] = [.none, .touchID, .faceID]
        XCTAssertEqual(types.count, 3)
    }

    // MARK: - AuthResult enum

    func testAuthResultCases() {
        // Verify all cases can be constructed
        let success = BiometricService.AuthResult.success
        let notAvailable = BiometricService.AuthResult.notAvailable
        let cancelled = BiometricService.AuthResult.cancelled
        let failure = BiometricService.AuthResult.failure(BiometricError.evaluationFailed)

        // Pattern matching works
        if case .success = success { } else { XCTFail("Expected success") }
        if case .notAvailable = notAvailable { } else { XCTFail("Expected notAvailable") }
        if case .cancelled = cancelled { } else { XCTFail("Expected cancelled") }
        if case .failure(let err) = failure {
            XCTAssertNotNil(err.localizedDescription)
        } else {
            XCTFail("Expected failure")
        }
    }

    // MARK: - BiometricError

    func testBiometricErrorDescription() {
        let error = BiometricError.evaluationFailed
        XCTAssertEqual(error.errorDescription, "Biometric evaluation failed.")
    }

    // MARK: - Availability check (CI/simulator will return .none)

    func testAvailableBiometricTypeReturnsValue() {
        // On CI/simulator without enrolled biometrics, this returns .none
        let type = biometricService.availableBiometricType()
        // Just verify it doesn't crash and returns a valid type
        XCTAssertTrue([BiometricService.BiometricType.none, .touchID, .faceID].contains(type))
    }

    func testIsBiometricAvailableConsistentWithType() {
        let type = biometricService.availableBiometricType()
        let available = biometricService.isBiometricAvailable
        if type == .none {
            XCTAssertFalse(available)
        } else {
            XCTAssertTrue(available)
        }
    }
}
