package com.lohitrade.ui.analytics

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.lohitrade.data.models.DailyPnL
import com.lohitrade.data.models.EquityCurvePoint
import com.lohitrade.data.models.StrategyPerformance
import com.lohitrade.data.trading.TradingService
import kotlin.math.abs

/**
 * Strategy analytics with equity curves and daily P&L charts (Req 13.6).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AnalyticsScreen(tradingService: TradingService, onBack: () -> Unit = {}) {
    val analyticsData by tradingService.analyticsData.collectAsState()
    val isLoading by tradingService.isLoading.collectAsState()
    var selectedPeriod by remember { mutableStateOf("30d") }
    val periods = listOf("7d", "30d", "90d", "1y", "all")

    LaunchedEffect(selectedPeriod) { tradingService.fetchAnalytics(selectedPeriod) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Analytics") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.titleLarge)
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding)
                .verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Period picker
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                periods.forEachIndexed { index, period ->
                    SegmentedButton(
                        selected = selectedPeriod == period,
                        onClick = { selectedPeriod = period },
                        shape = SegmentedButtonDefaults.itemShape(index, periods.size)
                    ) { Text(period.uppercase()) }
                }
            }

            // Equity Curve
            ChartCard(title = "Equity Curve") {
                val data = analyticsData?.equityCurve
                if (!data.isNullOrEmpty()) {
                    EquityCurveChart(data = data, modifier = Modifier.fillMaxWidth().height(200.dp))
                } else {
                    PlaceholderText()
                }
            }

            // Daily P&L
            ChartCard(title = "Daily P&L") {
                val data = analyticsData?.dailyPnl
                if (!data.isNullOrEmpty()) {
                    DailyPnLChart(data = data, modifier = Modifier.fillMaxWidth().height(200.dp))
                } else {
                    PlaceholderText()
                }
            }

            // Strategy Performance
            ChartCard(title = "Strategy Performance") {
                val strategies = analyticsData?.strategies
                if (!strategies.isNullOrEmpty()) {
                    strategies.forEach { strategy -> StrategyRow(strategy) }
                } else {
                    PlaceholderText()
                }
            }
        }
    }
}

@Composable
private fun ChartCard(title: String, content: @Composable () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(2.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            content()
        }
    }
}

@Composable
private fun PlaceholderText() {
    Text("No data available", color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
}

@Composable
fun EquityCurveChart(data: List<EquityCurvePoint>, modifier: Modifier = Modifier) {
    val lineColor = Color(0xFF2196F3)
    Canvas(modifier = modifier) {
        if (data.size < 2) return@Canvas
        val values = data.map { it.equity.toFloat() }
        val minVal = values.min()
        val maxVal = values.max()
        val range = (maxVal - minVal).coerceAtLeast(1f)

        val path = Path()
        data.forEachIndexed { index, point ->
            val x = size.width * index / (data.size - 1)
            val y = size.height * (1f - (point.equity.toFloat() - minVal) / range)
            if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        drawPath(path, lineColor, style = Stroke(width = 3f))
    }
}

@Composable
fun DailyPnLChart(data: List<DailyPnL>, modifier: Modifier = Modifier) {
    Canvas(modifier = modifier) {
        if (data.isEmpty()) return@Canvas
        val maxAbs = data.maxOf { abs(it.pnl).toFloat() }.coerceAtLeast(1f)
        val barWidth = (size.width / data.size).coerceAtLeast(2f) - 1f
        val midY = size.height / 2

        data.forEachIndexed { index, point ->
            val x = size.width * index / data.size
            val barHeight = (abs(point.pnl).toFloat() / maxAbs) * midY
            val color = if (point.pnl >= 0) Color(0xFF4CAF50).copy(alpha = 0.7f)
                        else Color(0xFFF44336).copy(alpha = 0.7f)
            val topLeft = if (point.pnl >= 0) Offset(x, midY - barHeight) else Offset(x, midY)
            drawRect(color, topLeft, androidx.compose.ui.geometry.Size(barWidth, barHeight))
        }
        // Zero line
        drawLine(Color.Gray.copy(alpha = 0.3f), Offset(0f, midY), Offset(size.width, midY), strokeWidth = 1f)
    }
}

@Composable
private fun StrategyRow(strategy: StrategyPerformance) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(strategy.name, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            Text("${strategy.tradeCount} trades", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("₹${"%.2f".format(strategy.totalPnl)}", fontWeight = FontWeight.SemiBold,
                color = if (strategy.totalPnl >= 0) Color(0xFF4CAF50) else Color(0xFFF44336))
            Text("Win: ${"%.1f".format(strategy.winRate * 100)}%", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
