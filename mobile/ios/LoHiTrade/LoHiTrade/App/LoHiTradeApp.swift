import SwiftUI

@main
struct LoHiTradeApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var authService = AuthService()
    @StateObject private var networkMonitor = NetworkMonitor.shared

    var body: some Scene {
        WindowGroup {
            Group {
                if authService.isAuthenticated {
                    ContentView()
                        .environmentObject(authService)
                } else {
                    LoginView()
                        .environmentObject(authService)
                }
            }
            .onAppear {
                networkMonitor.start()
                // Prune expired image cache entries on launch
                ImageCacheService.shared.pruneExpiredEntries()
            }
        }
    }
}

/// Placeholder main content view after login.
struct ContentView: View {
    @EnvironmentObject var authService: AuthService

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Text("LoHi-TRADE Dashboard")
                    .font(.title)
                Button("Logout") {
                    Task { await authService.logout() }
                }
            }
            .navigationTitle("Dashboard")
        }
    }
}
