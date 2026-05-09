import Foundation

/// User roles matching backend RBAC.
enum UserRole: String, Codable {
    case admin = "ADMIN"
    case trader = "TRADER"
    case viewer = "VIEWER"
}

/// User model matching the backend `users` table.
struct User: Codable, Identifiable, Equatable {
    let id: String
    let email: String
    let phone: String?
    let name: String
    let role: UserRole
    let isOnboarded: Bool
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, email, phone, name, role
        case isOnboarded = "is_onboarded"
        case createdAt = "created_at"
    }
}
