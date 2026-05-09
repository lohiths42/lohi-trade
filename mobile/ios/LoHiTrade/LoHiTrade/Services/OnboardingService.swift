import Foundation
import SwiftUI

/// Manages onboarding walkthrough state — checks/sets the is_onboarded flag
/// via UserDefaults (local) and syncs with the backend (Req 33.5, 33.8).
@MainActor
final class OnboardingService: ObservableObject {
    static let shared = OnboardingService()

    /// Whether the walkthrough overlay should be displayed.
    @Published var showWalkthrough = false

    /// Current step index in the walkthrough (0-based).
    @Published var currentStep: Int = 0

    private let userDefaultsKey = "is_onboarded"
    private let defaults: UserDefaults
    private let apiClient: APIClient

    init(defaults: UserDefaults = .standard, apiClient: APIClient = .shared) {
        self.defaults = defaults
        self.apiClient = apiClient
    }

    /// Whether the user has completed or skipped onboarding.
    var isOnboarded: Bool {
        defaults.bool(forKey: userDefaultsKey)
    }

    /// Check onboarding status and trigger walkthrough if needed.
    /// Called after login / app launch.
    func checkOnboardingStatus() {
        if !isOnboarded {
            currentStep = 0
            showWalkthrough = true
        }
    }

    /// Advance to the next walkthrough step. Completes if on the last step.
    func nextStep() {
        if currentStep < WalkthroughSteps.totalSteps - 1 {
            currentStep += 1
        } else {
            completeOnboarding()
        }
    }

    /// Go back to the previous walkthrough step.
    func previousStep() {
        if currentStep > 0 {
            currentStep -= 1
        }
    }

    /// Skip the walkthrough entirely and mark as onboarded.
    func skipOnboarding() {
        completeOnboarding()
    }

    /// Mark onboarding as complete — sets local flag and syncs with backend (Req 33.5).
    func completeOnboarding() {
        defaults.set(true, forKey: userDefaultsKey)
        showWalkthrough = false
        currentStep = 0

        // Fire-and-forget sync to backend
        Task {
            await syncOnboardedFlag(value: true)
        }
    }

    /// Reset onboarding so the walkthrough replays on next dashboard visit.
    /// Called from "Replay Tutorial" in Settings (Req 33.8 — support replay).
    func replayTutorial() {
        defaults.set(false, forKey: userDefaultsKey)
        currentStep = 0
        showWalkthrough = true

        Task {
            await syncOnboardedFlag(value: false)
        }
    }

    // MARK: - Backend sync

    /// Sync the is_onboarded flag with the backend.
    private func syncOnboardedFlag(value: Bool) async {
        struct OnboardedBody: Encodable {
            let isOnboarded: Bool
            enum CodingKeys: String, CodingKey {
                case isOnboarded = "is_onboarded"
            }
        }

        do {
            let _: EmptyResponse = try await apiClient.authenticatedRequest(
                .put,
                path: "/users/onboarded",
                body: OnboardedBody(isOnboarded: value)
            )
        } catch {
            // Non-critical — local flag is source of truth for UX.
            // Backend will eventually sync on next login.
        }
    }
}

/// Empty response for endpoints that return no meaningful body.
struct EmptyResponse: Decodable {}
