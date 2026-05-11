package com.lohitrade.data.api

import com.lohitrade.BuildConfig
import com.lohitrade.data.auth.KeystoreService
import com.lohitrade.data.models.RefreshTokenRequest
import com.lohitrade.data.models.TokenResponse
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Retrofit-based HTTP client with configurable base URL (Req 12.2).
 *
 * Includes:
 * - Bearer token injection via interceptor
 * - Automatic 401 → token refresh → retry
 * - Configurable base URL (BuildConfig or runtime override)
 */
class ApiClient(
    baseUrl: String = BuildConfig.API_BASE_URL,
    private val keystoreService: KeystoreService
) {
    private val isRefreshing = AtomicBoolean(false)

    /** Auth interceptor: attaches Bearer token to every request. */
    private val authInterceptor = Interceptor { chain ->
        val original = chain.request()
        val token = keystoreService.getAccessToken()
        val request = if (token != null) {
            original.newBuilder()
                .header("Authorization", "Bearer $token")
                .header("Content-Type", "application/json")
                .build()
        } else {
            original.newBuilder()
                .header("Content-Type", "application/json")
                .build()
        }
        chain.proceed(request)
    }

    /** Token refresh interceptor: on 401, refresh and retry once (Req 12.5). */
    private val tokenRefreshInterceptor = Interceptor { chain ->
        val request = chain.request()
        val response = chain.proceed(request)

        if (response.code == 401 && !isRefreshing.getAndSet(true)) {
            try {
                val refreshToken = keystoreService.getRefreshToken()
                if (refreshToken != null) {
                    // Build a direct refresh call (bypass interceptors to avoid loop)
                    val refreshBody = com.google.gson.Gson().toJson(
                        RefreshTokenRequest(refreshToken)
                    )
                    val refreshRequest = okhttp3.Request.Builder()
                        .url("${baseUrl.trimEnd('/')}/auth/refresh")
                        .post(
                            okhttp3.RequestBody.create(
                                okhttp3.MediaType.parse("application/json"),
                                refreshBody
                            )
                        )
                        .build()

                    val refreshResponse = chain.connection()?.let {
                        // Use a fresh OkHttp call for refresh
                        OkHttpClient().newCall(refreshRequest).execute()
                    }

                    if (refreshResponse != null && refreshResponse.isSuccessful) {
                        val body = refreshResponse.body?.string()
                        val tokens = com.google.gson.Gson().fromJson(body, TokenResponse::class.java)
                        keystoreService.saveAccessToken(tokens.accessToken)
                        keystoreService.saveRefreshToken(tokens.refreshToken)

                        // Retry original request with new token
                        response.close()
                        val newRequest = request.newBuilder()
                            .header("Authorization", "Bearer ${tokens.accessToken}")
                            .build()
                        return@Interceptor chain.proceed(newRequest)
                    }
                }
            } finally {
                isRefreshing.set(false)
            }
        }

        response
    }

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = if (BuildConfig.DEBUG) {
            HttpLoggingInterceptor.Level.BODY
        } else {
            HttpLoggingInterceptor.Level.NONE
        }
    }

    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(authInterceptor)
        .addInterceptor(tokenRefreshInterceptor)
        .addInterceptor(loggingInterceptor)
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val retrofit: Retrofit = Retrofit.Builder()
        .baseUrl(baseUrl.trimEnd('/') + "/")
        .client(okHttpClient)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    /** Create a Retrofit service interface. */
    fun <T> create(serviceClass: Class<T>): T = retrofit.create(serviceClass)

    val authApi: AuthApi = create(AuthApi::class.java)

    /**
     * Manually refresh the access token (Req 12.5).
     * Returns true on success.
     */
    suspend fun refreshTokenIfNeeded(): Boolean {
        val refreshToken = keystoreService.getRefreshToken() ?: return false
        return try {
            val response = authApi.refreshToken(RefreshTokenRequest(refreshToken))
            if (response.isSuccessful) {
                response.body()?.let { tokens ->
                    keystoreService.saveAccessToken(tokens.accessToken)
                    keystoreService.saveRefreshToken(tokens.refreshToken)
                    true
                } ?: false
            } else {
                false
            }
        } catch (e: Exception) {
            false
        }
    }
}
