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
import com.lohitrade.data.models.PriceTick
import com.lohitrade.data.models.Position
import com.lohitrade.data.trading.TradingService
import com.lohitrade.data.trading.WebSocketService
import kotlinx.coroutines.launch

/**
 * Position management screen — view and close positions (Req 13.3).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PositionsScreen(
    tradingService: TradingService,
    webSocketService: WebSocketService,
    onBack: () -> Unit = {}
) {
    val positions by tradingService.positions.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()
    val priceTicks by webSocketService.priceTicks.collectAsState()
    val scope = rememberCoroutineScope()
    var positionToClose by remember { mutableStateOf<Position?>(null) }

    LaunchedEffect(Unit) { tradingService.fetchPositions() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Positions") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                }
            )
        }
    ) { padding ->
        if (positions.isEmpty() && !isLoading) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No open positions", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(positions, key = { it.id }) { position ->
                    PositionCard(
                        position = position,
                        tick = priceTicks[position.symbol],
                        onClose = { positionToClose = position }
                    )
                }
            }
        }

        if (isLoading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        }
    }

    // Close confirmation dialog
    positionToClose?.let { pos ->
        AlertDialog(
            onDismissRequest = { positionToClose = null },
            title = { Text("Close Position") },
            text = { Text("Close ${pos.quantity} ${pos.symbol} at market?") },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch { tradingService.closePosition(pos.id) }
                    positionToClose = null
                }) { Text("Close", color = Color(0xFFF44336)) }
            },
            dismissButton = {
                TextButton(onClick = { positionToClose = null }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun PositionCard(position: Position, tick: PriceTick?, onClose: () -> Unit) {
    val currentLtp = tick?.ltp ?: position.ltp
    val currentPnl = if (tick != null) position.quantity * (tick.ltp - position.avgPrice) else position.pnl

    Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp)) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(position.symbol, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text("${position.side} · ${position.quantity} @ ${"%.2f".format(position.avgPrice)}",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                position.strategy?.let {
                    Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                }
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("₹${"%.2f".format(currentLtp)}", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "${if (currentPnl >= 0) "+" else ""}₹${"%.2f".format(currentPnl)}",
                    fontWeight = FontWeight.SemiBold,
                    color = if (currentPnl >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
                Spacer(Modifier.height(4.dp))
                OutlinedButton(onClick = onClose, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)) {
                    Text("Close", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}
