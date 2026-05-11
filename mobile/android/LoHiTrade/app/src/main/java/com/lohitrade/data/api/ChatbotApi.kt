package com.lohitrade.data.api

import com.lohitrade.data.models.*
import retrofit2.Response
import retrofit2.http.*

/**
 * Retrofit interface for the AI chatbot endpoints (Req 18.1, 20.7).
 */
interface ChatbotApi {

    /** Send a user message and receive the assistant response. */
    @POST("/chatbot/message")
    suspend fun sendMessage(@Body request: ChatMessageRequest): Response<ChatMessageResponse>

    /** Load conversation history for the current session. */
    @GET("/chatbot/history")
    suspend fun getHistory(): Response<ChatHistoryResponse>

    /** Delete the current chatbot session. */
    @DELETE("/chatbot/session")
    suspend fun clearSession(): Response<ChatSessionDeleteResponse>
}
