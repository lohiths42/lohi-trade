package com.lohitrade.data.auth

import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * Biometric authentication (fingerprint/face unlock) as secondary login (Req 12.3).
 *
 * After initial JWT authentication, users can enable biometric unlock so
 * subsequent app opens skip the password prompt and use the stored tokens.
 */
class BiometricService {

    /** Result of a biometric authentication attempt. */
    sealed class AuthResult {
        data object Success : AuthResult()
        data class Failure(val errorMessage: String) : AuthResult()
        data object NotAvailable : AuthResult()
        data object Cancelled : AuthResult()
    }

    /** The type of biometric available on this device. */
    enum class BiometricType {
        NONE,
        FINGERPRINT,
        FACE,
        IRIS
    }

    /**
     * Check whether biometric authentication is available on this device.
     */
    fun isBiometricAvailable(activity: FragmentActivity): Boolean {
        val biometricManager = BiometricManager.from(activity)
        return biometricManager.canAuthenticate(
            BiometricManager.Authenticators.BIOMETRIC_STRONG
        ) == BiometricManager.BIOMETRIC_SUCCESS
    }

    /**
     * Determine the type of biometric available.
     */
    fun availableBiometricType(activity: FragmentActivity): BiometricType {
        val biometricManager = BiometricManager.from(activity)
        val canAuth = biometricManager.canAuthenticate(
            BiometricManager.Authenticators.BIOMETRIC_STRONG
        )
        return if (canAuth == BiometricManager.BIOMETRIC_SUCCESS) {
            // Android doesn't expose the specific type easily;
            // we report FINGERPRINT as the most common default.
            BiometricType.FINGERPRINT
        } else {
            BiometricType.NONE
        }
    }

    /**
     * Prompt the user for biometric authentication.
     * Suspends until the user completes or cancels the prompt.
     */
    suspend fun authenticate(
        activity: FragmentActivity,
        title: String = "Unlock LoHi-TRADE",
        subtitle: String = "Use your fingerprint or face to log in",
        negativeButtonText: String = "Cancel"
    ): AuthResult {
        if (!isBiometricAvailable(activity)) {
            return AuthResult.NotAvailable
        }

        return suspendCancellableCoroutine { continuation ->
            val executor = ContextCompat.getMainExecutor(activity)

            val callback = object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    if (continuation.isActive) {
                        continuation.resume(AuthResult.Success)
                    }
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    if (continuation.isActive) {
                        val result = when (errorCode) {
                            BiometricPrompt.ERROR_USER_CANCELED,
                            BiometricPrompt.ERROR_NEGATIVE_BUTTON,
                            BiometricPrompt.ERROR_CANCELED -> AuthResult.Cancelled
                            else -> AuthResult.Failure(errString.toString())
                        }
                        continuation.resume(result)
                    }
                }

                override fun onAuthenticationFailed() {
                    // Called on each failed attempt; the prompt stays open.
                    // We don't resume here — the system handles retries.
                }
            }

            val prompt = BiometricPrompt(activity, executor, callback)

            val promptInfo = BiometricPrompt.PromptInfo.Builder()
                .setTitle(title)
                .setSubtitle(subtitle)
                .setNegativeButtonText(negativeButtonText)
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .build()

            prompt.authenticate(promptInfo)

            continuation.invokeOnCancellation {
                prompt.cancelAuthentication()
            }
        }
    }
}
