package com.lohitrade.ui.watchlist

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.lohitrade.data.models.PriceTick
import com.lohitrade.data.models.Watchlist
import com.lohitrade.data.models.WatchlistItem
import com.lohitrade.data.trading.TradingService
import com.lohitrade.data.trading.WebSocketService
import kotlinx.coroutines.launch

/**
 * Watchlist CRUD and security management (Req 13.7).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WatchlistScreen(
    tradingService: TradingService,
    webSocketService: WebSocketService,
    onBack: () -> Unit = {}
) {
    val watchlists by tradingService.watchlists.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()
    val scope = rememberCoroutineScope()
    var showCreateDialog by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    var selectedWatchlistId by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) { tradingService.fetchWatchlists() }

    if (selectedWatchlistId != null) {
        WatchlistDetailScreen(
            tradingService = tradingService,
            webSocketService = webSocketService,
            watchlistId = selectedWatchlistId!!,
            onBack = { selectedWatchlistId = null }
        )
    } else {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("Watchlists") },
                    navigationIcon = {
                        IconButton(onClick = onBack) {
                            Text("←", style = MaterialTheme.typography.titleLarge)
                        }
                    },
                    actions = {
                        IconButton(onClick = { newName = ""; showCreateDialog = true }) {
                            Icon(Icons.Default.Add, contentDescription = "Create Watchlist")
                        }
                    }
                )
            }
        ) { padding ->
            if (watchlists.isEmpty() && !isLoading) {
                Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                    Text("No watchlists. Tap + to create one.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(watchlists, key = { it.id }) { watchlist ->
                        WatchlistRow(
                            watchlist = watchlist,
                            onClick = { selectedWatchlistId = watchlist.id },
                            onDelete = if (!watchlist.isPrebuilt) {
                                { scope.launch { tradingService.deleteWatchlist(watchlist.id) } }
                            } else null
                        )
                    }
                }
            }
        }

        if (showCreateDialog) {
            AlertDialog(
                onDismissRequest = { showCreateDialog = false },
                title = { Text("New Watchlist") },
                text = {
                    OutlinedTextField(
                        value = newName,
                        onValueChange = { newName = it },
                        label = { Text("Name") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                },
                confirmButton = {
                    TextButton(onClick = {
                        if (newName.isNotBlank()) {
                            scope.launch { tradingService.createWatchlist(newName) }
                            showCreateDialog = false
                        }
                    }) { Text("Create") }
                },
                dismissButton = {
                    TextButton(onClick = { showCreateDialog = false }) { Text("Cancel") }
                }
            )
        }
    }
}

@Composable
private fun WatchlistRow(watchlist: Watchlist, onClick: () -> Unit, onDelete: (() -> Unit)?) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(2.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(watchlist.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                    if (watchlist.isPrebuilt) {
                        Spacer(Modifier.width(8.dp))
                        Text("Pre-built", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary)
                    }
                }
                Text("${watchlist.itemCount} securities", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            onDelete?.let {
                IconButton(onClick = it) {
                    Icon(Icons.Default.Delete, contentDescription = "Delete",
                        tint = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WatchlistDetailScreen(
    tradingService: TradingService,
    webSocketService: WebSocketService,
    watchlistId: String,
    onBack: () -> Unit
) {
    val detail by tradingService.currentWatchlist.collectAsState()
    val priceTicks by webSocketService.priceTicks.collectAsState()
    val scope = rememberCoroutineScope()
    var showAddDialog by remember { mutableStateOf(false) }
    var symbolToAdd by remember { mutableStateOf("") }

    LaunchedEffect(watchlistId) {
        tradingService.fetchWatchlistDetail(watchlistId)
    }

    LaunchedEffect(detail) {
        detail?.items?.map { it.symbol }?.let { symbols ->
            if (symbols.isNotEmpty()) webSocketService.subscribe(symbols)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(detail?.name ?: "Watchlist") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                },
                actions = {
                    if (detail?.isPrebuilt != true) {
                        IconButton(onClick = { symbolToAdd = ""; showAddDialog = true }) {
                            Icon(Icons.Default.Add, contentDescription = "Add Security")
                        }
                    }
                }
            )
        }
    ) { padding ->
        val items = detail?.items ?: emptyList()
        if (items.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No securities in this watchlist", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                items(items, key = { it.symbol }) { item ->
                    WatchlistItemRow(
                        item = item,
                        tick = priceTicks[item.symbol],
                        onRemove = if (detail?.isPrebuilt != true) {
                            { scope.launch { tradingService.removeSecurity(watchlistId, item.symbol) } }
                        } else null
                    )
                }
            }
        }
    }

    if (showAddDialog) {
        AlertDialog(
            onDismissRequest = { showAddDialog = false },
            title = { Text("Add Security") },
            text = {
                OutlinedTextField(
                    value = symbolToAdd,
                    onValueChange = { symbolToAdd = it.uppercase() },
                    label = { Text("Symbol (e.g. RELIANCE)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    if (symbolToAdd.isNotBlank()) {
                        scope.launch { tradingService.addSecurity(watchlistId, symbolToAdd) }
                        showAddDialog = false
                    }
                }) { Text("Add") }
            },
            dismissButton = {
                TextButton(onClick = { showAddDialog = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun WatchlistItemRow(item: WatchlistItem, tick: PriceTick?, onRemove: (() -> Unit)?) {
    val ltp = tick?.ltp ?: item.ltp ?: 0.0
    val change = tick?.change ?: item.change ?: 0.0
    val changePercent = tick?.changePercent ?: item.changePercent ?: 0.0

    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(item.symbol, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            Text(item.companyName, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("₹${"%.2f".format(ltp)}", style = MaterialTheme.typography.bodyMedium)
            Text(
                "${if (change >= 0) "+" else ""}${"%.2f".format(change)} (${"%.2f".format(changePercent)}%)",
                style = MaterialTheme.typography.bodySmall,
                color = if (change >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
            )
        }
        onRemove?.let {
            IconButton(onClick = it) {
                Icon(Icons.Default.Delete, contentDescription = "Remove",
                    tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp))
            }
        }
    }
}
