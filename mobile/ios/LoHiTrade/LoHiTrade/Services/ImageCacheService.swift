import Foundation
import UIKit

/// In-memory + disk image cache with LRU eviction (Req 34.8).
///
/// Caches chart images and avatars. Memory cache evicts at 50MB.
/// Disk cache entries expire after 7 days.
final class ImageCacheService {
    static let shared = ImageCacheService()

    private let memoryCache = NSCache<NSString, UIImage>()
    private let diskCacheURL: URL
    private let fileManager = FileManager.default
    private let diskExpiryInterval: TimeInterval = 7 * 24 * 60 * 60 // 7 days
    private let maxMemoryBytes = 50 * 1024 * 1024 // 50MB

    init() {
        let cacheDir = fileManager.urls(for: .cachesDirectory, in: .userDomainMask).first!
        diskCacheURL = cacheDir.appendingPathComponent("image_cache")
        try? fileManager.createDirectory(at: diskCacheURL, withIntermediateDirectories: true)

        memoryCache.totalCostLimit = maxMemoryBytes
        memoryCache.name = "com.lohitrade.imagecache"
    }

    // MARK: - Public API

    /// Returns cached image or downloads from URL.
    func image(for url: URL) async -> UIImage? {
        let key = cacheKey(for: url)

        // 1. Check memory cache
        if let cached = memoryCache.object(forKey: key as NSString) {
            return cached
        }

        // 2. Check disk cache
        if let diskImage = loadFromDisk(key: key) {
            let cost = diskImage.jpegData(compressionQuality: 1.0)?.count ?? 0
            memoryCache.setObject(diskImage, forKey: key as NSString, cost: cost)
            return diskImage
        }

        // 3. Download
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let image = UIImage(data: data) else {
            return nil
        }

        let cost = data.count
        memoryCache.setObject(image, forKey: key as NSString, cost: cost)
        saveToDisk(data: data, key: key)
        return image
    }

    /// Removes all cached images from memory and disk.
    func clearAll() {
        memoryCache.removeAllObjects()
        try? fileManager.removeItem(at: diskCacheURL)
        try? fileManager.createDirectory(at: diskCacheURL, withIntermediateDirectories: true)
    }

    /// Removes expired disk cache entries (older than 7 days).
    func pruneExpiredEntries() {
        guard let files = try? fileManager.contentsOfDirectory(
            at: diskCacheURL,
            includingPropertiesForKeys: [.contentModificationDateKey]
        ) else { return }

        let cutoff = Date().addingTimeInterval(-diskExpiryInterval)
        for fileURL in files {
            guard let attrs = try? fileURL.resourceValues(forKeys: [.contentModificationDateKey]),
                  let modified = attrs.contentModificationDate,
                  modified < cutoff else { continue }
            try? fileManager.removeItem(at: fileURL)
        }
    }

    // MARK: - Disk Operations

    private func saveToDisk(data: Data, key: String) {
        let fileURL = diskCacheURL.appendingPathComponent(key)
        try? data.write(to: fileURL)
    }

    private func loadFromDisk(key: String) -> UIImage? {
        let fileURL = diskCacheURL.appendingPathComponent(key)
        guard fileManager.fileExists(atPath: fileURL.path),
              let attrs = try? fileManager.attributesOfItem(atPath: fileURL.path),
              let modified = attrs[.modificationDate] as? Date,
              Date().timeIntervalSince(modified) < diskExpiryInterval,
              let data = try? Data(contentsOf: fileURL) else {
            return nil
        }
        return UIImage(data: data)
    }

    private func cacheKey(for url: URL) -> String {
        url.absoluteString
            .data(using: .utf8)
            .map { data in
                data.map { String(format: "%02x", $0) }.joined()
            } ?? url.lastPathComponent
    }
}
