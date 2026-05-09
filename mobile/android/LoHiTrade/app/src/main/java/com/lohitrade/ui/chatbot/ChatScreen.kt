package com.lohitrade.ui.chatbot

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.lohitrade.data.chatbot.ChatbotService
import com.lohitrade.data.models.ChatMessage
import com.lohitrade.data.models.ChatRole
import kotlinx.coroutines.launch

/**
 * Conversational chat interface for the AI chatbot (Req 18.1, 20.7).
 *
 * - User messages: right-aligned, primary color bubble
 * - Assistant messages: left-aligned, surface variant bubble
 * - Inline chart images via Coil AsyncImage, tap for full-screen detail
 * - Typing indicator while waiting for response
 * - Auto-scrolls to latest message
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    chatbotService: ChatbotService,
    onBack: () -> Unit,
    onChartTap: (imageUrl: String, messageContent: String) -> Unit
) {
    val messages by chatbotService.messages.collectAsState()
    val isLoading by chatbotService.isLoading.collectAsState()
    val errorMessage by chatbotService.errorMessage.collectAsState()

    var inputText by remember { mutableStateOf("") }
    var showMenu by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()

    // Load history on first composition
    LaunchedEffect(Unit) {
        chatbotService.fetchHistory()
    }

    // Auto-scroll to bottom when messages change or loading state changes
    LaunchedEffect(messages.size, isLoading) {
        if (messages.isNotEmpty() || isLoading) {
            // Scroll to the last item index + 1 if loading (for typing indicator)
            val targetIndex = if (isLoading) messages.size else messages.size - 1
            if (targetIndex >= 0) {
                listState.animateScrollToItem(targetIndex)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("AI Chatbot") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    Box {
                        IconButton(onClick = { showMenu = true }) {
                            Icon(Icons.Default.MoreVert, contentDescription = "Menu")
                        }
                        DropdownMenu(
                            expanded = showMenu,
                            onDismissRequest = { showMenu = false }
                        ) {
                            DropdownMenuItem(
                                text = { Text("Clear Chat") },
                                onClick = {
                                    showMenu = false
                                    coroutineScope.launch { chatbotService.clearSession() }
                                }
                            )
                        }
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            // Message list
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                if (messages.isEmpty() && !isLoading) {
                    item { EmptyState() }
                }

                items(messages, key = { it.id }) { message ->
                    ChatBubble(
                        message = message,
                        onChartTap = { url -> onChartTap(url, message.content) }
                    )
                }

                if (isLoading) {
                    item { TypingIndicator() }
                }
            }

            // Error banner
            errorMessage?.let { error ->
                Text(
                    text = error,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                )
            }

            HorizontalDivider()

            // Input bar
            InputBar(
                text = inputText,
                onTextChange = { inputText = it },
                canSend = inputText.isNotBlank() && !isLoading,
                onSend = {
                    val text = inputText.trim()
                    inputText = ""
                    coroutineScope.launch { chatbotService.sendMessage(text) }
                }
            )
        }
    }
}

@Composable
private fun EmptyState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 60.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "💬",
            style = MaterialTheme.typography.displayMedium
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "Ask me about your trades",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "I can explain trades, show performance charts,\nand answer questions about your portfolio.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
            modifier = Modifier.padding(horizontal = 40.dp)
        )
    }
}

@Composable
private fun ChatBubble(
    message: ChatMessage,
    onChartTap: (String) -> Unit
) {
    val isUser = message.role == ChatRole.USER

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
    ) {
        if (isUser) Spacer(modifier = Modifier.weight(0.2f))

        Column(
            modifier = Modifier
                .weight(0.8f, fill = false)
                .background(
                    color = if (isUser) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(16.dp)
                )
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
        ) {
            Text(
                text = message.content,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isUser) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onSurfaceVariant
            )

            // Inline chart image (Req 20.7)
            message.chartImageUrl?.let { url ->
                if (url.isNotBlank()) {
                    Spacer(modifier = Modifier.height(6.dp))
                    AsyncImage(
                        model = ImageRequest.Builder(LocalContext.current)
                            .data(url)
                            .crossfade(true)
                            .build(),
                        contentDescription = "Chart image. Tap to view full screen with data values.",
                        contentScale = ContentScale.Fit,
                        modifier = Modifier
                            .widthIn(max = 260.dp)
                            .heightIn(max = 180.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .clickable { onChartTap(url) }
                    )
                }
            }
        }

        if (!isUser) Spacer(modifier = Modifier.weight(0.2f))
    }
}

@Composable
private fun TypingIndicator() {
    val infiniteTransition = rememberInfiniteTransition(label = "typing")

    Row(
        modifier = Modifier
            .padding(horizontal = 12.dp)
            .background(
                MaterialTheme.colorScheme.surfaceVariant,
                RoundedCornerShape(16.dp)
            )
            .padding(horizontal = 16.dp, vertical = 12.dp)
            .semantics { contentDescription = "Assistant is typing" },
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        repeat(3) { index ->
            val alpha by infiniteTransition.animateFloat(
                initialValue = 0.3f,
                targetValue = 1.0f,
                animationSpec = infiniteRepeatable(
                    animation = tween(600, delayMillis = index * 200),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "dot$index"
            )
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(
                        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = alpha),
                        CircleShape
                    )
            )
        }
    }
}

@Composable
private fun InputBar(
    text: String,
    onTextChange: (String) -> Unit,
    canSend: Boolean,
    onSend: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text("Ask about your trades...") },
            shape = RoundedCornerShape(20.dp),
            maxLines = 4,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { if (canSend) onSend() })
        )

        IconButton(
            onClick = onSend,
            enabled = canSend,
            modifier = Modifier
                .size(40.dp)
                .background(
                    if (canSend) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f),
                    CircleShape
                )
        ) {
            Icon(
                Icons.Default.ArrowUpward,
                contentDescription = "Send message",
                tint = if (canSend) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f)
            )
        }
    }
}
