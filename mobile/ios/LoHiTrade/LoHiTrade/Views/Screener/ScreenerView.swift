import SwiftUI

/// Stock screener with filter params and sortable results (Req 13.8).
struct ScreenerView: View {
    @StateObject private var screenerService = ScreenerService.shared
    @State private var filter = ScreenerFilter()
    @State private var showFilterSheet = false
    @State private var currentPage = 1

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Results summary
                if let response = screenerService.results {
                    HStack {
                        Text("\(response.totalCount) results")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Spacer()
                        if response.totalCount > response.pageSize {
                            Text("Page \(response.page)")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                    .padding(.horizontal)
                    .padding(.vertical, 8)
                }

                // Results list
                List {
                    if let results = screenerService.results?.results {
                        ForEach(results) { result in
                            ScreenerResultRow(result: result)
                        }

                        // Pagination
                        if let response = screenerService.results,
                           response.totalCount > response.page * response.pageSize {
                            Button("Load More") {
                                currentPage += 1
                                Task { await screenerService.search(filter: filter, page: currentPage) }
                            }
                            .frame(maxWidth: .infinity, alignment: .center)
                        }
                    } else if !screenerService.isLoading {
                        ContentUnavailableView(
                            "Stock Screener",
                            systemImage: "magnifyingglass",
                            description: Text("Set filters to find stocks matching your criteria.")
                        )
                    }
                }
                .listStyle(.plain)
            }
            .navigationTitle("Screener")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        showFilterSheet = true
                    } label: {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                    }
                }
                ToolbarItem(placement: .navigationBarLeading) {
                    Menu {
                        ForEach(screenerService.presets) { preset in
                            Button(preset.name) {
                                filter = preset.filters
                                currentPage = 1
                                Task { await screenerService.applyPreset(preset) }
                            }
                        }
                    } label: {
                        Image(systemName: "bookmark")
                    }
                }
            }
            .task {
                await screenerService.fetchPresets()
                await screenerService.fetchTemplates()
            }
            .sheet(isPresented: $showFilterSheet) {
                ScreenerFilterSheet(filter: $filter) {
                    currentPage = 1
                    Task { await screenerService.search(filter: filter, page: 1) }
                }
            }
            .overlay {
                if screenerService.isLoading {
                    ProgressView()
                }
            }
        }
    }
}

// MARK: - Screener Result Row

struct ScreenerResultRow: View {
    let result: ScreenerResult

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(result.symbol)
                        .font(.subheadline.bold())
                    Text(result.companyName)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text(String(format: "₹%.2f", result.ltp))
                        .font(.subheadline)
                    Text(String(format: "%@%.2f%%", result.changePercent >= 0 ? "+" : "", result.changePercent))
                        .font(.caption.bold())
                        .foregroundColor(result.changePercent >= 0 ? .green : .red)
                }
            }

            HStack(spacing: 12) {
                if let sector = result.sector {
                    Label(sector, systemImage: "building.2")
                        .font(.caption2)
                }
                if let pe = result.peRatio {
                    Text("PE: \(String(format: "%.1f", pe))")
                        .font(.caption2)
                }
                if let mc = result.marketCap {
                    Text("MCap: \(formatMarketCap(mc))")
                        .font(.caption2)
                }
            }
            .foregroundColor(.secondary)
        }
        .padding(.vertical, 2)
    }

    private func formatMarketCap(_ value: Double) -> String {
        if value >= 1_00_000 {
            return String(format: "₹%.1fL Cr", value / 1_00_000)
        } else if value >= 100 {
            return String(format: "₹%.0f Cr", value)
        }
        return String(format: "₹%.2f", value)
    }
}

// MARK: - Filter Sheet

struct ScreenerFilterSheet: View {
    @Binding var filter: ScreenerFilter
    let onApply: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Fundamental") {
                    RangeField(label: "PE Ratio", range: binding(for: \.peRatio))
                    RangeField(label: "PB Ratio", range: binding(for: \.pbRatio))
                    RangeField(label: "Dividend Yield %", range: binding(for: \.dividendYield))
                    RangeField(label: "ROE %", range: binding(for: \.roe))
                    RangeField(label: "Debt/Equity", range: binding(for: \.debtToEquity))
                }

                Section("Technical") {
                    RangeField(label: "RSI (14)", range: binding(for: \.rsi14))
                    RangeField(label: "Price Change 1D %", range: binding(for: \.priceChange1d))
                    RangeField(label: "Price Change 1W %", range: binding(for: \.priceChange1w))
                    RangeField(label: "Price Change 1M %", range: binding(for: \.priceChange1m))
                }

                Section("Meta") {
                    Picker("Exchange", selection: Binding(
                        get: { filter.exchange ?? "" },
                        set: { filter.exchange = $0.isEmpty ? nil : $0 }
                    )) {
                        Text("All").tag("")
                        Text("NSE").tag("NSE")
                        Text("BSE").tag("BSE")
                    }

                    Picker("Market Cap", selection: Binding(
                        get: { filter.marketCapCategory ?? "" },
                        set: { filter.marketCapCategory = $0.isEmpty ? nil : $0 }
                    )) {
                        Text("All").tag("")
                        Text("Large Cap").tag("large-cap")
                        Text("Mid Cap").tag("mid-cap")
                        Text("Small Cap").tag("small-cap")
                    }
                }

                Section("Sort") {
                    Picker("Sort By", selection: Binding(
                        get: { filter.sortBy ?? "market_cap" },
                        set: { filter.sortBy = $0 }
                    )) {
                        Text("Market Cap").tag("market_cap")
                        Text("PE Ratio").tag("pe_ratio")
                        Text("Change %").tag("change_percent")
                        Text("Volume").tag("avg_volume")
                    }

                    Picker("Order", selection: Binding(
                        get: { filter.sortOrder ?? "desc" },
                        set: { filter.sortOrder = $0 }
                    )) {
                        Text("Descending").tag("desc")
                        Text("Ascending").tag("asc")
                    }
                }
            }
            .navigationTitle("Filters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Reset") {
                        filter = ScreenerFilter()
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Apply") {
                        dismiss()
                        onApply()
                    }
                    .bold()
                }
            }
        }
    }

    private func binding(for keyPath: WritableKeyPath<ScreenerFilter, ScreenerRange?>) -> Binding<ScreenerRange> {
        Binding(
            get: { filter[keyPath: keyPath] ?? ScreenerRange() },
            set: {
                let range = ($0.min == nil && $0.max == nil) ? nil : $0
                filter[keyPath: keyPath] = range
            }
        )
    }
}

// MARK: - Range Field

struct RangeField: View {
    let label: String
    @Binding var range: ScreenerRange

    var body: some View {
        HStack {
            Text(label)
                .font(.subheadline)
            Spacer()
            TextField("Min", value: $range.min, format: .number)
                .keyboardType(.decimalPad)
                .frame(width: 60)
                .textFieldStyle(.roundedBorder)
                .font(.caption)
            Text("–")
            TextField("Max", value: $range.max, format: .number)
                .keyboardType(.decimalPad)
                .frame(width: 60)
                .textFieldStyle(.roundedBorder)
                .font(.caption)
        }
    }
}
