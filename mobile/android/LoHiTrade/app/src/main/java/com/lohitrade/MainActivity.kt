package com.lohitrade

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import com.lohitrade.data.api.ApiClient
import com.lohitrade.data.api.TradingApi
import com.lohitrade.data.auth.AuthService
import com.lohitrade.data.auth.BiometricService
import com.lohitrade.data.auth.KeystoreService
import com.lohitrade.data.cache.NetworkMonitor
import com.lohitrade.data.cache.OfflineCacheDatabase
import com.lohitrade.data.cache.OfflineCacheService
import com.lohitrade.data.onboarding.OnboardingService
import com.lohitrade.data.push.PushNotificationService
import com.lohitrade.data.trading.TradingService
import com.lohitrade.data.trading.WebSocketService
import com.lohitrade.data.api.ChatbotApi
import com.lohitrade.data.chatbot.ChatbotService
import com.lohitrade.ui.analytics.AnalyticsScreen
import com.lohitrade.ui.auth.LoginScreen
import com.lohitrade.ui.chatbot.ChatImageDetailScreen
import com.lohitrade.ui.chatbot.ChatScreen
import com.lohitrade.ui.dashboard.DashboardScreen
import com.lohitrade.ui.notifications.NotificationCenterScreen
import com.lohitrade.ui.onboarding.WalkthroughOverlay
import com.lohitrade.ui.screener.ScreenerScreen
import com.lohitrade.ui.trading.KillSwitchScreen
import com.lohitrade.ui.trading.OrdersScreen
import com.lohitrade.ui.trading.PositionsScreen
import com.lohitrade.ui.watchlist.WatchlistScreen

/**
 * Single activity with Jetpack Compose (Req 12.1).
 *
 * Hosts the Compose navigation graph with bottom navigation for
 * Dashboard, Positions, Watchlists, Screener, and Notifications.
 */
class MainActivity : ComponentActivity() {

    private lateinit var keystoreService: KeystoreService
    private lateinit var apiClient: ApiClient
    private lateinit var authService: AuthService
    private lateinit var tradingService: TradingService
    private lateinit var webSocketService: WebSocketService
    private lateinit var networkMonitor: NetworkMonitor
    private lateinit var offlineCacheService: OfflineCacheService
    private lateinit var onboardingService: OnboardingService
    private lateinit var chatbotService: ChatbotService
    private val biometricService = BiometricService()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Initialize services (in production, use Hilt DI)
        keystoreService = KeystoreService(applicationContext)
        apiClient = ApiClient(keystoreService = keystoreService)
        authService = AuthService(apiClient, keystoreService)

        val tradingApi = apiClient.create(TradingApi::class.java)
        tradingService = TradingService(tradingApi)
        webSocketService = WebSocketService(
            baseUrl = com.lohitrade.BuildConfig.API_BASE_URL,
            keystoreService = keystoreService
        )

        // Initialize offline cache (Req 14.1) and network monitor (Req 14.2)
        val cacheDb = OfflineCacheDatabase.getInstance(applicationContext)
        offlineCacheService = OfflineCacheService(cacheDb.cacheDao())
        networkMonitor = NetworkMonitor(applicationContext)
        networkMonitor.start()

        // Initialize onboarding service (Req 33.2, 33.5, 33.8)
        val onboardingPrefs = applicationContext.getSharedPreferences("onboarding", MODE_PRIVATE)
        onboardingService = OnboardingService(prefs = onboardingPrefs)

        // Initialize chatbot service (Req 18.1, 20.7)
        val chatbotApi = apiClient.create(ChatbotApi::class.java)
        chatbotService = ChatbotService(chatbotApi)

        // Request push notification permission and subscribe to defaults
        PushNotificationService.subscribeToDefaults()

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    val isAuthenticated by authService.isAuthenticated.collectAsState()

                    if (isAuthenticated) {
                        // Connect WebSocket for real-time prices (Req 12.7)
                        LaunchedEffect(Unit) { webSocketService.connect() }
                        DisposableEffect(Unit) { onDispose { webSocketService.disconnect() } }

                        // Check onboarding status on login (Req 33.1)
                        LaunchedEffect(Unit) { onboardingService.checkOnboardingStatus() }

                        Box(modifier = Modifier.fillMaxSize()) {
                            MainNavigation(
                                tradingService = tradingService,
                                webSocketService = webSocketService,
                                offlineCacheService = offlineCacheService,
                                networkMonitor = networkMonitor,
                                chatbotService = chatbotService
                            )

                            // Walkthrough overlay on top of main content (Req 33.2, 33.3)
                            WalkthroughOverlay(onboardingService = onboardingService)
                        }
                    } else {
                        LoginScreen(
                            authService = authService,
                            biometricService = biometricService,
                            activity = this@MainActivity
                        )
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        networkMonitor.stop()
    }
}

/** Bottom navigation tabs. */
private enum class MainTab(val label: String) {
    Dashboard("Dashboard"),
    Positions("Positions"),
    Watchlists("Watchlists"),
    Screener("Screener"),
    Notifications("Alerts")
}

/** Detail screens navigated from tabs. */
private enum class DetailScreen {
    Analytics, KillSwitch, Orders, Chatbot
}

/** Data for the chart image detail overlay. */
private data class ChartDetailData(
    val imageUrl: String,
    val messageContent: String
)

@Composable
private fun MainNavigation(
    tradingService: TradingService,
    webSocketService: WebSocketService,
    offlineCacheService: OfflineCacheService,
    networkMonitor: NetworkMonitor,
    chatbotService: ChatbotService
) {
    var currentTab by remember { mutableStateOf(MainTab.Dashboard) }
    var detailScreen by remember { mutableStateOf<DetailScreen?>(null) }
    var chartDetail by remember { mutableStateOf<ChartDetailData?>(null) }

    // If showing full-screen chart detail, render it on top
    chartDetail?.let { detail ->
        ChatImageDetailScreen(
            imageUrl = detail.imageUrl,
            messageContent = detail.messageContent,
            onBack = { chartDetail = null }
        )
        return
    }

    // If a detail screen is active, show it instead of tabs
    detailScreen?.let { screen ->
        when (screen) {
            DetailScreen.Analytics -> AnalyticsScreen(
                tradingService = tradingService,
                onBack = { detailScreen = null }
            )
            DetailScreen.KillSwitch -> KillSwitchScreen(
                tradingService = tradingService,
                onBack = { detailScreen = null }
            )
            DetailScreen.Orders -> OrdersScreen(
                tradingService = tradingService,
                onBack = { detailScreen = null }
            )
            DetailScreen.Chatbot -> ChatScreen(
                chatbotService = chatbotService,
                onBack = { detailScreen = null },
                onChartTap = { url, content ->
                    chartDetail = ChartDetailData(url, content)
                }
            )
        }
        return
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                MainTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = currentTab == tab,
                        onClick = { currentTab = tab },
                        icon = {
                            Icon(
                                when (tab) {
                                    MainTab.Dashboard -> Icons.Default.Dashboard
                                    MainTab.Positions -> Icons.Default.ShowChart
                                    MainTab.Watchlists -> Icons.Default.Star
                                    MainTab.Screener -> Icons.Default.Search
                                    MainTab.Notifications -> Icons.Default.Notifications
                                },
                                contentDescription = tab.label
                            )
                        },
                        label = { Text(tab.label) }
                    )
                }
            }
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { detailScreen = DetailScreen.Chatbot }
            ) {
                Icon(Icons.Default.Chat, contentDescription = "AI Chatbot")
            }
        }
    ) { padding ->
        Surface(modifier = Modifier.padding(padding)) {
            when (currentTab) {
                MainTab.Dashboard -> DashboardScreen(
                    tradingService = tradingService,
                    webSocketService = webSocketService,
                    offlineCacheService = offlineCacheService,
                    networkMonitor = networkMonitor,
                    onNavigateToAnalytics = { detailScreen = DetailScreen.Analytics },
                    onNavigateToKillSwitch = { detailScreen = DetailScreen.KillSwitch },
                    onNavigateToPositions = { currentTab = MainTab.Positions }
                )
                MainTab.Positions -> PositionsScreen(
                    tradingService = tradingService,
                    webSocketService = webSocketService,
                    onBack = { currentTab = MainTab.Dashboard }
                )
                MainTab.Watchlists -> WatchlistScreen(
                    tradingService = tradingService,
                    webSocketService = webSocketService,
                    onBack = { currentTab = MainTab.Dashboard }
                )
                MainTab.Screener -> ScreenerScreen(
                    tradingService = tradingService,
                    onBack = { currentTab = MainTab.Dashboard }
                )
                MainTab.Notifications -> NotificationCenterScreen(
                    tradingService = tradingService,
                    onBack = { currentTab = MainTab.Dashboard }
                )
            }
        }
    }
}
