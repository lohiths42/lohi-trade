package com.lohitrade.data.api

import com.lohitrade.data.models.*
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST

/**
 * Auth API interface for the FastAPI backend (Req 12.2).
 *
 * Endpoints mirror the backend auth_v2 router:
 * login, register, google, apple, refresh, logout.
 */
interface AuthApi {

    @POST("/auth/login")
    suspend fun login(@Body request: LoginRequest): Response<TokenResponse>

    @POST("/auth/register")
    suspend fun register(@Body request: RegisterRequest): Response<RegisterResponse>

    @POST("/auth/google")
    suspend fun loginWithGoogle(@Body request: GoogleLoginRequest): Response<TokenResponse>

    @POST("/auth/apple")
    suspend fun loginWithApple(@Body request: AppleLoginRequest): Response<TokenResponse>

    @POST("/auth/refresh")
    suspend fun refreshToken(@Body request: RefreshTokenRequest): Response<TokenResponse>

    @POST("/auth/logout")
    suspend fun logout(): Response<Unit>

    @POST("/users/fcm-token")
    suspend fun registerFCMToken(@Body request: FCMTokenRequest): Response<Unit>
}
