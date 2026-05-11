package com.lohitrade.ui.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Analytics
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lohitrade.data.cache.NetworkMonitor
import com.lohitrade.data.cache.OfflineCacheService
import com.lohitrade.data.models.PriceTick
import com.lohitrade.data.models.Position
import com.lohitrade.data.models.Signal
import com.lohitrade.data.trading.TradingService
import com.lohitrade.data.trading.WebSocketService
import com.lohitrade.ui.components.OfflineIndicator
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.text.NumberFormat
import java.util.Locale

/**
 * Dashboard showing P&L summary, open positions, and recent signals (Req 13.1).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    tradingService: TradingService,
    webSocketService: WebSocketService,
    offlineCacheService: OfflineCacheService? = null,
    networkMonitor: NetworkMonitor? = null,
    onNavigateToAnalytics: () -> Unit = {},
    onNavigateToKillSwitch: () -> Unit = {},
    onNavigateToPositions: () -> Unit = {}
) {
    val summary by tradingService.dashboardSummary.collectAsState()
    val positions by tradingService.positions.collectAsState()
    val signals by tradingService.signals.collectAsState()
    val killSwitchStatus by tradingService.killSwitchStatus.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()
    val priceTicks by webSocketService.priceTicks.collectAsState()
    val isConnected by (networkMonitor?.isConnected ?: MutableStateFlow(true)).collectAsState()
    val cacheTimestamps by (offlineCacheService?.lastUpdated ?: MutableStateFlow(emptyMap())).collectAsState()
    val scope = rememberCoroutineScope()

    // Load cached data on launch, then fetch from server (Req 14.1)
    LaunchedEffect(Unit) {
        offlineCacheService?.let { cache ->
            cache.loadDashboardSummary()
            cache.loadPositions()
            cache.loadSignals()
        }
        tradingService.fetchDashboard()
        tradingService.fetchKillSwitchStatus()
    }

    // Cache data on successful API responses
    LaunchedEffect(summary, positions, signals) {
        offlineCacheService?.let { cache ->
            summary?.let { cache.saveDashboardSummary(it) }
            if (positions.isNotEmpty()) cache.savePositions(positions)
            if (signals.isNotEmpty()) cache.saveSignals(signals)
        }
    }

    // Sync on connectivity restore (Req 14.3)
    LaunchedEffect(networkMonitor) {
        networkMonitor?.connectivityRestored?.collect {
            tradingService.fetchDashboard()
            tradingService.fetchKillSwitchStatus()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Dashboard") },
                actions = {
                    IconButton(onClick = onNavigateToKillSwitch) {
                        Icon(
                            Icons.Default.PowerSettingsNew,
                            contentDescription = "Kill Switch",
                            tint = if (killSwitchStatus?.isActive == true) Color.Red
                                   else MaterialTheme.colorScheme.onSurface
                        )
                    }
                    IconButton(onClick = onNavigateToAnalytics) {
                        Icon(Icons.Default.Analytics, contentDescription = "Analytics")
                    }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            // Offline indicator (Req 14.2)
            OfflineIndicator(
                isOffline = !isConnected,
                lastUpdated = offlineCacheService?.mostRecentUpdate
            )

            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
            // P&L Summary Card
            PnlSummaryCard(summary = summary, isLoading = isLoading)

            // Open Positions
            OpenPositionsSection(
                positions = positions,
                priceTicks = priceTicks,
                onSeeAll = onNavigateToPositions
            )

            // Recent Signals
            RecentSignalsSection(signals = signals)
            }
        }
    }
}

@Composable
private fun PnlSummaryCard(
    summary: com.lohitrade.data.models.DashboardSummary?,
    isLoading: Boolean
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            if (summary != null) {
                Text("Total P&L", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(4.dp))
                Text(
                    formatCurrency(summary.totalPnl),
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                    color = if (summary.totalPnl >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
                Text(
                    "${if (summary.totalPnlPercent >= 0) "+" else ""}${"%.2f".format(summary.totalPnlPercent)}%",
                    style = MaterialTheme.typography.titleMedium,
                    color = if (summary.totalPnlPercent >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                    StatItem("Realized", formatCurrency(summary.realizedPnl))
                    StatItem("Unrealized", formatCurrency(summary.unrealizedPnl))
                    StatItem("Positions", "${summary.openPositionCount}")
                }
            } else if (isLoading) {
                CircularProgressIndicator(modifier = Modifier.padding(16.dp))
            } else {
                Text("Unable to load dashboard", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun StatItem(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun OpenPositionsSection(
    positions: List<Position>,
    priceTicks: Map<String, PriceTick>,
    onSeeAll: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Open Positions", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = onSeeAll) { Text("See All") }
            }
            if (positions.isEmpty()) {
                Text("No open positions", color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
            } else {
                positions.take(5).forEach { position ->
                    PositionRow(position = position, tick = priceTicks[position.symbol])
                }
            }
        }
    }
}

@Composable
fun PositionRow(position: Position, tick: PriceTick?) {
    val currentLtp = tick?.ltp ?: position.ltp
    val currentPnl = if (tick != null) position.quantity * (tick.ltp - position.avgPrice) else position.pnl

    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(position.symbol, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            Text("${position.quantity} @ ${"%.2f".format(position.avgPrice)}",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("₹${"%.2f".format(currentLtp)}", style = MaterialTheme.typography.bodyMedium)
            Text(
                "${if (currentPnl >= 0) "+" else ""}₹${"%.2f".format(currentPnl)}",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold,
                color = if (currentPnl >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
            )
        }
    }
}

@Composable
private fun RecentSignalsSection(signals: List<Signal>) {
    Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Recent Signals", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            if (signals.isEmpty()) {
                Text("No recent signals", color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
            } else {
                signals.take(5).forEach { signal -> SignalRow(signal) }
            }
        }
    }
}

@Composable
private fun SignalRow(signal: Signal) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            if (signal.side == "BUY") "▲" else "▼",
            color = if (signal.side == "BUY") Color(0xFF4CAF50) else Color(0xFFF44336),
            fontWeight = FontWeight.Bold
        )
        Spacer(Modifier.width(8.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(signal.symbol, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            Text(signal.strategy, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("₹${"%.2f".format(signal.price)}", style = MaterialTheme.typography.bodyMedium)
            Text(signal.timestamp, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun formatCurrency(value: Double): String {
    val formatter = NumberFormat.getCurrencyInstance(Locale("en", "IN"))
    formatter.maximumFractionDigits = 2
    return formatter.format(value)
}
