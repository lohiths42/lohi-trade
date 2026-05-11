package com.lohitrade.data.auth

import android.util.Base64
import com.lohitrade.data.api.ApiClient
import com.lohitrade.data.models.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

/**
 * Main authentication service orchestrating JWT auth, biometric login,
 * token storage, and automatic refresh (Req 12.2, 12.3, 12.4, 12.5).
 */
class AuthService(
    private val apiClient: ApiClient,
    private val keystoreService: KeystoreService,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
) {
    private val _isAuthenticated = MutableStateFlow(false)
    val isAuthenticated: StateFlow<Boolean> = _isAuthenticated.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    private var refreshJob: Job? = null

    init {
        // Check for existing valid tokens on launch
        val token = keystoreService.getAccessToken()
        if (token != null) {
            val payload = JWTDecoder.decode(token)
            if (payload != null && !payload.isExpired) {
                _isAuthenticated.value = true
                scheduleTokenRefresh(payload)
            } else if (keystoreService.getRefreshToken() != null) {
                // Access token expired but refresh token exists — try refresh
                scope.launch { attemptSilentRefresh() }
            }
        }
    }

    // -- Email/password login (Req 12.2) --

    suspend fun login(email: String, password: String) {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val response = apiClient.authApi.login(LoginRequest(email, password))
            if (response.isSuccessful) {
                response.body()?.let { storeTokens(it) }
                _isAuthenticated.value = true
            } else {
                _errorMessage.value = parseError(response)
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Login failed"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Registration --

    suspend fun register(email: String, password: String, phone: String, name: String) {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val response = apiClient.authApi.register(
                RegisterRequest(email, password, phone, name)
            )
            if (response.isSuccessful) {
                // After registration, auto-login
                login(email, password)
            } else {
                _errorMessage.value = parseError(response)
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Registration failed"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Social login (Google) --

    suspend fun loginWithGoogle(idToken: String) {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val response = apiClient.authApi.loginWithGoogle(GoogleLoginRequest(idToken))
            if (response.isSuccessful) {
                response.body()?.let { storeTokens(it) }
                _isAuthenticated.value = true
            } else {
                _errorMessage.value = parseError(response)
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Google login failed"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Social login (Apple) --

    suspend fun loginWithApple(authCode: String, userName: String? = null) {
        _isLoading.value = true
        _errorMessage.value = null
        try {
            val response = apiClient.authApi.loginWithApple(
                AppleLoginRequest(authCode, userName)
            )
            if (response.isSuccessful) {
                response.body()?.let { storeTokens(it) }
                _isAuthenticated.value = true
            } else {
                _errorMessage.value = parseError(response)
            }
        } catch (e: Exception) {
            _errorMessage.value = e.localizedMessage ?: "Apple login failed"
        } finally {
            _isLoading.value = false
        }
    }

    // -- Logout --

    suspend fun logout() {
        refreshJob?.cancel()
        refreshJob = null
        try {
            apiClient.authApi.logout()
        } catch (_: Exception) {
            // Best-effort server logout
        }
        keystoreService.deleteAll()
        _isAuthenticated.value = false
        _errorMessage.value = null
    }

    // -- Token management (Req 12.4, 12.5) --

    private fun storeTokens(response: TokenResponse) {
        keystoreService.saveTokens(response.accessToken, response.refreshToken)
        JWTDecoder.decode(response.accessToken)?.let { scheduleTokenRefresh(it) }
    }

    /**
     * Schedule a coroutine to refresh the access token 60 seconds before expiry.
     */
    private fun scheduleTokenRefresh(payload: JWTPayload) {
        refreshJob?.cancel()
        val refreshIn = maxOf(payload.secondsUntilExpiry - 60, 1L)
        refreshJob = scope.launch {
            delay(refreshIn * 1000)
            attemptSilentRefresh()
        }
    }

    /**
     * Silently refresh the access token using the stored refresh token.
     */
    private suspend fun attemptSilentRefresh() {
        val success = apiClient.refreshTokenIfNeeded()
        if (success) {
            val token = keystoreService.getAccessToken()
            val payload = token?.let { JWTDecoder.decode(it) }
            if (payload != null && !payload.isExpired) {
                _isAuthenticated.value = true
                scheduleTokenRefresh(payload)
            } else {
                _isAuthenticated.value = false
            }
        } else {
            _isAuthenticated.value = false
        }
    }

    /** Parse error body from a failed response. */
    private fun <T> parseError(response: retrofit2.Response<T>): String {
        return try {
            val errorBody = response.errorBody()?.string()
            if (errorBody != null) {
                val json = JSONObject(errorBody)
                json.optString("detail", "Request failed (${response.code()})")
            } else {
                "Request failed (${response.code()})"
            }
        } catch (_: Exception) {
            "Request failed (${response.code()})"
        }
    }
}

// -- JWT Decoder (local, no verification — server is source of truth) --

object JWTDecoder {
    /**
     * Decode a JWT token's payload without signature verification.
     * Used only for reading expiry locally; the server validates signatures.
     */
    fun decode(token: String): JWTPayload? {
        val parts = token.split(".")
        if (parts.size != 3) return null

        return try {
            val payloadBytes = Base64.decode(
                parts[1].replace("-", "+").replace("_", "/"),
                Base64.DEFAULT
            )
            val json = JSONObject(String(payloadBytes, Charsets.UTF_8))

            JWTPayload(
                sub = json.getString("sub"),
                email = json.optString("email", ""),
                role = json.optString("role", "TRADER"),
                type = json.optString("type", "access"),
                iat = json.getLong("iat"),
                exp = json.getLong("exp")
            )
        } catch (_: Exception) {
            null
        }
    }
}
