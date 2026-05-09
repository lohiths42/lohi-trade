import SwiftUI

/// Watchlist CRUD and security management (Req 13.7).
struct WatchlistView: View {
    @StateObject private var watchlistService = WatchlistService.shared
    @StateObject private var webSocketService = WebSocketService.shared
    @State private var showCreateSheet = false
    @State private var newWatchlistName = ""
    @State private var selectedWatchlist: Watchlist?
    @State private var showRenameAlert = false
    @State private var renameText = ""
    @State private var watchlistToRename: Watchlist?

    var body: some View {
        NavigationStack {
            List {
                if watchlistService.watchlists.isEmpty && !watchlistService.isLoading {
                    ContentUnavailableView(
                        "No Watchlists",
                        systemImage: "star",
                        description: Text("Create a watchlist to track your favorite stocks.")
                    )
                } else {
                    ForEach(watchlistService.watchlists) { watchlist in
                        NavigationLink(destination: WatchlistDetailView(watchlistId: watchlist.id)) {
                            WatchlistRow(watchlist: watchlist)
                        }
                        .swipeActions(edge: .trailing) {
                            if !watchlist.isPrebuilt {
                                Button(role: .destructive) {
                                    Task { _ = await watchlistService.deleteWatchlist(id: watchlist.id) }
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                                Button {
                                    watchlistToRename = watchlist
                                    renameText = watchlist.name
                                    showRenameAlert = true
                                } label: {
                                    Label("Rename", systemImage: "pencil")
                                }
                                .tint(.blue)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Watchlists")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        newWatchlistName = ""
                        showCreateSheet = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .refreshable {
                await watchlistService.fetchWatchlists()
            }
            .task {
                await watchlistService.fetchWatchlists()
            }
            .alert("New Watchlist", isPresented: $showCreateSheet) {
                TextField("Name", text: $newWatchlistName)
                Button("Cancel", role: .cancel) {}
                Button("Create") {
                    guard !newWatchlistName.isEmpty else { return }
                    Task { _ = await watchlistService.createWatchlist(name: newWatchlistName) }
                }
            }
            .alert("Rename Watchlist", isPresented: $showRenameAlert) {
                TextField("Name", text: $renameText)
                Button("Cancel", role: .cancel) {}
                Button("Rename") {
                    guard let wl = watchlistToRename, !renameText.isEmpty else { return }
                    Task { _ = await watchlistService.renameWatchlist(id: wl.id, name: renameText) }
                }
            }
        }
    }
}

// MARK: - Watchlist Row

struct WatchlistRow: View {
    let watchlist: Watchlist

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(watchlist.name)
                        .font(.subheadline.bold())
                    if watchlist.isPrebuilt {
                        Text("Pre-built")
                            .font(.caption2)
                            .padding(.horizontal, 4)
                            .padding(.vertical, 1)
                            .background(Color.blue.opacity(0.1))
                            .foregroundColor(.blue)
                            .cornerRadius(3)
                    }
                }
                Text("\(watchlist.itemCount) securities")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }
}

// MARK: - Watchlist Detail View

struct WatchlistDetailView: View {
    let watchlistId: String
    @StateObject private var watchlistService = WatchlistService.shared
    @StateObject private var webSocketService = WebSocketService.shared
    @State private var showAddSecurityAlert = false
    @State private var symbolToAdd = ""

    var body: some View {
        List {
            if let detail = watchlistService.currentWatchlist {
                ForEach(detail.items) { item in
                    WatchlistItemRow(item: item, tick: webSocketService.priceTicks[item.symbol])
                        .swipeActions(edge: .trailing) {
                            if !detail.isPrebuilt {
                                Button(role: .destructive) {
                                    Task {
                                        _ = await watchlistService.removeSecurity(
                                            watchlistId: watchlistId, symbol: item.symbol
                                        )
                                    }
                                } label: {
                                    Label("Remove", systemImage: "minus.circle")
                                }
                            }
                        }
                }
            }
        }
        .navigationTitle(watchlistService.currentWatchlist?.name ?? "Watchlist")
        .toolbar {
            if watchlistService.currentWatchlist?.isPrebuilt != true {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        symbolToAdd = ""
                        showAddSecurityAlert = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
        }
        .task {
            await watchlistService.fetchWatchlistDetail(id: watchlistId)
            if let items = watchlistService.currentWatchlist?.items {
                webSocketService.subscribe(to: items.map(\.symbol))
            }
        }
        .alert("Add Security", isPresented: $showAddSecurityAlert) {
            TextField("Symbol (e.g. RELIANCE)", text: $symbolToAdd)
                .textInputAutocapitalization(.characters)
            Button("Cancel", role: .cancel) {}
            Button("Add") {
                guard !symbolToAdd.isEmpty else { return }
                Task {
                    _ = await watchlistService.addSecurity(
                        watchlistId: watchlistId, symbol: symbolToAdd.uppercased()
                    )
                }
            }
        }
    }
}

// MARK: - Watchlist Item Row

struct WatchlistItemRow: View {
    let item: WatchlistItem
    let tick: PriceTick?

    private var ltp: Double { tick?.ltp ?? item.ltp ?? 0 }
    private var change: Double { tick?.change ?? item.change ?? 0 }
    private var changePercent: Double { tick?.changePercent ?? item.changePercent ?? 0 }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.symbol)
                    .font(.subheadline.bold())
                Text(item.companyName)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(String(format: "₹%.2f", ltp))
                    .font(.subheadline)
                HStack(spacing: 4) {
                    Text(String(format: "%@%.2f", change >= 0 ? "+" : "", change))
                    Text(String(format: "(%@%.2f%%)", changePercent >= 0 ? "+" : "", changePercent))
                }
                .font(.caption)
                .foregroundColor(change >= 0 ? .green : .red)
            }
        }
        .padding(.vertical, 2)
    }
}
