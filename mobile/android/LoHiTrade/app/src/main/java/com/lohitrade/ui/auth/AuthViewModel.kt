package com.lohitrade.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.lohitrade.data.auth.AuthService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel for auth state management in Compose screens.
 *
 * Wraps AuthService and exposes UI state for login/register flows.
 * In a full Hilt setup, annotate with @HiltViewModel and @Inject constructor.
 */
class AuthViewModel(
    private val authService: AuthService
) : ViewModel() {

    val isAuthenticated: StateFlow<Boolean> = authService.isAuthenticated
    val isLoading: StateFlow<Boolean> = authService.isLoading
    val errorMessage: StateFlow<String?> = authService.errorMessage

    // -- Form state --

    private val _email = MutableStateFlow("")
    val email: StateFlow<String> = _email.asStateFlow()

    private val _password = MutableStateFlow("")
    val password: StateFlow<String> = _password.asStateFlow()

    fun updateEmail(value: String) { _email.value = value }
    fun updatePassword(value: String) { _password.value = value }

    // -- Actions --

    fun login() {
        viewModelScope.launch {
            authService.login(_email.value, _password.value)
        }
    }

    fun register(name: String, phone: String) {
        viewModelScope.launch {
            authService.register(_email.value, _password.value, phone, name)
        }
    }

    fun loginWithGoogle(idToken: String) {
        viewModelScope.launch {
            authService.loginWithGoogle(idToken)
        }
    }

    fun loginWithApple(authCode: String, userName: String?) {
        viewModelScope.launch {
            authService.loginWithApple(authCode, userName)
        }
    }

    fun logout() {
        viewModelScope.launch {
            authService.logout()
        }
    }
}
