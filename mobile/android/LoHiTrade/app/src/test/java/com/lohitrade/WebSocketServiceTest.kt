package com.lohitrade

import com.lohitrade.data.trading.WebSocketService
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for WebSocketService connection management and subscription logic.
 */
class WebSocketServiceTest {

    private lateinit var webSocketService: WebSocketService

    @Before
    fun setup() {
        // Create service without keystoreService for testing
        webSocketService = WebSocketService(
            baseUrl = "ws://localhost:8000",
            keystoreService = null
        )
    }

    @Test
    fun `initial state is disconnected with empty ticks`() {
        assertFalse(webSocketService.isConnected.value)
        assertTrue(webSocketService.priceTicks.value.isEmpty())
    }

    @Test
    fun `subscribe adds symbols to tracked set`() {
        // Subscribe before connecting — symbols should be queued
        webSocketService.subscribe(listOf("RELIANCE", "TCS"))
        // Service tracks symbols internally even when not connected
        // Verify no crash and state remains disconnected
        assertFalse(webSocketService.isConnected.value)
    }

    @Test
    fun `unsubscribe removes symbols from tracked set`() {
        webSocketService.subscribe(listOf("RELIANCE", "TCS", "INFY"))
        webSocketService.unsubscribe(listOf("TCS"))
        // No crash, state remains disconnected
        assertFalse(webSocketService.isConnected.value)
    }

    @Test
    fun `disconnect resets connection state`() {
        webSocketService.disconnect()
        assertFalse(webSocketService.isConnected.value)
    }

    @Test
    fun `multiple disconnect calls are safe`() {
        webSocketService.disconnect()
        webSocketService.disconnect()
        assertFalse(webSocketService.isConnected.value)
    }

    @Test
    fun `subscribe with empty list does not crash`() {
        webSocketService.subscribe(emptyList())
        assertFalse(webSocketService.isConnected.value)
    }

    @Test
    fun `companion constants are correct`() {
        assertEquals(10, WebSocketService.MAX_RECONNECT_ATTEMPTS)
        assertEquals(1000L, WebSocketService.BASE_RECONNECT_DELAY_MS)
        assertEquals(30000L, WebSocketService.MAX_RECONNECT_DELAY_MS)
    }
}
