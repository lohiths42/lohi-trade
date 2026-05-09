import Foundation
import SwiftUI

/// Model for each step in the onboarding walkthrough (Req 33.2, 33.3).
struct WalkthroughStep: Identifiable, Equatable {
    let id: Int
    let title: String
    let description: String
    let iconName: String
    let targetIdentifier: String
    let tooltipPosition: TooltipPosition

    enum TooltipPosition: String, Equatable {
        case top, bottom, leading, trailing
    }
}

/// All 7 walkthrough steps covering key platform features (Req 33.2).
enum WalkthroughSteps {
    static let all: [WalkthroughStep] = [
        WalkthroughStep(
            id: 0,
            title: "Dashboard Overview",
            description: "View your total P&L, realized and unrealized gains, and open position count at a glance.",
            iconName: "chart.bar.fill",
            targetIdentifier: "dashboard-pnl",
            tooltipPosition: .bottom
        ),
        WalkthroughStep(
            id: 1,
            title: "Manage Positions",
            description: "Track and manage your open positions. Close individual trades or view detailed performance.",
            iconName: "list.bullet.rectangle",
            targetIdentifier: "positions",
            tooltipPosition: .trailing
        ),
        WalkthroughStep(
            id: 2,
            title: "Stock Screener",
            description: "Filter stocks by fundamental and technical parameters to find your next trade opportunity.",
            iconName: "magnifyingglass",
            targetIdentifier: "screener",
            tooltipPosition: .bottom
        ),
        WalkthroughStep(
            id: 3,
            title: "Watchlists",
            description: "Create custom watchlists to track your favorite stocks with real-time prices.",
            iconName: "star.fill",
            targetIdentifier: "watchlist",
            tooltipPosition: .trailing
        ),
        WalkthroughStep(
            id: 4,
            title: "Connect Broker",
            description: "Link your broker account (Shoonya, Angel One, Kite, or Groww) to start trading.",
            iconName: "link.circle.fill",
            targetIdentifier: "broker",
            tooltipPosition: .bottom
        ),
        WalkthroughStep(
            id: 5,
            title: "AI Chatbot",
            description: "Ask questions about your trades and performance. Get insights with charts and analysis.",
            iconName: "bubble.left.and.bubble.right.fill",
            targetIdentifier: "chatbot",
            tooltipPosition: .leading
        ),
        WalkthroughStep(
            id: 6,
            title: "Kill Switch",
            description: "Instantly halt all trading activity in an emergency. One tap to protect your portfolio.",
            iconName: "power",
            targetIdentifier: "kill-switch",
            tooltipPosition: .bottom
        ),
    ]

    static var totalSteps: Int { all.count }
}
