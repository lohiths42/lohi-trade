package com.lohitrade.data.onboarding

/**
 * Model for each step in the onboarding walkthrough (Req 33.2, 33.3).
 */
data class WalkthroughStep(
    val id: Int,
    val title: String,
    val description: String,
    val iconName: String,
    val targetIdentifier: String,
    val tooltipPosition: TooltipPosition
)

enum class TooltipPosition {
    TOP, BOTTOM, START, END
}

/**
 * All 7 walkthrough steps covering key platform features (Req 33.2).
 */
object WalkthroughSteps {
    val all: List<WalkthroughStep> = listOf(
        WalkthroughStep(
            id = 0,
            title = "Dashboard Overview",
            description = "View your total P&L, realized and unrealized gains, and open position count at a glance.",
            iconName = "dashboard",
            targetIdentifier = "dashboard-pnl",
            tooltipPosition = TooltipPosition.BOTTOM
        ),
        WalkthroughStep(
            id = 1,
            title = "Manage Positions",
            description = "Track and manage your open positions. Close individual trades or view detailed performance.",
            iconName = "show_chart",
            targetIdentifier = "positions",
            tooltipPosition = TooltipPosition.END
        ),
        WalkthroughStep(
            id = 2,
            title = "Stock Screener",
            description = "Filter stocks by fundamental and technical parameters to find your next trade opportunity.",
            iconName = "search",
            targetIdentifier = "screener",
            tooltipPosition = TooltipPosition.BOTTOM
        ),
        WalkthroughStep(
            id = 3,
            title = "Watchlists",
            description = "Create custom watchlists to track your favorite stocks with real-time prices.",
            iconName = "star",
            targetIdentifier = "watchlist",
            tooltipPosition = TooltipPosition.END
        ),
        WalkthroughStep(
            id = 4,
            title = "Connect Broker",
            description = "Link your broker account (Shoonya, Angel One, Kite, or Groww) to start trading.",
            iconName = "link",
            targetIdentifier = "broker",
            tooltipPosition = TooltipPosition.BOTTOM
        ),
        WalkthroughStep(
            id = 5,
            title = "AI Chatbot",
            description = "Ask questions about your trades and performance. Get insights with charts and analysis.",
            iconName = "chat",
            targetIdentifier = "chatbot",
            tooltipPosition = TooltipPosition.START
        ),
        WalkthroughStep(
            id = 6,
            title = "Kill Switch",
            description = "Instantly halt all trading activity in an emergency. One tap to protect your portfolio.",
            iconName = "power_settings_new",
            targetIdentifier = "kill-switch",
            tooltipPosition = TooltipPosition.BOTTOM
        )
    )

    val totalSteps: Int get() = all.size
}
