package com.lohitrade

import android.content.SharedPreferences
import com.lohitrade.data.onboarding.OnboardingService
import com.lohitrade.data.onboarding.WalkthroughSteps
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.JUnit4

/**
 * Unit tests for OnboardingService — state management, navigation, and flag persistence.
 * Mirrors the iOS OnboardingServiceTests pattern.
 */
@RunWith(JUnit4::class)
class OnboardingServiceTest {

    private lateinit var prefs: FakeSharedPreferences
    private lateinit var service: OnboardingService

    @Before
    fun setUp() {
        prefs = FakeSharedPreferences()
        service = OnboardingService(prefs = prefs, syncCallback = null)
    }

    // -- Initial state --

    @Test
    fun `initial state is not onboarded`() {
        assertFalse(service.isOnboarded)
        assertFalse(service.showWalkthrough.value)
        assertEquals(0, service.currentStep.value)
    }

    // -- checkOnboardingStatus --

    @Test
    fun `checkOnboardingStatus shows walkthrough when not onboarded`() {
        service.checkOnboardingStatus()
        assertTrue(service.showWalkthrough.value)
        assertEquals(0, service.currentStep.value)
    }

    @Test
    fun `checkOnboardingStatus does not show when already onboarded`() {
        prefs.edit().putBoolean(OnboardingService.PREFS_KEY, true).apply()
        service.checkOnboardingStatus()
        assertFalse(service.showWalkthrough.value)
    }

    // -- Navigation: nextStep --

    @Test
    fun `nextStep advances step`() {
        service.checkOnboardingStatus()
        assertEquals(0, service.currentStep.value)

        service.nextStep()
        assertEquals(1, service.currentStep.value)
        assertTrue(service.showWalkthrough.value)

        service.nextStep()
        assertEquals(2, service.currentStep.value)
    }

    @Test
    fun `nextStep on last step completes onboarding`() {
        service.checkOnboardingStatus()
        // Navigate to last step
        for (i in 0 until WalkthroughSteps.totalSteps - 1) {
            service.nextStep()
        }
        assertEquals(WalkthroughSteps.totalSteps - 1, service.currentStep.value)
        assertTrue(service.showWalkthrough.value)

        // Next on last step should complete
        service.nextStep()
        assertFalse(service.showWalkthrough.value)
        assertTrue(service.isOnboarded)
        assertEquals(0, service.currentStep.value)
    }

    // -- Navigation: previousStep --

    @Test
    fun `previousStep goes back`() {
        service.checkOnboardingStatus()
        service.nextStep()
        service.nextStep()
        assertEquals(2, service.currentStep.value)

        service.previousStep()
        assertEquals(1, service.currentStep.value)
    }

    @Test
    fun `previousStep does not go below zero`() {
        service.checkOnboardingStatus()
        assertEquals(0, service.currentStep.value)

        service.previousStep()
        assertEquals(0, service.currentStep.value)
    }

    // -- Skip --

    @Test
    fun `skipOnboarding sets flag`() {
        service.checkOnboardingStatus()
        assertTrue(service.showWalkthrough.value)

        service.skipOnboarding()
        assertFalse(service.showWalkthrough.value)
        assertTrue(service.isOnboarded)
        assertTrue(prefs.getBoolean(OnboardingService.PREFS_KEY, false))
    }

    // -- Complete --

    @Test
    fun `completeOnboarding persists flag`() {
        service.checkOnboardingStatus()
        service.completeOnboarding()

        assertTrue(prefs.getBoolean(OnboardingService.PREFS_KEY, false))
        assertFalse(service.showWalkthrough.value)
        assertEquals(0, service.currentStep.value)
    }

    // -- Replay Tutorial --

    @Test
    fun `replayTutorial resets state`() {
        // First complete onboarding
        service.checkOnboardingStatus()
        service.completeOnboarding()
        assertTrue(service.isOnboarded)
        assertFalse(service.showWalkthrough.value)

        // Replay
        service.replayTutorial()
        assertFalse(service.isOnboarded)
        assertTrue(service.showWalkthrough.value)
        assertEquals(0, service.currentStep.value)
        assertFalse(prefs.getBoolean(OnboardingService.PREFS_KEY, false))
    }

    // -- WalkthroughStep model --

    @Test
    fun `walkthrough steps has seven steps`() {
        assertEquals(7, WalkthroughSteps.totalSteps)
        assertEquals(7, WalkthroughSteps.all.size)
    }

    @Test
    fun `walkthrough steps have unique ids`() {
        val ids = WalkthroughSteps.all.map { it.id }
        assertEquals("All step IDs should be unique", ids.toSet().size, ids.size)
    }

    @Test
    fun `walkthrough steps have content`() {
        for (step in WalkthroughSteps.all) {
            assertTrue("Step ${step.id} should have a title", step.title.isNotEmpty())
            assertTrue("Step ${step.id} should have a description", step.description.isNotEmpty())
            assertTrue("Step ${step.id} should have an icon", step.iconName.isNotEmpty())
            assertTrue("Step ${step.id} should have a target identifier", step.targetIdentifier.isNotEmpty())
        }
    }

    @Test
    fun `walkthrough step sequence matches expected order`() {
        val titles = WalkthroughSteps.all.map { it.title }
        assertEquals(
            listOf(
                "Dashboard Overview",
                "Manage Positions",
                "Stock Screener",
                "Watchlists",
                "Connect Broker",
                "AI Chatbot",
                "Kill Switch"
            ),
            titles
        )
    }

    // -- Full walkthrough flow --

    @Test
    fun `full walkthrough flow`() {
        // Start
        service.checkOnboardingStatus()
        assertTrue(service.showWalkthrough.value)
        assertEquals(0, service.currentStep.value)

        // Walk through all steps
        for (expectedStep in 1 until WalkthroughSteps.totalSteps) {
            service.nextStep()
            assertEquals(expectedStep, service.currentStep.value)
            assertTrue(service.showWalkthrough.value)
        }

        // Complete on last step
        service.nextStep()
        assertFalse(service.showWalkthrough.value)
        assertTrue(service.isOnboarded)

        // Subsequent check should not show walkthrough
        service.checkOnboardingStatus()
        assertFalse(service.showWalkthrough.value)
    }

    @Test
    fun `back and forth navigation`() {
        service.checkOnboardingStatus()

        service.nextStep() // 0 -> 1
        service.nextStep() // 1 -> 2
        service.nextStep() // 2 -> 3
        assertEquals(3, service.currentStep.value)

        service.previousStep() // 3 -> 2
        service.previousStep() // 2 -> 1
        assertEquals(1, service.currentStep.value)

        service.nextStep() // 1 -> 2
        assertEquals(2, service.currentStep.value)
        assertTrue(service.showWalkthrough.value)
    }

    // -- Sync callback --

    @Test
    fun `completeOnboarding invokes sync callback`() = runTest {
        var syncedValue: Boolean? = null
        val serviceWithSync = OnboardingService(
            prefs = prefs,
            syncCallback = { value -> syncedValue = value },
            scope = this
        )
        serviceWithSync.checkOnboardingStatus()
        serviceWithSync.completeOnboarding()

        // Allow coroutine to execute
        testScheduler.advanceUntilIdle()
        assertEquals(true, syncedValue)
    }

    @Test
    fun `replayTutorial invokes sync callback with false`() = runTest {
        var syncedValue: Boolean? = null
        val serviceWithSync = OnboardingService(
            prefs = prefs,
            syncCallback = { value -> syncedValue = value },
            scope = this
        )
        serviceWithSync.checkOnboardingStatus()
        serviceWithSync.completeOnboarding()
        testScheduler.advanceUntilIdle()

        syncedValue = null
        serviceWithSync.replayTutorial()
        testScheduler.advanceUntilIdle()
        assertEquals(false, syncedValue)
    }
}
