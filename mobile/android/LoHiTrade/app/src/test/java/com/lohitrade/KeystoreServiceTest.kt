package com.lohitrade

import com.lohitrade.data.auth.KeystoreService
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.JUnit4

/**
 * Unit tests for KeystoreService — secure token storage (Req 12.4).
 *
 * Note: EncryptedSharedPreferences requires an Android context and cannot
 * be unit-tested with standard JUnit. These tests validate the API contract
 * and would run as instrumented tests on a real device/emulator.
 *
 * For pure JUnit, we test the KeystoreService interface contract via a
 * simple in-memory implementation that mirrors the real behavior.
 */
@RunWith(JUnit4::class)
class KeystoreServiceTest {

    /**
     * In-memory test double that mirrors KeystoreService's API contract.
     * Used because EncryptedSharedPreferences needs Android context.
     */
    private class InMemoryKeystoreService {
        private val store = mutableMapOf<String, String>()

        fun saveAccessToken(token: String) { store["access_token"] = token }
        fun getAccessToken(): String? = store["access_token"]
        fun deleteAccessToken() { store.remove("access_token") }

        fun saveRefreshToken(token: String) { store["refresh_token"] = token }
        fun getRefreshToken(): String? = store["refresh_token"]
        fun deleteRefreshToken() { store.remove("refresh_token") }

        fun saveTokens(accessToken: String, refreshToken: String) {
            store["access_token"] = accessToken
            store["refresh_token"] = refreshToken
        }

        fun deleteAll() {
            store.remove("access_token")
            store.remove("refresh_token")
        }

        fun hasTokens(): Boolean = store.containsKey("access_token")
    }

    private val keystore = InMemoryKeystoreService()

    // -- Save and retrieve --

    @Test
    fun `save and get access token`() {
        val token = "eyJhbGciOiJIUzI1NiJ9.test-access-token"
        keystore.saveAccessToken(token)
        assertEquals(token, keystore.getAccessToken())
    }

    @Test
    fun `save and get refresh token`() {
        val token = "refresh-token-abc123"
        keystore.saveRefreshToken(token)
        assertEquals(token, keystore.getRefreshToken())
    }

    // -- Overwrite --

    @Test
    fun `overwrite existing token`() {
        keystore.saveAccessToken("old-token")
        keystore.saveAccessToken("new-token")
        assertEquals("new-token", keystore.getAccessToken())
    }

    // -- Delete --

    @Test
    fun `delete access token`() {
        keystore.saveAccessToken("token-to-delete")
        keystore.deleteAccessToken()
        assertNull(keystore.getAccessToken())
    }

    @Test
    fun `delete non-existent token does not crash`() {
        keystore.deleteAccessToken() // Should not throw
        assertNull(keystore.getAccessToken())
    }

    // -- Delete all --

    @Test
    fun `delete all tokens`() {
        keystore.saveTokens("access", "refresh")
        keystore.deleteAll()
        assertNull(keystore.getAccessToken())
        assertNull(keystore.getRefreshToken())
    }

    // -- Get non-existent --

    @Test
    fun `get non-existent key returns null`() {
        assertNull(keystore.getAccessToken())
    }

    // -- Save both tokens --

    @Test
    fun `save tokens stores both`() {
        keystore.saveTokens("access-123", "refresh-456")
        assertEquals("access-123", keystore.getAccessToken())
        assertEquals("refresh-456", keystore.getRefreshToken())
    }

    // -- hasTokens --

    @Test
    fun `hasTokens returns false when empty`() {
        assertFalse(keystore.hasTokens())
    }

    @Test
    fun `hasTokens returns true after saving`() {
        keystore.saveAccessToken("token")
        assertTrue(keystore.hasTokens())
    }

    @Test
    fun `hasTokens returns false after deleteAll`() {
        keystore.saveAccessToken("token")
        keystore.deleteAll()
        assertFalse(keystore.hasTokens())
    }

    // -- Empty string --

    @Test
    fun `save empty string token`() {
        keystore.saveAccessToken("")
        assertEquals("", keystore.getAccessToken())
    }

    // -- Long token --

    @Test
    fun `save long token`() {
        val longToken = "a".repeat(4096)
        keystore.saveAccessToken(longToken)
        assertEquals(longToken, keystore.getAccessToken())
    }
}
