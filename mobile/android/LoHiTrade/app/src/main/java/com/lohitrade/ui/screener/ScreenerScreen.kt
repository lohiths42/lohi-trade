package com.lohitrade.ui.screener

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.lohitrade.data.models.*
import com.lohitrade.data.trading.TradingService
import kotlinx.coroutines.launch

/**
 * Stock screener with filter params and sortable results (Req 13.8).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScreenerScreen(tradingService: TradingService, onBack: () -> Unit = {}) {
    val results by tradingService.screenerResults.collectAsState()
    val templates by tradingService.screenerTemplates.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()
    val scope = rememberCoroutineScope()
    var showFilterSheet by remember { mutableStateOf(false) }
    var filters by remember { mutableStateOf(ScreenerFilters()) }
    var sortBy by remember { mutableStateOf("market_cap") }
    var sortOrder by remember { mutableStateOf("desc") }
    var currentPage by remember { mutableIntStateOf(1) }

    LaunchedEffect(Unit) {
        tradingService.fetchScreenerTemplates()
        tradingService.fetchScreenerPresets()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Screener") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                },
                actions = {
                    IconButton(onClick = { showFilterSheet = true }) {
                        Icon(Icons.Default.FilterList, contentDescription = "Filters")
                    }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            // Templates row
            if (templates.isNotEmpty()) {
                Row(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    templates.take(3).forEach { template ->
                        AssistChip(
                            onClick = {
                                filters = template.filters
                                currentPage = 1
                                scope.launch {
                                    tradingService.searchScreener(
                                        ScreenerRequest(template.filters, sortBy, sortOrder, 1)
                                    )
                                }
                            },
                            label = { Text(template.name, style = MaterialTheme.typography.labelSmall) }
                        )
                    }
                }
            }

            // Results summary
            results?.let { resp ->
                Text(
                    "${resp.totalCount} results · Page ${resp.page}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                )
            }

            // Results list
            val resultList = results?.results
            if (resultList.isNullOrEmpty() && !isLoading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("Set filters to find stocks", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(resultList ?: emptyList()) { result ->
                        ScreenerResultRow(result)
                    }
                    // Load more
                    results?.let { resp ->
                        if (resp.totalCount > resp.page * resp.pageSize) {
                            item {
                                TextButton(
                                    onClick = {
                                        currentPage++
                                        scope.launch {
                                            tradingService.searchScreener(
                                                ScreenerRequest(filters, sortBy, sortOrder, currentPage)
                                            )
                                        }
                                    },
                                    modifier = Modifier.fillMaxWidth()
                                ) { Text("Load More") }
                            }
                        }
                    }
                }
            }

            if (isLoading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }
        }
    }

    // Filter bottom sheet
    if (showFilterSheet) {
        ScreenerFilterSheet(
            filters = filters,
            sortBy = sortBy,
            sortOrder = sortOrder,
            onFiltersChanged = { filters = it },
            onSortByChanged = { sortBy = it },
            onSortOrderChanged = { sortOrder = it },
            onApply = {
                showFilterSheet = false
                currentPage = 1
                scope.launch {
                    tradingService.searchScreener(ScreenerRequest(filters, sortBy, sortOrder, 1))
                }
            },
            onDismiss = { showFilterSheet = false }
        )
    }
}

@Composable
private fun ScreenerResultRow(result: ScreenerResult) {
    Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(1.dp)) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(result.symbol, fontWeight = FontWeight.Bold)
                    Text(result.companyName, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("₹${"%.2f".format(result.ltp)}")
                    Text(
                        "${if (result.changePercent >= 0) "+" else ""}${"%.2f".format(result.changePercent)}%",
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.SemiBold,
                        color = if (result.changePercent >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                result.sector?.let {
                    Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                result.peRatio?.let {
                    Text("PE: ${"%.1f".format(it)}", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                result.marketCap?.let {
                    Text("MCap: ${formatMarketCap(it)}", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ScreenerFilterSheet(
    filters: ScreenerFilters,
    sortBy: String,
    sortOrder: String,
    onFiltersChanged: (ScreenerFilters) -> Unit,
    onSortByChanged: (String) -> Unit,
    onSortOrderChanged: (String) -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit
) {
    var peMin by remember { mutableStateOf(filters.peRatio?.min?.toString() ?: "") }
    var peMax by remember { mutableStateOf(filters.peRatio?.max?.toString() ?: "") }
    var rsiMin by remember { mutableStateOf(filters.rsi14?.min?.toString() ?: "") }
    var rsiMax by remember { mutableStateOf(filters.rsi14?.max?.toString() ?: "") }
    var exchange by remember { mutableStateOf(filters.exchange ?: "") }
    var marketCap by remember { mutableStateOf(filters.marketCapCategory ?: "") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Filters") },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("Fundamental", style = MaterialTheme.typography.labelLarge)
                RangeInput("PE Ratio", peMin, peMax, { peMin = it }, { peMax = it })

                Text("Technical", style = MaterialTheme.typography.labelLarge)
                RangeInput("RSI (14)", rsiMin, rsiMax, { rsiMin = it }, { rsiMax = it })

                Text("Meta", style = MaterialTheme.typography.labelLarge)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("" to "All", "NSE" to "NSE", "BSE" to "BSE").forEach { (value, label) ->
                        FilterChip(
                            selected = exchange == value,
                            onClick = { exchange = value },
                            label = { Text(label) }
                        )
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("" to "All", "large-cap" to "Large", "mid-cap" to "Mid", "small-cap" to "Small").forEach { (value, label) ->
                        FilterChip(
                            selected = marketCap == value,
                            onClick = { marketCap = value },
                            label = { Text(label) }
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onFiltersChanged(ScreenerFilters(
                    peRatio = rangeOrNull(peMin, peMax),
                    rsi14 = rangeOrNull(rsiMin, rsiMax),
                    exchange = exchange.ifBlank { null },
                    marketCapCategory = marketCap.ifBlank { null }
                ))
                onApply()
            }) { Text("Apply") }
        },
        dismissButton = {
            TextButton(onClick = {
                onFiltersChanged(ScreenerFilters())
                peMin = ""; peMax = ""; rsiMin = ""; rsiMax = ""; exchange = ""; marketCap = ""
            }) { Text("Reset") }
        }
    )
}

@Composable
private fun RangeInput(
    label: String,
    minVal: String, maxVal: String,
    onMinChange: (String) -> Unit, onMaxChange: (String) -> Unit
) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
        OutlinedTextField(
            value = minVal, onValueChange = onMinChange,
            label = { Text("Min") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.width(80.dp),
            singleLine = true
        )
        Text("–")
        OutlinedTextField(
            value = maxVal, onValueChange = onMaxChange,
            label = { Text("Max") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.width(80.dp),
            singleLine = true
        )
    }
}

private fun rangeOrNull(min: String, max: String): ScreenerRange? {
    val minD = min.toDoubleOrNull()
    val maxD = max.toDoubleOrNull()
    return if (minD != null || maxD != null) ScreenerRange(minD, maxD) else null
}

private fun formatMarketCap(value: Double): String {
    return when {
        value >= 100000 -> "₹${"%.1f".format(value / 100000)}L Cr"
        value >= 100 -> "₹${"%.0f".format(value)} Cr"
        else -> "₹${"%.2f".format(value)}"
    }
}
