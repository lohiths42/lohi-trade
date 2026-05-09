import Foundation
import SQLite3

/// SQLite-based local cache for offline portfolio viewing (Req 14.1).
///
/// Caches positions, orders, dashboard summary, and watchlists with
/// per-data-type timestamps. Auto-saves on every successful API response
/// and loads cached data on app launch for instant dashboard display.
@MainActor
final class OfflineCacheService: ObservableObject {
    static let shared = OfflineCacheService()

    @Published var lastUpdated: [String: Date] = [:]

    private var db: OpaquePointer?
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init() {
        openDatabase()
        createTables()
    }

    deinit {
        sqlite3_close(db)
    }

    // MARK: - Database Setup

    private func openDatabase() {
        let fileURL = Self.databaseURL
        if sqlite3_open(fileURL.path, &db) != SQLITE_OK {
            print("[OfflineCache] Failed to open database: \(String(cString: sqlite3_errmsg(db)))")
        }
        // Enable WAL mode for better concurrent read performance
        execute("PRAGMA journal_mode=WAL")
    }

    static var databaseURL: URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("offline_cache.sqlite3")
    }

    private func createTables() {
        execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                data BLOB NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
    }

    // MARK: - Save

    func savePositions(_ positions: [Position]) {
        save(positions, forKey: "positions")
    }

    func saveOrders(_ orders: [Order]) {
        save(orders, forKey: "orders")
    }

    func saveDashboardSummary(_ summary: DashboardSummary) {
        save(summary, forKey: "dashboard_summary")
    }

    func saveWatchlists(_ watchlists: [Watchlist]) {
        save(watchlists, forKey: "watchlists")
    }

    func saveSignals(_ signals: [Signal]) {
        save(signals, forKey: "signals")
    }

    // MARK: - Load

    func loadPositions() -> [Position]? {
        load(forKey: "positions")
    }

    func loadOrders() -> [Order]? {
        load(forKey: "orders")
    }

    func loadDashboardSummary() -> DashboardSummary? {
        load(forKey: "dashboard_summary")
    }

    func loadWatchlists() -> [Watchlist]? {
        load(forKey: "watchlists")
    }

    func loadSignals() -> [Signal]? {
        load(forKey: "signals")
    }

    // MARK: - Timestamp

    func lastUpdatedDate(forKey key: String) -> Date? {
        lastUpdated[key]
    }

    /// Returns the most recent update timestamp across all cached data types.
    var mostRecentUpdate: Date? {
        lastUpdated.values.max()
    }

    // MARK: - Clear

    func clearAll() {
        execute("DELETE FROM cache_entries")
        lastUpdated.removeAll()
    }

    // MARK: - Generic Save/Load

    private func save<T: Encodable>(_ value: T, forKey key: String) {
        guard let data = try? encoder.encode(value) else { return }
        let now = Date()

        var stmt: OpaquePointer?
        let sql = "INSERT OR REPLACE INTO cache_entries (key, data, updated_at) VALUES (?, ?, ?)"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (key as NSString).utf8String, -1, nil)
        data.withUnsafeBytes { ptr in
            sqlite3_bind_blob(stmt, 2, ptr.baseAddress, Int32(data.count), nil)
        }
        sqlite3_bind_double(stmt, 3, now.timeIntervalSince1970)

        if sqlite3_step(stmt) == SQLITE_DONE {
            lastUpdated[key] = now
        }
    }

    private func load<T: Decodable>(forKey key: String) -> T? {
        var stmt: OpaquePointer?
        let sql = "SELECT data, updated_at FROM cache_entries WHERE key = ?"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (key as NSString).utf8String, -1, nil)

        guard sqlite3_step(stmt) == SQLITE_ROW else { return nil }

        guard let blob = sqlite3_column_blob(stmt, 0) else { return nil }
        let blobSize = Int(sqlite3_column_bytes(stmt, 0))
        let data = Data(bytes: blob, count: blobSize)

        let timestamp = sqlite3_column_double(stmt, 1)
        lastUpdated[key] = Date(timeIntervalSince1970: timestamp)

        return try? decoder.decode(T.self, from: data)
    }

    // MARK: - Helpers

    @discardableResult
    private func execute(_ sql: String) -> Bool {
        var errMsg: UnsafeMutablePointer<CChar>?
        let result = sqlite3_exec(db, sql, nil, nil, &errMsg)
        if result != SQLITE_OK {
            if let errMsg {
                print("[OfflineCache] SQL error: \(String(cString: errMsg))")
                sqlite3_free(errMsg)
            }
            return false
        }
        return true
    }
}
