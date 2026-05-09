package com.lohitrade.data.chatbot

import com.lohitrade.data.api.ChatbotApi
import com.lohitrade.data.models.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Service layer for the AI chatbot (Req 18.1, 20.7).
 *
 * Sends messages to POST /chatbot/message, receives responses with
 * text and optional chart image URLs, maintains conversation history
 * per session, and supports clearing via DELETE /chatbot/session.
 */
class ChatbotService(private val chatbotApi: ChatbotApi) {

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    /**
     * Send a user message and append both the user message (optimistically)
     * and the assistant response to the conversation.
     */
    suspend fun sendMessage(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return

        // Optimistic user message
        val userMessage = ChatMessage(
            id = "local-${System.currentTimeMillis()}",
            role = ChatRole.USER,
            content = trimmed,
            chartImageUrl = null,
            timestamp = java.time.Instant.now().toString()
        )
        _messages.value = _messages.value + userMessage

        _isLoading.value = true
        _errorMessage.value = null
        try {
            val response = chatbotApi.sendMessage(ChatMessageRequest(trimmed))
            if (response.isSuccessful) {
                response.body()?.let { chatResponse ->
                    _messages.value = _messages.value + chatResponse.message
                }
            } else {
                _errorMessage.value = "Failed to get response (${response.code()})"
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to send message"
        } finally {
            _isLoading.value = false
        }
    }

    /** Load conversation history for the current session. */
    suspend fun fetchHistory() {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val response = chatbotApi.getHistory()
            if (response.isSuccessful) {
                _messages.value = response.body()?.messages ?: emptyList()
            } else {
                _errorMessage.value = "Failed to load history (${response.code()})"
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to load history"
        } finally {
            _isLoading.value = false
        }
    }

    /** Delete the current chatbot session and clear local messages. */
    suspend fun clearSession() {
        _errorMessage.value = null
        try {
            val response = chatbotApi.clearSession()
            if (response.isSuccessful) {
                _messages.value = emptyList()
            } else {
                _errorMessage.value = "Failed to clear session (${response.code()})"
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Failed to clear session"
        }
    }
}
