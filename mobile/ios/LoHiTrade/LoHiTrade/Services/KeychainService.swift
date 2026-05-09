import Foundation
import Security

/// Secure token storage using iOS Keychain (Req 12.4).
final class KeychainService {
    static let shared = KeychainService()

    private let serviceName = "com.lohitrade.ios"

    enum Key: String {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
    }

    // MARK: - Public API

    /// Save a string value to the Keychain.
    @discardableResult
    func save(_ value: String, for key: Key) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }
        return save(data: data, for: key.rawValue)
    }

    /// Retrieve a string value from the Keychain.
    func get(_ key: Key) -> String? {
        guard let data = getData(for: key.rawValue) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Delete a value from the Keychain.
    @discardableResult
    func delete(_ key: Key) -> Bool {
        return deleteData(for: key.rawValue)
    }

    /// Delete all tokens (used on logout).
    func deleteAll() {
        delete(.accessToken)
        delete(.refreshToken)
    }

    // MARK: - Internal (exposed for testing)

    func save(data: Data, for account: String) -> Bool {
        // Delete existing item first to avoid errSecDuplicateItem
        deleteData(for: account)

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]

        let status = SecItemAdd(query as CFDictionary, nil)
        return status == errSecSuccess
    }

    func getData(for account: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess else { return nil }
        return result as? Data
    }

    @discardableResult
    func deleteData(for account: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
        ]

        let status = SecItemDelete(query as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
}
