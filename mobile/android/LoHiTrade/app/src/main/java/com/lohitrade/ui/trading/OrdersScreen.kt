package com.lohitrade.ui.trading

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.lohitrade.data.models.Order
import com.lohitrade.data.trading.TradingService

/**
 * Order history with status, fill details, and rejection reasons (Req 13.4).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrdersScreen(tradingService: TradingService, onBack: () -> Unit = {}) {
    val orders by tradingService.orders.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()

    LaunchedEffect(Unit) { tradingService.fetchOrders() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Order History") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                }
            )
        }
    ) { padding ->
        if (orders.isEmpty() && !isLoading) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No orders", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(orders, key = { it.id }) { order -> OrderCard(order) }
            }
        }
    }
}

@Composable
private fun OrderCard(order: Order) {
    val statusColor = when (order.status) {
        "COMPLETE" -> Color(0xFF4CAF50)
        "REJECTED" -> Color(0xFFF44336)
        "CANCELLED" -> Color(0xFFFF9800)
        "PENDING", "OPEN" -> Color(0xFF2196F3)
        else -> MaterialTheme.colorScheme.onSurface
    }

    Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(order.symbol, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f))
                Text(order.status, color = statusColor, fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.labelMedium)
            }
            Spacer(Modifier.height(4.dp))
            Row {
                Text("${order.side} · ${order.orderType} · Qty: ${order.quantity}",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            order.price?.let {
                Text("Price: ₹${"%.2f".format(it)}", style = MaterialTheme.typography.bodySmall)
            }
            if (order.filledQuantity > 0) {
                Text("Filled: ${order.filledQuantity} @ ₹${"%.2f".format(order.avgFillPrice ?: 0.0)}",
                    style = MaterialTheme.typography.bodySmall, color = Color(0xFF4CAF50))
            }
            order.rejectionReason?.let {
                Text("Reason: $it", style = MaterialTheme.typography.bodySmall, color = Color(0xFFF44336))
            }
            Spacer(Modifier.height(4.dp))
            Text(order.placedAt, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
