import SwiftUI

/// Notification center for trade, system, and alert notifications (Req 13.9).
struct NotificationCenterView: View {
    @State private var notifications: [AppNotification] = []
    @State private var isLoading = false
    @State private var selectedFilter: NotificationFilter = .all

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Filter picker
                Picker("Filter", selection: $selectedFilter) {
                    ForEach(NotificationFilter.allCases, id: \.self) { filter in
                        Text(filter.title).tag(filter)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.vertical, 8)

                // Notification list
                List {
                    let filtered = filteredNotifications
                    if filtered.isEmpty && !isLoading {
                        ContentUnavailableView(
                            "No Notifications",
                            systemImage: "bell.slash",
                            description: Text("You're all caught up.")
                        )
                    } else {
                        ForEach(filtered) { notification in
                            NotificationRow(notification: notification)
                        }
                    }
                }
                .listStyle(.plain)
            }
            .navigationTitle("Notifications")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Mark All Read") {
                        Task { await markAllRead() }
                    }
                    .font(.caption)
                }
            }
            .refreshable {
                await fetchNotifications()
            }
            .task {
                await fetchNotifications()
            }
        }
    }

    private var filteredNotifications: [AppNotification] {
        switch selectedFilter {
        case .all: return notifications
        case .trade: return notifications.filter { $0.type == .trade }
        case .system: return notifications.filter { $0.type == .system }
        case .alert: return notifications.filter { $0.type == .alert }
        }
    }

    private func fetchNotifications() async {
        isLoading = true
        defer { isLoading = false }
        do {
            notifications = try await APIClient.shared.authenticatedRequest(
                .get, path: "/notifications"
            )
        } catch {
            print("[Notifications] Fetch error: \(error.localizedDescription)")
        }
    }

    private func markAllRead() async {
        do {
            let _: EmptyResponse = try await APIClient.shared.authenticatedRequest(
                .post, path: "/notifications/mark-all-read"
            )
            for i in notifications.indices {
                notifications[i].isRead = true
            }
        } catch {
            print("[Notifications] Mark read error: \(error.localizedDescription)")
        }
    }
}

// MARK: - Notification Models

struct AppNotification: Codable, Identifiable {
    let id: String
    let type: NotificationType
    let title: String
    let message: String
    var isRead: Bool
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, type, title, message
        case isRead = "is_read"
        case createdAt = "created_at"
    }
}

enum NotificationType: String, Codable {
    case trade = "TRADE"
    case system = "SYSTEM"
    case alert = "ALERT"
}

enum NotificationFilter: CaseIterable {
    case all, trade, system, alert

    var title: String {
        switch self {
        case .all: return "All"
        case .trade: return "Trades"
        case .system: return "System"
        case .alert: return "Alerts"
        }
    }
}

// MARK: - Notification Row

struct NotificationRow: View {
    let notification: AppNotification

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: iconName)
                .foregroundColor(iconColor)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(notification.title)
                        .font(.subheadline)
                        .fontWeight(notification.isRead ? .regular : .bold)
                    Spacer()
                    if !notification.isRead {
                        Circle()
                            .fill(.blue)
                            .frame(width: 8, height: 8)
                    }
                }
                Text(notification.message)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                Text(notification.createdAt)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
        .opacity(notification.isRead ? 0.7 : 1.0)
    }

    private var iconName: String {
        switch notification.type {
        case .trade: return "arrow.left.arrow.right.circle.fill"
        case .system: return "gear.circle.fill"
        case .alert: return "exclamationmark.triangle.fill"
        }
    }

    private var iconColor: Color {
        switch notification.type {
        case .trade: return .blue
        case .system: return .gray
        case .alert: return .orange
        }
    }
}
