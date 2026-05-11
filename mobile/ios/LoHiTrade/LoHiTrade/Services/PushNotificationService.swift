import Foundation
import UserNotifications
import FirebaseMessaging

/// Firebase Cloud Messaging push notification setup (Req 12.6).
///
/// Handles trade alerts, order status updates, and kill switch activations.
final class PushNotificationService {
    static let shared = PushNotificationService()

    /// FCM topics the app subscribes to.
    enum Topic: String {
        case tradeAlerts = "trade_alerts"
        case orderUpdates = "order_updates"
        case killSwitch = "kill_switch"
    }

    /// The current FCM registration token.
    private(set) var fcmToken: String?

    // MARK: - Configuration

    /// Configure Firebase Messaging. Call from AppDelegate.
    func configureFCM(delegate: MessagingDelegate) {
        Messaging.messaging().delegate = delegate
    }

    /// Request notification permissions from the user.
    func requestPermission() async -> Bool {
        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .badge, .sound]
            )
            return granted
        } catch {
            print("[Push] Permission request failed: \(error.localizedDescription)")
            return false
        }
    }

    // MARK: - Token handling

    /// Called when FCM provides a new registration token.
    func handleNewFCMToken(_ token: String) {
        fcmToken = token
        print("[Push] FCM token: \(token)")
        // Send token to backend for targeted push delivery
        Task {
            await registerTokenWithBackend(token)
        }
    }

    // MARK: - Topic subscriptions

    /// Subscribe to a push notification topic.
    func subscribe(to topic: Topic) {
        Messaging.messaging().subscribe(toTopic: topic.rawValue) { error in
            if let error {
                print("[Push] Subscribe to \(topic.rawValue) failed: \(error.localizedDescription)")
            }
        }
    }

    /// Unsubscribe from a push notification topic.
    func unsubscribe(from topic: Topic) {
        Messaging.messaging().unsubscribe(fromTopic: topic.rawValue) { error in
            if let error {
                print("[Push] Unsubscribe from \(topic.rawValue) failed: \(error.localizedDescription)")
            }
        }
    }

    /// Subscribe to all default topics after login.
    func subscribeToDefaults() {
        subscribe(to: .tradeAlerts)
        subscribe(to: .orderUpdates)
        subscribe(to: .killSwitch)
    }

    // MARK: - Notification handling

    /// Handle a notification tap — route to the appropriate screen.
    func handleNotificationTap(_ userInfo: [AnyHashable: Any]) {
        guard let type = userInfo["type"] as? String else { return }

        switch type {
        case "trade_alert":
            NotificationCenter.default.post(name: .navigateToTrades, object: nil, userInfo: userInfo)
        case "order_update":
            NotificationCenter.default.post(name: .navigateToOrders, object: nil, userInfo: userInfo)
        case "kill_switch":
            NotificationCenter.default.post(name: .navigateToKillSwitch, object: nil, userInfo: userInfo)
        default:
            break
        }
    }

    // MARK: - Backend registration

    private func registerTokenWithBackend(_ token: String) async {
        // Send FCM token to backend so it can target this device
        // This is a fire-and-forget call; failures are logged but not blocking
        do {
            struct FCMTokenBody: Encodable {
                let fcmToken: String
                enum CodingKeys: String, CodingKey { case fcmToken = "fcm_token" }
            }
            struct EmptyResponse: Decodable {}
            let _: EmptyResponse = try await APIClient.shared.authenticatedRequest(
                .post,
                path: "/users/fcm-token",
                body: FCMTokenBody(fcmToken: token)
            )
        } catch {
            print("[Push] Failed to register FCM token with backend: \(error.localizedDescription)")
        }
    }
}

// MARK: - Notification names for navigation

extension Notification.Name {
    static let navigateToTrades = Notification.Name("navigateToTrades")
    static let navigateToOrders = Notification.Name("navigateToOrders")
    static let navigateToKillSwitch = Notification.Name("navigateToKillSwitch")
}
