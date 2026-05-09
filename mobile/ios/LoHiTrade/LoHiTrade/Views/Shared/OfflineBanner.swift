import SwiftUI

/// Offline indicator banner showing cached data status (Req 14.2).
///
/// Displays "Offline — showing cached data from [timestamp]" when
/// the device has no network connectivity.
struct OfflineBanner: View {
    @ObservedObject var networkMonitor: NetworkMonitor
    let lastUpdated: Date?

    var body: some View {
        if !networkMonitor.isConnected {
            HStack(spacing: 8) {
                Image(systemName: "wifi.slash")
                    .font(.caption)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Offline")
                        .font(.caption.bold())
                    if let lastUpdated {
                        Text("Showing cached data from \(formattedTimestamp(lastUpdated))")
                            .font(.caption2)
                    }
                }
                Spacer()
            }
            .foregroundColor(.white)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.orange)
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }

    private func formattedTimestamp(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
