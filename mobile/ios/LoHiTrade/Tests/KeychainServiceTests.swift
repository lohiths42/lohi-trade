import XCTest
@testable import LoHiTrade

/// Unit tests for KeychainService — secure token storage in iOS Keychain (Req 12.4).
final class KeychainServiceTests: XCTestCase {
    private var keychain: KeychainService!

    override func setUp() {
        super.setUp()
        keychain = KeychainService.shared
        // Clean up before each test
        keychain.deleteAll()
    }

    override func tearDown() {
        keychain.deleteAll()
        super.tearDown()
    }

    // MARK: - Save and retrieve

    func testSaveAndGetAccessToken() {
        let token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test-access-token"
        let saved = keychain.save(token, for: .accessToken)
        XCTAssertTrue(saved, "Should save access token successfully")

        let retrieved = keychain.get(.accessToken)
        XCTAssertEqual(retrieved, token, "Retrieved token should match saved token")
    }

    func testSaveAndGetRefreshToken() {
        let token = "refresh-token-abc123"
        let saved = keychain.save(token, for: .refreshToken)
        XCTAssertTrue(saved)

        let retrieved = keychain.get(.refreshToken)
        XCTAssertEqual(retrieved, token)
    }

    // MARK: - Overwrite

    func testOverwriteExistingToken() {
        keychain.save("old-token", for: .accessToken)
        keychain.save("new-token", for: .accessToken)

        let retrieved = keychain.get(.accessToken)
        XCTAssertEqual(retrieved, "new-token", "Should overwrite with new value")
    }

    // MARK: - Delete

    func testDeleteToken() {
        keychain.save("token-to-delete", for: .accessToken)
        let deleted = keychain.delete(.accessToken)
        XCTAssertTrue(deleted)

        let retrieved = keychain.get(.accessToken)
        XCTAssertNil(retrieved, "Token should be nil after deletion")
    }

    func testDeleteNonExistentToken() {
        // Should not crash or fail
        let deleted = keychain.delete(.accessToken)
        XCTAssertTrue(deleted, "Deleting non-existent key should succeed (errSecItemNotFound)")
    }

    // MARK: - Delete all

    func testDeleteAll() {
        keychain.save("access", for: .accessToken)
        keychain.save("refresh", for: .refreshToken)

        keychain.deleteAll()

        XCTAssertNil(keychain.get(.accessToken))
        XCTAssertNil(keychain.get(.refreshToken))
    }

    // MARK: - Get non-existent

    func testGetNonExistentKey() {
        let value = keychain.get(.accessToken)
        XCTAssertNil(value, "Should return nil for non-existent key")
    }

    // MARK: - Empty string

    func testSaveEmptyString() {
        let saved = keychain.save("", for: .accessToken)
        XCTAssertTrue(saved)

        let retrieved = keychain.get(.accessToken)
        XCTAssertEqual(retrieved, "")
    }

    // MARK: - Long token

    func testSaveLongToken() {
        let longToken = String(repeating: "a", count: 4096)
        let saved = keychain.save(longToken, for: .accessToken)
        XCTAssertTrue(saved)

        let retrieved = keychain.get(.accessToken)
        XCTAssertEqual(retrieved, longToken)
    }
}
