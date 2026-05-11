package com.lohitrade.ui.notifications

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.lohitrade.data.models.AppNotification
import com.lohitrade.data.trading.TradingService
import kotlinx.coroutines.launch

/**
 * Notification center for trade, system, and alert notifications (Req 13.9).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotificationCenterScreen(tradingService: TradingService, onBack: () -> Unit = {}) {
    val notifications by tradingService.notifications.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()
    val scope = rememberCoroutineScope()
    var selectedFilter by remember { mutableStateOf("All") }
    val filters = listOf("All", "Trades", "System", "Alerts")

    LaunchedEffect(Unit) { tradingService.fetchNotifications() }

    val filtered = when (selectedFilter) {
        "Trades" -> notifications.filter { it.type == "TRADE" }
        "System" -> notifications.filter { it.type == "SYSTEM" }
        "Alerts" -> notifications.filter { it.type == "ALERT" }
        else -> notifications
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Notifications") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                },
                actions = {
                    TextButton(onClick = { scope.launch { tradingService.markAllNotificationsRead() } }) {
                        Text("Mark All Read", style = MaterialTheme.typography.labelSmall)
                    }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            // Filter tabs
            SingleChoiceSegmentedButtonRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                filters.forEachIndexed { index, filter ->
                    SegmentedButton(
                        selected = selectedFilter == filter,
                        onClick = { selectedFilter = filter },
                        shape = SegmentedButtonDefaults.itemShape(index, filters.size)
                    ) { Text(filter, style = MaterialTheme.typography.labelSmall) }
                }
            }

            if (filtered.isEmpty() && !isLoading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("No notifications", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    items(filtered, key = { it.id }) { notification ->
                        NotificationRow(notification)
                    }
                }
            }
        }
    }
}

@Composable
private fun NotificationRow(notification: AppNotification) {
    val iconAndColor = when (notification.type) {
        "TRADE" -> "↔" to Color(0xFF2196F3)
        "SYSTEM" -> "⚙" to Color.Gray
        "ALERT" -> "⚠" to Color(0xFFFF9800)
        else -> "•" to Color.Gray
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .alpha(if (notification.isRead) 0.7f else 1f),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(iconAndColor.first, color = iconAndColor.second, style = MaterialTheme.typography.titleMedium)
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    notification.title,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (notification.isRead) FontWeight.Normal else FontWeight.Bold,
                    modifier = Modifier.weight(1f)
                )
                if (!notification.isRead) {
                    Spacer(Modifier.width(4.dp))
                    Surface(
                        shape = MaterialTheme.shapes.small,
                        color = Color(0xFF2196F3),
                        modifier = Modifier.size(8.dp)
                    ) {}
                }
            }
            Text(notification.message, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
            Text(notification.createdAt, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
