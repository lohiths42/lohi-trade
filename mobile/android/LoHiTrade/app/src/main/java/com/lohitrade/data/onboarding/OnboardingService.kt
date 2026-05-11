package com.lohitrade.data.onboarding

import android.content.SharedPreferences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Manages onboarding walkthrough state — checks/sets the is_onboarded flag
 * via SharedPreferences (local) and syncs with the backend (Req 33.5, 33.8).
 *
 * Mirrors the iOS OnboardingService pattern.
 */
class OnboardingService(
    private val prefs: SharedPreferences,
    private val syncCallback: (suspend (Boolean) -> Unit)? = null,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
) {
    companion object {
        const val PREFS_KEY = "is_onboarded"
    }

    private val _showWalkthrough = MutableStateFlow(false)
    /** Whether the walkthrough overlay should be displayed. */
    val showWalkthrough: StateFlow<Boolean> = _showWalkthrough.asStateFlow()

    private val _currentStep = MutableStateFlow(0)
    /** Current step index in the walkthrough (0-based). */
    val currentStep: StateFlow<Int> = _currentStep.asStateFlow()

    /** Whether the user has completed or skipped onboarding. */
    val isOnboarded: Boolean
        get() = prefs.getBoolean(PREFS_KEY, false)

    /**
     * Check onboarding status and trigger walkthrough if needed.
     * Called after login / app launch.
     */
    fun checkOnboardingStatus() {
        if (!isOnboarded) {
            _currentStep.value = 0
            _showWalkthrough.value = true
        }
    }

    /**
     * Advance to the next walkthrough step. Completes if on the last step.
     */
    fun nextStep() {
        if (_currentStep.value < WalkthroughSteps.totalSteps - 1) {
            _currentStep.value += 1
        } else {
            completeOnboarding()
        }
    }

    /**
     * Go back to the previous walkthrough step.
     */
    fun previousStep() {
        if (_currentStep.value > 0) {
            _currentStep.value -= 1
        }
    }

    /**
     * Skip the walkthrough entirely and mark as onboarded.
     */
    fun skipOnboarding() {
        completeOnboarding()
    }

    /**
     * Mark onboarding as complete — sets local flag and syncs with backend (Req 33.5).
     */
    fun completeOnboarding() {
        prefs.edit().putBoolean(PREFS_KEY, true).apply()
        _showWalkthrough.value = false
        _currentStep.value = 0

        // Fire-and-forget sync to backend
        syncCallback?.let { callback ->
            scope.launch {
                try {
                    callback(true)
                } catch (_: Exception) {
                    // Non-critical — local flag is source of truth for UX
                }
            }
        }
    }

    /**
     * Reset onboarding so the walkthrough replays on next dashboard visit.
     * Called from "Replay Tutorial" in Settings (Req 33.8).
     */
    fun replayTutorial() {
        prefs.edit().putBoolean(PREFS_KEY, false).apply()
        _currentStep.value = 0
        _showWalkthrough.value = true

        syncCallback?.let { callback ->
            scope.launch {
                try {
                    callback(false)
                } catch (_: Exception) {
                    // Non-critical
                }
            }
        }
    }
}
