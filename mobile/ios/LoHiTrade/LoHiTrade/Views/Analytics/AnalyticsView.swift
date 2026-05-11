import SwiftUI

/// Strategy performance analytics with equity curves and daily P&L charts (Req 13.6).
struct AnalyticsView: View {
    @StateObject private var tradingService = TradingService.shared
    @State private var selectedPeriod = "30d"

    private let periods = ["7d", "30d", "90d", "1y", "all"]

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                periodPicker
                equityCurveSection
                dailyPnlSection
                strategyPerformanceSection
            }
            .padding()
        }
        .navigationTitle("Analytics")
        .refreshable {
            await tradingService.fetchAnalytics(period: selectedPeriod)
        }
        .task {
            await tradingService.fetchAnalytics(period: selectedPeriod)
        }
    }

    // MARK: - Period Picker

    private var periodPicker: some View {
        Picker("Period", selection: $selectedPeriod) {
            ForEach(periods, id: \.self) { period in
                Text(period.uppercased()).tag(period)
            }
        }
        .pickerStyle(.segmented)
        .onChange(of: selectedPeriod) { _, newValue in
            Task { await tradingService.fetchAnalytics(period: newValue) }
        }
    }

    // MARK: - Equity Curve

    private var equityCurveSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Equity Curve")
                .font(.headline)

            if let data = tradingService.analyticsData?.equityCurve, !data.isEmpty {
                EquityCurveChart(data: data)
                    .frame(height: 200)
            } else {
                placeholder
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    // MARK: - Daily P&L

    private var dailyPnlSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Daily P&L")
                .font(.headline)

            if let data = tradingService.analyticsData?.dailyPnl, !data.isEmpty {
                DailyPnLChart(data: data)
                    .frame(height: 200)
            } else {
                placeholder
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    // MARK: - Strategy Performance

    private var strategyPerformanceSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Strategy Performance")
                .font(.headline)

            if let strategies = tradingService.analyticsData?.strategies, !strategies.isEmpty {
                ForEach(strategies) { strategy in
                    StrategyRow(strategy: strategy)
                }
            } else {
                placeholder
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    private var placeholder: some View {
        Text("No data available")
            .foregroundColor(.secondary)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.vertical, 8)
    }
}

// MARK: - Equity Curve Chart (Canvas-based)

struct EquityCurveChart: View {
    let data: [EquityCurvePoint]

    var body: some View {
        GeometryReader { geometry in
            let values = data.map(\.equity)
            let minVal = values.min() ?? 0
            let maxVal = values.max() ?? 1
            let range = max(maxVal - minVal, 1)

            Canvas { context, size in
                guard data.count > 1 else { return }
                var path = Path()
                for (index, point) in data.enumerated() {
                    let x = size.width * CGFloat(index) / CGFloat(data.count - 1)
                    let y = size.height * (1 - CGFloat(point.equity - minVal) / CGFloat(range))
                    if index == 0 {
                        path.move(to: CGPoint(x: x, y: y))
                    } else {
                        path.addLine(to: CGPoint(x: x, y: y))
                    }
                }
                context.stroke(path, with: .color(.blue), lineWidth: 2)
            }
        }
    }
}

// MARK: - Daily P&L Bar Chart

struct DailyPnLChart: View {
    let data: [DailyPnL]

    var body: some View {
        GeometryReader { geometry in
            let maxAbs = data.map { abs($0.pnl) }.max() ?? 1
            let barWidth = max(geometry.size.width / CGFloat(data.count) - 2, 2)
            let midY = geometry.size.height / 2

            Canvas { context, size in
                for (index, point) in data.enumerated() {
                    let x = size.width * CGFloat(index) / CGFloat(max(data.count, 1))
                    let barHeight = CGFloat(abs(point.pnl) / maxAbs) * midY
                    let rect: CGRect
                    if point.pnl >= 0 {
                        rect = CGRect(x: x, y: midY - barHeight, width: barWidth, height: barHeight)
                    } else {
                        rect = CGRect(x: x, y: midY, width: barWidth, height: barHeight)
                    }
                    let color: Color = point.pnl >= 0 ? .green : .red
                    context.fill(Path(rect), with: .color(color.opacity(0.7)))
                }
                // Zero line
                var zeroLine = Path()
                zeroLine.move(to: CGPoint(x: 0, y: midY))
                zeroLine.addLine(to: CGPoint(x: size.width, y: midY))
                context.stroke(zeroLine, with: .color(.secondary.opacity(0.3)), lineWidth: 1)
            }
        }
    }
}

// MARK: - Strategy Row

struct StrategyRow: View {
    let strategy: StrategyPerformance

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(strategy.name)
                    .font(.subheadline.bold())
                Text("\(strategy.tradeCount) trades")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(String(format: "₹%.2f", strategy.totalPnl))
                    .font(.subheadline.bold())
                    .foregroundColor(strategy.totalPnl >= 0 ? .green : .red)
                Text(String(format: "Win: %.1f%%", strategy.winRate * 100))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}
