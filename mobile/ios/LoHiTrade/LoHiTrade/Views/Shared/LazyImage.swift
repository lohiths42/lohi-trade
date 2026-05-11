import SwiftUI

/// Lazy-loading image view with placeholder and cache (Req 34.8).
///
/// Uses ImageCacheService for in-memory + disk caching.
/// Shows a placeholder while loading and a fallback on failure.
struct LazyImage: View {
    let url: URL?
    var placeholder: Image = Image(systemName: "photo")
    var contentMode: ContentMode = .fit

    @State private var loadedImage: UIImage?
    @State private var isLoading = false

    var body: some View {
        Group {
            if let loadedImage {
                Image(uiImage: loadedImage)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else if isLoading {
                ProgressView()
            } else {
                placeholder
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
                    .foregroundColor(.secondary.opacity(0.5))
            }
        }
        .task(id: url) {
            await loadImage()
        }
    }

    private func loadImage() async {
        guard let url else { return }
        isLoading = true
        defer { isLoading = false }
        loadedImage = await ImageCacheService.shared.image(for: url)
    }
}
