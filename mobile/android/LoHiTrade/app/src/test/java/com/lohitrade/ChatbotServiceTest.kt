package com.lohitrade

import com.lohitrade.data.api.ChatbotApi
import com.lohitrade.data.chatbot.ChatbotService
import com.lohitrade.data.models.*
import io.mockk.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import retrofit2.Response

/**
 * Unit tests for ChatbotService (Req 18.1, 20.7).
 */
class ChatbotServiceTest {

    private lateinit var chatbotApi: ChatbotApi
    private lateinit var chatbotService: ChatbotService

    @Before
    fun setup() {
        chatbotApi = mockk()
        chatbotService = ChatbotService(chatbotApi)
    }

    // -- sendMessage --

    @Test
    fun `sendMessage appends user message optimistically and assistant response`() = runTest {
        val assistantMsg = ChatMessage(
            id = "msg-2",
            role = ChatRole.ASSISTANT,
            content = "Your win rate is 65%.",
            chartImageUrl = null,
            timestamp = "2024-01-15T10:30:05Z"
        )
        coEvery { chatbotApi.sendMessage(any()) } returns Response.success(
            ChatMessageResponse(message = assistantMsg)
        )

        chatbotService.sendMessage("What is my win rate?")

        val messages = chatbotService.messages.value
        assertEquals(2, messages.size)
        assertEquals(ChatRole.USER, messages[0].role)
        assertEquals("What is my win rate?", messages[0].content)
        assertEquals(ChatRole.ASSISTANT, messages[1].role)
        assertEquals("Your win rate is 65%.", messages[1].content)
        assertFalse(chatbotService.isLoading.value)
        assertNull(chatbotService.errorMessage.value)
    }

    @Test
    fun `sendMessage with chart image URL in response`() = runTest {
        val assistantMsg = ChatMessage(
            id = "msg-chart",
            role = ChatRole.ASSISTANT,
            content = "Here is your equity curve.",
            chartImageUrl = "https://api.lohitrade.com/charts/equity-123.png",
            timestamp = "2024-01-15T10:30:05Z"
        )
        coEvery { chatbotApi.sendMessage(any()) } returns Response.success(
            ChatMessageResponse(message = assistantMsg)
        )

        chatbotService.sendMessage("Show my performance")

        val messages = chatbotService.messages.value
        assertEquals(2, messages.size)
        assertEquals("https://api.lohitrade.com/charts/equity-123.png", messages[1].chartImageUrl)
    }

    @Test
    fun `sendMessage ignores blank input`() = runTest {
        chatbotService.sendMessage("   ")

        assertTrue(chatbotService.messages.value.isEmpty())
        coVerify(exactly = 0) { chatbotApi.sendMessage(any()) }
    }

    @Test
    fun `sendMessage sets error on API failure`() = runTest {
        coEvery { chatbotApi.sendMessage(any()) } throws RuntimeException("Network error")

        chatbotService.sendMessage("Hello")

        // User message still appended optimistically
        assertEquals(1, chatbotService.messages.value.size)
        assertEquals(ChatRole.USER, chatbotService.messages.value[0].role)
        assertNotNull(chatbotService.errorMessage.value)
        assertFalse(chatbotService.isLoading.value)
    }

    @Test
    fun `sendMessage sets error on non-successful response`() = runTest {
        coEvery { chatbotApi.sendMessage(any()) } returns Response.error(
            500,
            okhttp3.ResponseBody.create(
                okhttp3.MediaType.parse("application/json"),
                "{\"error\":\"Internal server error\"}"
            )
        )

        chatbotService.sendMessage("Hello")

        assertEquals(1, chatbotService.messages.value.size)
        assertNotNull(chatbotService.errorMessage.value)
        assertTrue(chatbotService.errorMessage.value!!.contains("500"))
    }

    // -- fetchHistory --

    @Test
    fun `fetchHistory populates messages from server`() = runTest {
        val history = listOf(
            ChatMessage("msg-1", ChatRole.USER, "Hello", null, "2024-01-15T10:00:00Z"),
            ChatMessage("msg-2", ChatRole.ASSISTANT, "Hi there!", null, "2024-01-15T10:00:03Z")
        )
        coEvery { chatbotApi.getHistory() } returns Response.success(
            ChatHistoryResponse(messages = history)
        )

        chatbotService.fetchHistory()

        assertEquals(2, chatbotService.messages.value.size)
        assertEquals("Hello", chatbotService.messages.value[0].content)
        assertEquals("Hi there!", chatbotService.messages.value[1].content)
        assertFalse(chatbotService.isLoading.value)
    }

    @Test
    fun `fetchHistory sets error on exception`() = runTest {
        coEvery { chatbotApi.getHistory() } throws RuntimeException("Timeout")

        chatbotService.fetchHistory()

        assertNotNull(chatbotService.errorMessage.value)
        assertFalse(chatbotService.isLoading.value)
    }

    // -- clearSession --

    @Test
    fun `clearSession clears local messages on success`() = runTest {
        // Pre-populate messages
        val assistantMsg = ChatMessage("msg-1", ChatRole.ASSISTANT, "Hi", null, "2024-01-15T10:00:00Z")
        coEvery { chatbotApi.sendMessage(any()) } returns Response.success(
            ChatMessageResponse(message = assistantMsg)
        )
        chatbotService.sendMessage("Hello")
        assertEquals(2, chatbotService.messages.value.size)

        // Clear session
        coEvery { chatbotApi.clearSession() } returns Response.success(
            ChatSessionDeleteResponse(success = true, message = "Session cleared")
        )

        chatbotService.clearSession()

        assertTrue(chatbotService.messages.value.isEmpty())
        assertNull(chatbotService.errorMessage.value)
    }

    @Test
    fun `clearSession sets error on failure`() = runTest {
        coEvery { chatbotApi.clearSession() } throws RuntimeException("Network error")

        chatbotService.clearSession()

        assertNotNull(chatbotService.errorMessage.value)
    }

    @Test
    fun `clearSession does not clear messages on non-successful response`() = runTest {
        // Pre-populate
        val assistantMsg = ChatMessage("msg-1", ChatRole.ASSISTANT, "Hi", null, "2024-01-15T10:00:00Z")
        coEvery { chatbotApi.sendMessage(any()) } returns Response.success(
            ChatMessageResponse(message = assistantMsg)
        )
        chatbotService.sendMessage("Hello")
        val countBefore = chatbotService.messages.value.size

        coEvery { chatbotApi.clearSession() } returns Response.error(
            500,
            okhttp3.ResponseBody.create(
                okhttp3.MediaType.parse("application/json"),
                "{\"error\":\"fail\"}"
            )
        )

        chatbotService.clearSession()

        assertEquals(countBefore, chatbotService.messages.value.size)
        assertNotNull(chatbotService.errorMessage.value)
    }

    // -- ChatModels --

    @Test
    fun `ChatMessage data class equality`() {
        val msg1 = ChatMessage("id-1", ChatRole.USER, "Hello", null, "2024-01-15T10:00:00Z")
        val msg2 = ChatMessage("id-1", ChatRole.USER, "Hello", null, "2024-01-15T10:00:00Z")
        assertEquals(msg1, msg2)
    }

    @Test
    fun `ChatRole enum values`() {
        assertEquals(2, ChatRole.entries.size)
        assertTrue(ChatRole.entries.contains(ChatRole.USER))
        assertTrue(ChatRole.entries.contains(ChatRole.ASSISTANT))
    }

    @Test
    fun `ChatMessage with and without chart URL`() {
        val withChart = ChatMessage("id-1", ChatRole.ASSISTANT, "Chart", "https://example.com/chart.png", "ts")
        val withoutChart = ChatMessage("id-2", ChatRole.ASSISTANT, "Text only", null, "ts")

        assertNotNull(withChart.chartImageUrl)
        assertNull(withoutChart.chartImageUrl)
    }
}
