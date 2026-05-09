import SwiftUI

/// Main tab bar navigation for the app (Req 13.1-13.9).
struct MainTabView: View {
    @StateObject private var tradingService = TradingService.shared
    @StateObject private var webSocketService = WebSocketService.shared

    var body: some View {
        TabView {
            DashboardView()
                .tabItem {
                    Label("Dashboard", systemImage: "chart.bar.fill")
                }

            PositionsView()
                .tabItem {
                    Label("Positions", systemImage: "list.bullet.rectangle")
                }

            WatchlistView()
                .tabItem {
                    Label("Watchlist", systemImage: "star.fill")
                }

            ScreenerView()
                .tabItem {
                    Label("Screener", systemImage: "magnifyingglass")
                }

            NotificationCenterView()
                .tabItem {
                    Label("Alerts", systemImage: "bell.fill")
                }
        }
        .onAppear {
            webSocketService.connect()
        }
        .onDisappear {
            webSocketService.disconnect()
        }
    }
}
