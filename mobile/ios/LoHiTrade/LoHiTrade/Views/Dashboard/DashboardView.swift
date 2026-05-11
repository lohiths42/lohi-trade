import SwiftUI

/// Dashboard showing P&L summary, open positions, and recent signals (Req 13.1, 14.1, 14.2).
struct DashboardView: View {
    @StateObject private var tradingService = TradingService.shared
    @StateObject private var webSocketService = WebSocketService.shared
    @StateObject private var networkMonitor = NetworkMonitor.shared
    @StateObject private var offlineCache = OfflineCacheService.shared

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                OfflineBanner(
                    networkMonitor: networkMonitor,
                    lastUpdated: offlineCache.mostRecentUpdate
                )
                .animation(.easeInOut(duration: 0.3), value: networkMonitor.isConnected)

                ScrollView {
                    VStack(spacing: 16) {
                        pnlSummaryCard
                        openPositionsSection
                        recentSignalsSection
                    }
                    .padding()
                }
            }
            .navigationTitle("Dashboard")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink(destination: KillSwitchView()) {
                        Image(systemName: "power")
                            .foregroundColor(
                                tradingService.killSwitchStatus?.isActive == true ? .red : .primary
                            )
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink(destination: AnalyticsView()) {
                        Image(systemName: "chart.xyaxis.line")
                    }
                }
            }
            .refreshable {
                await tradingService.fetchDashboard()
                await tradingService.fetchKillSwitchStatus()
            }
            .task {
                // Load cached data first for instant display (Req 14.1, 14.4)
                loadCachedData()
                // Then fetch fresh data from server
                await tradingService.fetchDashboard()
                await tradingService.fetchKillSwitchStatus()
                // Cache the fresh data
                cacheCurrentData()
            }
            .onReceive(networkMonitor.connectivityRestored) {
                // Sync within 5 seconds on connectivity restore (Req 14.3)
                Task {
                    await tradingService.fetchDashboard()
                    await tradingService.fetchKillSwitchStatus()
                    cacheCurrentData()
                }
            }
        }
    }

    // MARK: - P&L Summary Card

    private var pnlSummaryCard: some View {
        VStack(spacing: 12) {
            if let summary = tradingService.dashboardSummary {
                Text("Total P&L")
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                Text(formatCurrency(summary.totalPnl))
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                    .foregroundColor(summary.totalPnl >= 0 ? .green : .red)

                Text("\(summary.totalPnlPercent >= 0 ? "+" : "")\(String(format: "%.2f", summary.totalPnlPercent))%")
                    .font(.headline)
                    .foregroundColor(summary.totalPnlPercent >= 0 ? .green : .red)

                HStack(spacing: 24) {
                    VStack {
                        Text("Realized")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text(formatCurrency(summary.realizedPnl))
                            .font(.subheadline.bold())
                    }
                    VStack {
                        Text("Unrealized")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text(formatCurrency(summary.unrealizedPnl))
                            .font(.subheadline.bold())
                    }
                    VStack {
                        Text("Positions")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("\(summary.openPositionCount)")
                            .font(.subheadline.bold())
                    }
                }
            } else if tradingService.isLoading {
                ProgressView()
            } else {
                Text("Unable to load dashboard")
                    .foregroundColor(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    // MARK: - Open Positions

    private var openPositionsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Open Positions")
                    .font(.headline)
                Spacer()
                NavigationLink("See All", destination: PositionsView())
                    .font(.subheadline)
            }

            if tradingService.positions.isEmpty {
                Text("No open positions")
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 8)
            } else {
                ForEach(tradingService.positions.prefix(5)) { position in
                    PositionRow(position: position, tick: webSocketService.priceTicks[position.symbol])
                }
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    // MARK: - Recent Signals

    private var recentSignalsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recent Signals")
                .font(.headline)

            if tradingService.signals.isEmpty {
                Text("No recent signals")
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 8)
            } else {
                ForEach(tradingService.signals.prefix(5)) { signal in
                    SignalRow(signal: signal)
                }
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    private func formatCurrency(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencySymbol = "₹"
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: value)) ?? "₹0.00"
    }

    // MARK: - Offline Cache Helpers

    private func loadCachedData() {
        if tradingService.dashboardSummary == nil,
           let cached = offlineCache.loadDashboardSummary() {
            tradingService.dashboardSummary = cached
        }
        if tradingService.positions.isEmpty,
           let cached = offlineCache.loadPositions() {
            tradingService.positions = cached
        }
        if tradingService.signals.isEmpty,
           let cached = offlineCache.loadSignals() {
            tradingService.signals = cached
        }
    }

    private func cacheCurrentData() {
        if let summary = tradingService.dashboardSummary {
            offlineCache.saveDashboardSummary(summary)
        }
        if !tradingService.positions.isEmpty {
            offlineCache.savePositions(tradingService.positions)
        }
        if !tradingService.signals.isEmpty {
            offlineCache.saveSignals(tradingService.signals)
        }
    }
}

// MARK: - Position Row

struct PositionRow: View {
    let position: Position
    let tick: PriceTick?

    private var currentLtp: Double { tick?.ltp ?? position.ltp }
    private var currentPnl: Double {
        if let tick {
            return Double(position.quantity) * (tick.ltp - position.avgPrice)
        }
        return position.pnl
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(position.symbol)
                    .font(.subheadline.bold())
                Text("\(position.quantity) @ \(String(format: "%.2f", position.avgPrice))")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(String(format: "₹%.2f", currentLtp))
                    .font(.subheadline)
                Text(String(format: "%@₹%.2f", currentPnl >= 0 ? "+" : "", currentPnl))
                    .font(.caption.bold())
                    .foregroundColor(currentPnl >= 0 ? .green : .red)
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Signal Row

struct SignalRow: View {
    let signal: Signal

    var body: some View {
        HStack {
            Image(systemName: signal.side == "BUY" ? "arrow.up.circle.fill" : "arrow.down.circle.fill")
                .foregroundColor(signal.side == "BUY" ? .green : .red)
            VStack(alignment: .leading, spacing: 2) {
                Text(signal.symbol)
                    .font(.subheadline.bold())
                Text(signal.strategy)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(String(format: "₹%.2f", signal.price))
                    .font(.subheadline)
                Text(signal.timestamp)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}
