package com.lohitrade.data.models

import com.google.gson.annotations.SerializedName

// -- Request models --

data class LoginRequest(
    val email: String,
    val password: String
)

data class RegisterRequest(
    val email: String,
    val password: String,
    val phone: String,
    val name: String
)

data class GoogleLoginRequest(
    @SerializedName("id_token") val idToken: String
)

data class AppleLoginRequest(
    @SerializedName("auth_code") val authCode: String,
    @SerializedName("user_name") val userName: String? = null
)

data class RefreshTokenRequest(
    @SerializedName("refresh_token") val refreshToken: String
)

data class FCMTokenRequest(
    @SerializedName("fcm_token") val fcmToken: String
)

// -- Response models --

data class TokenResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("token_type") val tokenType: String
)

data class RegisterResponse(
    @SerializedName("user_id") val userId: String,
    val email: String,
    val message: String
)

data class ErrorResponse(
    val detail: String
)

// -- JWT payload (decoded locally for expiry checks) --

data class JWTPayload(
    val sub: String,
    val email: String,
    val role: String,
    val type: String,
    val iat: Long,
    val exp: Long
) {
    /** Seconds remaining until token expires. */
    val secondsUntilExpiry: Long
        get() = exp - (System.currentTimeMillis() / 1000)

    /** Whether the token has expired. */
    val isExpired: Boolean
        get() = secondsUntilExpiry <= 0

    /** Whether the token will expire within the given threshold (default 60s). */
    fun expiresWithin(seconds: Long = 60): Boolean = secondsUntilExpiry < seconds
}
