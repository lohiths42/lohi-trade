package com.lohitrade.data.models

import com.google.gson.annotations.SerializedName

/**
 * Data models for the AI chatbot (Req 18.1, 20.7).
 */

/** Role of a chat message participant. */
enum class ChatRole {
    @SerializedName("user") USER,
    @SerializedName("assistant") ASSISTANT
}

/** A single chat message with optional chart image URL. */
data class ChatMessage(
    val id: String,
    val role: ChatRole,
    val content: String,
    @SerializedName("chart_image_url") val chartImageUrl: String? = null,
    val timestamp: String
)

/** Request body for POST /chatbot/message. */
data class ChatMessageRequest(
    val message: String
)

/** Response from POST /chatbot/message. */
data class ChatMessageResponse(
    val message: ChatMessage
)

/** Response from GET /chatbot/history. */
data class ChatHistoryResponse(
    val messages: List<ChatMessage>
)

/** Response from DELETE /chatbot/session. */
data class ChatSessionDeleteResponse(
    val success: Boolean,
    val message: String
)
