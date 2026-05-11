import SwiftUI

/// Open positions with close action (Req 13.3).
struct PositionsView: View {
    @StateObject private var tradingService = TradingService.shared
    @StateObject private var webSocketService = WebSocketService.shared
    @State private var positionToClose: Position?
    @State private var showCloseConfirmation = false

    var body: some View {
        NavigationStack {
            List {
                if tradingService.positions.isEmpty && !tradingService.isLoading {
                    ContentUnavailableView(
                        "No Open Positions",
                        systemImage: "tray",
                        description: Text("Your open positions will appear here.")
                    )
                } else {
                    ForEach(tradingService.positions) { position in
                        PositionDetailRow(
                            position: position,
                            tick: webSocketService.priceTicks[position.symbol],
                            onClose: {
                                positionToClose = position
                                showCloseConfirmation = true
                            }
                        )
                    }
                }
            }
            .navigationTitle("Positions")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink(destination: OrderHistoryView()) {
                        Image(systemName: "clock.arrow.circlepath")
                    }
                }
            }
            .refreshable {
                await tradingService.fetchPositions()
            }
            .task {
                await tradingService.fetchPositions()
                let symbols = tradingService.positions.map(\.symbol)
                webSocketService.subscribe(to: symbols)
            }
            .alert("Close Position", isPresented: $showCloseConfirmation) {
                Button("Cancel", role: .cancel) {}
                Button("Close", role: .destructive) {
                    guard let position = positionToClose else { return }
                    Task {
                        _ = await tradingService.closePosition(positionId: position.id)
                    }
                }
            } message: {
                if let position = positionToClose {
                    Text("Close \(position.quantity) shares of \(position.symbol)?")
                }
            }
        }
    }
}

// MARK: - Position Detail Row

struct PositionDetailRow: View {
    let position: Position
    let tick: PriceTick?
    let onClose: () -> Void

    private var currentLtp: Double { tick?.ltp ?? position.ltp }
    private var currentPnl: Double {
        if let tick {
            return Double(position.quantity) * (tick.ltp - position.avgPrice)
        }
        return position.pnl
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(position.symbol)
                            .font(.headline)
                        Text(position.side)
                            .font(.caption.bold())
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(position.side == "BUY" ? Color.green.opacity(0.2) : Color.red.opacity(0.2))
                            .cornerRadius(4)
                    }
                    Text(position.exchange)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                Button(action: onClose) {
                    Text("Close")
                        .font(.caption.bold())
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color.red.opacity(0.1))
                        .foregroundColor(.red)
                        .cornerRadius(6)
                }
                .buttonStyle(.plain)
            }

            HStack {
                VStack(alignment: .leading) {
                    Text("Qty: \(position.quantity)")
                        .font(.caption)
                    Text("Avg: ₹\(String(format: "%.2f", position.avgPrice))")
                        .font(.caption)
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Text("LTP: ₹\(String(format: "%.2f", currentLtp))")
                        .font(.caption)
                    Text(String(format: "%@₹%.2f", currentPnl >= 0 ? "+" : "", currentPnl))
                        .font(.caption.bold())
                        .foregroundColor(currentPnl >= 0 ? .green : .red)
                }
            }
            .foregroundColor(.secondary)

            if let strategy = position.strategy {
                Text("Strategy: \(strategy)")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}
