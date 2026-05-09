package com.lohitrade.ui.trading

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lohitrade.data.trading.TradingService
import kotlinx.coroutines.launch

/**
 * Kill switch with confirmation dialog (Req 13.5).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KillSwitchScreen(tradingService: TradingService, onBack: () -> Unit = {}) {
    val killSwitchStatus by tradingService.killSwitchStatus.collectAsState()
    val scope = rememberCoroutineScope()
    var showConfirmDialog by remember { mutableStateOf(false) }
    var reason by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { tradingService.fetchKillSwitchStatus() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Kill Switch") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            val isActive = killSwitchStatus?.isActive == true

            Text(
                if (isActive) "⚠️" else "🛡️",
                fontSize = 64.sp
            )
            Spacer(Modifier.height(16.dp))
            Text(
                if (isActive) "Kill Switch ACTIVE" else "Kill Switch Inactive",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = if (isActive) Color(0xFFF44336) else Color(0xFF4CAF50)
            )
            Spacer(Modifier.height(8.dp))
            Text(
                if (isActive) "All trading is halted. Open positions will be closed."
                else "Trading is operating normally.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )

            killSwitchStatus?.let { status ->
                if (isActive) {
                    Spacer(Modifier.height(16.dp))
                    status.activatedAt?.let {
                        Text("Activated: $it", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    status.reason?.let {
                        Text("Reason: $it", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }

            Spacer(Modifier.height(32.dp))

            Button(
                onClick = { showConfirmDialog = true },
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (isActive) Color(0xFF4CAF50) else Color(0xFFF44336)
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    if (isActive) "Deactivate Kill Switch" else "Activate Kill Switch",
                    style = MaterialTheme.typography.titleMedium
                )
            }
        }
    }

    if (showConfirmDialog) {
        val isActive = killSwitchStatus?.isActive == true
        AlertDialog(
            onDismissRequest = { showConfirmDialog = false },
            title = { Text(if (isActive) "Deactivate Kill Switch?" else "Activate Kill Switch?") },
            text = {
                Column {
                    Text(
                        if (isActive) "This will resume normal trading operations."
                        else "This will halt all trading and close open positions."
                    )
                    if (!isActive) {
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = reason,
                            onValueChange = { reason = it },
                            label = { Text("Reason (optional)") },
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        tradingService.toggleKillSwitch(!isActive, reason.ifBlank { null })
                    }
                    showConfirmDialog = false
                    reason = ""
                }) {
                    Text("Confirm", color = if (isActive) Color(0xFF4CAF50) else Color(0xFFF44336))
                }
            },
            dismissButton = {
                TextButton(onClick = { showConfirmDialog = false; reason = "" }) { Text("Cancel") }
            }
        )
    }
}
