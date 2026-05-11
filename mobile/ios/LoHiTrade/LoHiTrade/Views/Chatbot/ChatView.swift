import SwiftUI

/// Conversational chat interface for the AI chatbot (Req 18.1, 20.7).
///
/// - User messages: right-aligned, blue bubble
/// - Assistant messages: left-aligned, gray bubble
/// - Inline chart images via LazyImage, tap for full-screen detail
/// - Loading indicator while waiting for response
/// - Auto-scroll to latest message
struct ChatView: View {
    @StateObject private var chatbotService = ChatbotService.shared
    @State private var inputText = ""
    @State private var selectedChartURL: URL?
    @State private var selectedChartContent: String?
    @FocusState private var isInputFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                messageList
                Divider()
                inputBar
            }
            .navigationTitle("AI Chatbot")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(role: .destructive) {
                            Task { await chatbotService.clearSession() }
                        } label: {
                            Label("Clear Chat", systemImage: "trash")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .task {
                await chatbotService.fetchHistory()
            }
            .fullScreenCover(item: $selectedChartBinding) { detail in
                ChatImageDetailView(
                    imageURL: detail.url,
                    messageContent: detail.content
                )
            }
        }
    }

    // MARK: - Message List

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if chatbotService.messages.isEmpty && !chatbotService.isLoading {
                        emptyState
                    }

                    ForEach(chatbotService.messages) { message in
                        ChatBubble(
                            message: message,
                            onChartTap: { url in
                                selectedChartURL = url
                                selectedChartContent = message.content
                            }
                        )
                        .id(message.id)
                    }

                    if chatbotService.isLoading {
                        HStack {
                            TypingIndicator()
                            Spacer()
                        }
                        .padding(.horizontal)
                        .id("loading")
                    }
                }
                .padding(.vertical, 12)
            }
            .onChange(of: chatbotService.messages.count) { _ in
                scrollToBottom(proxy: proxy)
            }
            .onChange(of: chatbotService.isLoading) { _ in
                scrollToBottom(proxy: proxy)
            }
        }
    }

    private func scrollToBottom(proxy: ScrollViewProxy) {
        withAnimation(.easeOut(duration: 0.2)) {
            if chatbotService.isLoading {
                proxy.scrollTo("loading", anchor: .bottom)
            } else if let lastId = chatbotService.messages.last?.id {
                proxy.scrollTo(lastId, anchor: .bottom)
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 48))
                .foregroundColor(.secondary.opacity(0.5))
            Text("Ask me about your trades")
                .font(.headline)
                .foregroundColor(.secondary)
            Text("I can explain trades, show performance charts, and answer questions about your portfolio.")
                .font(.caption)
                .foregroundColor(.secondary.opacity(0.7))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .padding(.top, 60)
    }

    // MARK: - Input Bar

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField("Ask about your trades...", text: $inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .focused($isInputFocused)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color(.systemGray6))
                .cornerRadius(20)
                .onSubmit { sendMessage() }

            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 32))
                    .foregroundColor(canSend ? .blue : .gray.opacity(0.4))
            }
            .disabled(!canSend)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(.systemBackground))
    }

    private var canSend: Bool {
        !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !chatbotService.isLoading
    }

    private func sendMessage() {
        guard canSend else { return }
        let text = inputText
        inputText = ""
        Task { await chatbotService.sendMessage(text) }
    }

    // MARK: - Full-screen chart binding

    private var selectedChartBinding: Binding<ChartDetail?> {
        Binding(
            get: {
                guard let url = selectedChartURL else { return nil }
                return ChartDetail(url: url, content: selectedChartContent ?? "")
            },
            set: { newValue in
                if newValue == nil {
                    selectedChartURL = nil
                    selectedChartContent = nil
                }
            }
        )
    }
}

// MARK: - Chart Detail (for full-screen cover)

struct ChartDetail: Identifiable, Equatable {
    let id = UUID()
    let url: URL
    let content: String

    static func == (lhs: ChartDetail, rhs: ChartDetail) -> Bool {
        lhs.url == rhs.url && lhs.content == rhs.content
    }
}

// MARK: - Chat Bubble

struct ChatBubble: View {
    let message: ChatMessage
    var onChartTap: ((URL) -> Void)?

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 60) }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 6) {
                Text(message.content)
                    .font(.subheadline)
                    .foregroundColor(message.role == .user ? .white : .primary)

                if let chartURL = message.chartURL {
                    LazyImage(
                        url: chartURL,
                        placeholder: Image(systemName: "chart.bar"),
                        contentMode: .fit
                    )
                    .frame(maxWidth: 260, maxHeight: 180)
                    .cornerRadius(8)
                    .onTapGesture {
                        onChartTap?(chartURL)
                    }
                    .accessibilityLabel("Chart image. Tap to view full screen with data values.")
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(bubbleBackground)
            .cornerRadius(16)

            if message.role == .assistant { Spacer(minLength: 60) }
        }
        .padding(.horizontal, 12)
    }

    private var bubbleBackground: Color {
        message.role == .user ? .blue : Color(.systemGray5)
    }
}

// MARK: - Typing Indicator

struct TypingIndicator: View {
    @State private var dotCount = 0
    private let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(Color.secondary)
                    .frame(width: 8, height: 8)
                    .opacity(dotCount % 3 == index ? 1.0 : 0.3)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color(.systemGray5))
        .cornerRadius(16)
        .onReceive(timer) { _ in
            dotCount += 1
        }
        .accessibilityLabel("Assistant is typing")
    }
}
