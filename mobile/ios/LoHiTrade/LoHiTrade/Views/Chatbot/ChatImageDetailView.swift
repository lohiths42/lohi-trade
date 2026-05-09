import SwiftUI

/// Full-screen chart image view with pinch-to-zoom and data values (Req 20.7).
///
/// Displayed when a user taps an inline chart image in the chat.
/// Supports pinch-to-zoom and double-tap to reset zoom.
struct ChatImageDetailView: View {
    let imageURL: URL
    let messageContent: String

    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 0) {
                    chartImage
                    dataValuesPanel
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Close") { dismiss() }
                        .foregroundColor(.white)
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        resetZoom()
                    } label: {
                        Image(systemName: "arrow.counterclockwise")
                            .foregroundColor(.white)
                    }
                }
            }
            .toolbarBackground(.black, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
        }
    }

    // MARK: - Chart Image with Zoom

    private var chartImage: some View {
        GeometryReader { geometry in
            LazyImage(
                url: imageURL,
                placeholder: Image(systemName: "chart.bar"),
                contentMode: .fit
            )
            .frame(width: geometry.size.width, height: geometry.size.height)
            .scaleEffect(scale)
            .offset(offset)
            .gesture(pinchGesture)
            .gesture(doubleTapGesture)
            .gesture(dragGesture)
            .accessibilityLabel("Chart image. Pinch to zoom, double tap to reset.")
        }
        .frame(maxHeight: .infinity)
    }

    // MARK: - Data Values Panel

    private var dataValuesPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Chart Details")
                .font(.headline)
                .foregroundColor(.white)

            Text(messageContent)
                .font(.subheadline)
                .foregroundColor(.white.opacity(0.8))
                .lineLimit(6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color(.systemGray6).opacity(0.2))
    }

    // MARK: - Gestures

    private var pinchGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                let newScale = lastScale * value.magnification
                scale = min(max(newScale, 1.0), 5.0)
            }
            .onEnded { _ in
                lastScale = scale
                if scale <= 1.0 {
                    resetZoom()
                }
            }
    }

    private var doubleTapGesture: some Gesture {
        TapGesture(count: 2)
            .onEnded {
                if scale > 1.0 {
                    resetZoom()
                } else {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        scale = 2.5
                        lastScale = 2.5
                    }
                }
            }
    }

    private var dragGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                guard scale > 1.0 else { return }
                offset = CGSize(
                    width: lastOffset.width + value.translation.width,
                    height: lastOffset.height + value.translation.height
                )
            }
            .onEnded { _ in
                lastOffset = offset
            }
    }

    private func resetZoom() {
        withAnimation(.easeInOut(duration: 0.3)) {
            scale = 1.0
            lastScale = 1.0
            offset = .zero
            lastOffset = .zero
        }
    }
}
