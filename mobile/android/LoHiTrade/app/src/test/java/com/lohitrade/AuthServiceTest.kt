package com.lohitrade

import android.util.Base64
import com.lohitrade.data.auth.JWTDecoder
import com.lohitrade.data.models.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.JUnit4

/**
 * Unit tests for AuthService — JWT decoding, token lifecycle, and model serialization.
 */
@RunWith(JUnit4::class)
class AuthServiceTest {

    // -- JWTPayload expiry logic --

    @Test
    fun `payload is expired when exp is in the past`() {
        val payload = JWTPayload(
            sub = "user-1", email = "a@b.com", role = "TRADER",
            type = "access", iat = 1000, exp = 1001
        )
        assertTrue("Token from the past should be expired", payload.isExpired)
    }

    @Test
    fun `payload is not expired when exp is in the future`() {
        val futureExp = (System.currentTimeMillis() / 1000) + 3600
        val payload = JWTPayload(
            sub = "user-1", email = "a@b.com", role = "TRADER",
            type = "access", iat = 1000, exp = futureExp
        )
        assertFalse("Token expiring in 1 hour should not be expired", payload.isExpired)
    }

    @Test
    fun `payload expiresWithin threshold`() {
        val soonExp = (System.currentTimeMillis() / 1000) + 30
        val payload = JWTPayload(
            sub = "user-1", email = "a@b.com", role = "TRADER",
            type = "access", iat = 1000, exp = soonExp
        )
        assertTrue("Should be expiring within 60s", payload.expiresWithin(60))
        assertFalse("Should not be expiring within 10s", payload.expiresWithin(10))
    }

    @Test
    fun `secondsUntilExpiry is positive for future token`() {
        val futureExp = (System.currentTimeMillis() / 1000) + 900
        val payload = JWTPayload(
            sub = "user-1", email = "a@b.com", role = "TRADER",
            type = "access", iat = 1000, exp = futureExp
        )
        assertTrue("Seconds until expiry should be positive", payload.secondsUntilExpiry > 0)
    }

    @Test
    fun `secondsUntilExpiry is negative for expired token`() {
        val payload = JWTPayload(
            sub = "user-1", email = "a@b.com", role = "TRADER",
            type = "access", iat = 1000, exp = 1001
        )
        assertTrue("Seconds until expiry should be negative", payload.secondsUntilExpiry < 0)
    }

    // -- TokenResponse model --

    @Test
    fun `TokenResponse holds correct values`() {
        val response = TokenResponse(
            accessToken = "abc123",
            refreshToken = "def456",
            tokenType = "bearer"
        )
        assertEquals("abc123", response.accessToken)
        assertEquals("def456", response.refreshToken)
        assertEquals("bearer", response.tokenType)
    }

    // -- RegisterResponse model --

    @Test
    fun `RegisterResponse holds correct values`() {
        val response = RegisterResponse(
            userId = "uuid-123",
            email = "test@example.com",
            message = "Registration successful"
        )
        assertEquals("uuid-123", response.userId)
        assertEquals("test@example.com", response.email)
    }

    // -- Request model construction --

    @Test
    fun `LoginRequest holds correct values`() {
        val request = LoginRequest(email = "test@example.com", password = "Pass123!")
        assertEquals("test@example.com", request.email)
        assertEquals("Pass123!", request.password)
    }

    @Test
    fun `RefreshTokenRequest holds correct values`() {
        val request = RefreshTokenRequest(refreshToken = "my-refresh-token")
        assertEquals("my-refresh-token", request.refreshToken)
    }

    @Test
    fun `GoogleLoginRequest holds correct values`() {
        val request = GoogleLoginRequest(idToken = "google-id-token-xyz")
        assertEquals("google-id-token-xyz", request.idToken)
    }

    @Test
    fun `AppleLoginRequest with userName`() {
        val request = AppleLoginRequest(authCode = "apple-auth-code", userName = "John Doe")
        assertEquals("apple-auth-code", request.authCode)
        assertEquals("John Doe", request.userName)
    }

    @Test
    fun `AppleLoginRequest with null userName`() {
        val request = AppleLoginRequest(authCode = "code", userName = null)
        assertEquals("code", request.authCode)
        assertNull(request.userName)
    }

    // -- FCMTokenRequest --

    @Test
    fun `FCMTokenRequest holds correct value`() {
        val request = FCMTokenRequest(fcmToken = "fcm-token-abc")
        assertEquals("fcm-token-abc", request.fcmToken)
    }

    // -- ErrorResponse --

    @Test
    fun `ErrorResponse holds detail`() {
        val response = ErrorResponse(detail = "Invalid credentials")
        assertEquals("Invalid credentials", response.detail)
    }
}
