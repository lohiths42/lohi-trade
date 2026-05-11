package com.lohitrade.ui.auth

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import com.lohitrade.data.auth.AuthService
import com.lohitrade.data.auth.BiometricService
import kotlinx.coroutines.launch

/**
 * Login screen with email, Google, and biometric sign-in options (Req 12.2, 12.3).
 *
 * Social login buttons are prominently placed for faster onboarding (Req 32.8).
 */
@Composable
fun LoginScreen(
    authService: AuthService,
    biometricService: BiometricService,
    activity: FragmentActivity
) {
    val isLoading by authService.isLoading.collectAsState()
    val errorMessage by authService.errorMessage.collectAsState()
    val scope = rememberCoroutineScope()

    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showRegister by remember { mutableStateOf(false) }

    if (showRegister) {
        RegisterScreen(
            authService = authService,
            onBack = { showRegister = false }
        )
        return
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(modifier = Modifier.weight(1f))

        // Logo / title
        Text(
            text = "LoHi-TRADE",
            style = MaterialTheme.typography.headlineLarge
        )
        Text(
            text = "Algorithmic Trading Platform",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(48.dp))

        // Social login buttons (prominently placed)
        OutlinedButton(
            onClick = {
                // Google Sign-In SDK integration point
                // In production: launch Google sign-in intent, get idToken, call authService.loginWithGoogle()
            },
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp)
        ) {
            Text("Continue with Google")
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Divider
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            HorizontalDivider(modifier = Modifier.weight(1f))
            Text(
                text = "  or  ",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            HorizontalDivider(modifier = Modifier.weight(1f))
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Email field
        OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            label = { Text("Email") },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Email,
                imeAction = ImeAction.Next
            ),
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(8.dp))

        // Password field
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("Password") },
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Password,
                imeAction = ImeAction.Done
            ),
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(16.dp))

        // Sign In button
        Button(
            onClick = {
                scope.launch { authService.login(email, password) }
            },
            enabled = email.isNotBlank() && password.isNotBlank() && !isLoading,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp)
        ) {
            if (isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(24.dp),
                    color = MaterialTheme.colorScheme.onPrimary
                )
            } else {
                Text("Sign In")
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Biometric login button (Req 12.3)
        if (biometricService.isBiometricAvailable(activity)) {
            TextButton(
                onClick = {
                    scope.launch {
                        val result = biometricService.authenticate(activity)
                        if (result is BiometricService.AuthResult.Success) {
                            // Biometric passed — check if we have valid tokens
                            // AuthService init already checks tokens on launch
                        }
                    }
                }
            ) {
                Icon(
                    imageVector = Icons.Default.Fingerprint,
                    contentDescription = "Biometric login",
                    modifier = Modifier.size(20.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("Unlock with Biometric")
            }
        }

        // Error message
        if (errorMessage != null) {
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = errorMessage!!,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall
            )
        }

        Spacer(modifier = Modifier.weight(1f))

        // Register link
        TextButton(onClick = { showRegister = true }) {
            Text("Don't have an account? Sign Up")
        }

        Spacer(modifier = Modifier.height(16.dp))
    }
}
