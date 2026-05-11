import SwiftUI

/// Order history with status, fill details, and rejection reasons (Req 13.4).
struct OrderHistoryView: View {
    @StateObject private var tradingService = TradingService.shared

    var body: some View {
        List {
            if tradingService.orders.isEmpty && !tradingService.isLoading {
                ContentUnavailableView(
                    "No Orders",
                    systemImage: "doc.text",
                    description: Text("Your order history will appear here.")
                )
            } else {
                ForEach(tradingService.orders) { order in
                    OrderRow(order: order)
                }
            }
        }
        .navigationTitle("Order History")
        .refreshable {
            await tradingService.fetchOrders()
        }
        .task {
            await tradingService.fetchOrders()
        }
    }
}

// MARK: - Order Row

struct OrderRow: View {
    let order: Order

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(order.symbol)
                    .font(.headline)
                Text(order.side)
                    .font(.caption.bold())
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(order.side == "BUY" ? Color.green.opacity(0.2) : Color.red.opacity(0.2))
                    .cornerRadius(4)
                Spacer()
                statusBadge
            }

            HStack {
                Text("\(order.orderType) · \(order.quantity) qty")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                if let price = order.price, price > 0 {
                    Text("₹\(String(format: "%.2f", price))")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

            // Fill details
            if order.filledQuantity > 0 {
                HStack {
                    Text("Filled: \(order.filledQuantity)/\(order.quantity)")
                        .font(.caption)
                    if let avgFill = order.avgFillPrice {
                        Text("@ ₹\(String(format: "%.2f", avgFill))")
                            .font(.caption)
                    }
                }
                .foregroundColor(.secondary)
            }

            // Rejection reason
            if let reason = order.rejectionReason, !reason.isEmpty {
                Text("Reason: \(reason)")
                    .font(.caption)
                    .foregroundColor(.red)
            }

            Text(order.placedAt)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .padding(.vertical, 4)
    }

    private var statusBadge: some View {
        Text(order.status.rawValue)
            .font(.caption2.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(statusColor.opacity(0.15))
            .foregroundColor(statusColor)
            .cornerRadius(4)
    }

    private var statusColor: Color {
        switch order.status {
        case .complete: return .green
        case .rejected: return .red
        case .cancelled: return .orange
        case .pending, .open: return .blue
        }
    }
}
