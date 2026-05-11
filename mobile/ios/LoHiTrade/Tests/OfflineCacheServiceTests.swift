import XCTest
@testable import LoHiTrade

@MainActor
final class OfflineCacheServiceTests: XCTestCase {

    private var sut: OfflineCacheService!

    override func setUp() async throws {
        // Use a fresh database for each test
        let dbURL = OfflineCacheService.databaseURL
        try? FileManager.default.removeItem(at: dbURL)
        sut = OfflineCacheService()
    }

    override func tearDown() async throws {
        sut.clearAll()
        sut = nil
    }

    // MARK: - Dashboard Summary

    func testSaveAndLoadDashboardSummary() {
        let summary = DashboardSummary(
            totalPnl: 1500.50,
            totalPnlPercent: 3.25,
            realizedPnl: 800.0,
            unrealizedPnl: 700.50,
            openPositionCount: 3,
            todayTradeCount: 7
        )

        sut.saveDashboardSummary(summary)
        let loaded = sut.loadDashboardSummary()

        XCTAssertEqual(loaded, summary)
        XCTAssertNotNil(sut.lastUpdatedDate(forKey: "dashboard_summary"))
    }

    // MARK: - Positions

    func testSaveAndLoadPositions() {
        let positions = [
            Position(
                id: "p1", symbol: "RELIANCE", exchange: "NSE",
                quantity: 10, avgPrice: 2500.0, ltp: 2550.0,
                pnl: 500.0, pnlPercent: 2.0, side: "BUY",
                product: "CNC", strategy: "MeanReversion"
            )
        ]

        sut.savePositions(positions)
        let loaded = sut.loadPositions()

        XCTAssertEqual(loaded, positions)
    }

    // MARK: - Orders

    func testSaveAndLoadOrders() {
        let orders = [
            Order(
                id: "o1", symbol: "TCS", exchange: "NSE",
                side: "BUY", orderType: "LIMIT", quantity: 5,
                price: 3400.0, triggerPrice: nil, filledQuantity: 5,
                avgFillPrice: 3400.0, status: .complete,
                rejectionReason: nil, placedAt: "2024-01-15T10:30:00Z",
                updatedAt: "2024-01-15T10:30:05Z"
            )
        ]

        sut.saveOrders(orders)
        let loaded = sut.loadOrders()

        XCTAssertEqual(loaded, orders)
    }

    // MARK: - Watchlists

    func testSaveAndLoadWatchlists() {
        let watchlists = [
            Watchlist(id: "w1", name: "Nifty 50", isPrebuilt: true, itemCount: 50),
            Watchlist(id: "w2", name: "My Picks", isPrebuilt: false, itemCount: 12)
        ]

        sut.saveWatchlists(watchlists)
        let loaded = sut.loadWatchlists()

        XCTAssertEqual(loaded, watchlists)
    }

    // MARK: - Signals

    func testSaveAndLoadSignals() {
        let signals = [
            Signal(
                id: "s1", symbol: "INFY", strategy: "TrendFollowing",
                side: "BUY", price: 1450.0,
                timestamp: "2024-01-15T11:00:00Z", status: "ACTIVE"
            )
        ]

        sut.saveSignals(signals)
        let loaded = sut.loadSignals()

        XCTAssertEqual(loaded, signals)
    }

    // MARK: - Timestamps

    func testLastUpdatedTracksPerDataType() {
        let summary = DashboardSummary(
            totalPnl: 0, totalPnlPercent: 0, realizedPnl: 0,
            unrealizedPnl: 0, openPositionCount: 0, todayTradeCount: 0
        )
        sut.saveDashboardSummary(summary)
        sut.savePositions([])

        XCTAssertNotNil(sut.lastUpdatedDate(forKey: "dashboard_summary"))
        XCTAssertNotNil(sut.lastUpdatedDate(forKey: "positions"))
        XCTAssertNotNil(sut.mostRecentUpdate)
    }

    // MARK: - Clear

    func testClearAllRemovesData() {
        let summary = DashboardSummary(
            totalPnl: 100, totalPnlPercent: 1, realizedPnl: 50,
            unrealizedPnl: 50, openPositionCount: 1, todayTradeCount: 2
        )
        sut.saveDashboardSummary(summary)
        XCTAssertNotNil(sut.loadDashboardSummary())

        sut.clearAll()

        XCTAssertNil(sut.loadDashboardSummary())
        XCTAssertTrue(sut.lastUpdated.isEmpty)
    }

    // MARK: - Overwrite

    func testSaveOverwritesPreviousData() {
        let summary1 = DashboardSummary(
            totalPnl: 100, totalPnlPercent: 1, realizedPnl: 50,
            unrealizedPnl: 50, openPositionCount: 1, todayTradeCount: 2
        )
        let summary2 = DashboardSummary(
            totalPnl: 200, totalPnlPercent: 2, realizedPnl: 100,
            unrealizedPnl: 100, openPositionCount: 3, todayTradeCount: 5
        )

        sut.saveDashboardSummary(summary1)
        sut.saveDashboardSummary(summary2)

        let loaded = sut.loadDashboardSummary()
        XCTAssertEqual(loaded, summary2)
    }

    // MARK: - Load Missing Key

    func testLoadNonExistentKeyReturnsNil() {
        let loaded: DashboardSummary? = sut.loadDashboardSummary()
        XCTAssertNil(loaded)
    }
}
