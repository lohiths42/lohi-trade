import XCTest
@testable import LoHiTrade

/// Unit tests for OnboardingService — state management, navigation, and flag persistence.
@MainActor
final class OnboardingServiceTests: XCTestCase {

    private var defaults: UserDefaults!
    private var service: OnboardingService!

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: "OnboardingServiceTests")!
        defaults.removePersistentDomain(forName: "OnboardingServiceTests")
        service = OnboardingService(defaults: defaults)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: "OnboardingServiceTests")
        defaults = nil
        service = nil
        super.tearDown()
    }

    // MARK: - Initial state

    func testInitialStateNotOnboarded() {
        XCTAssertFalse(service.isOnboarded)
        XCTAssertFalse(service.showWalkthrough)
        XCTAssertEqual(service.currentStep, 0)
    }

    // MARK: - checkOnboardingStatus

    func testCheckOnboardingStatusShowsWalkthroughWhenNotOnboarded() {
        service.checkOnboardingStatus()
        XCTAssertTrue(service.showWalkthrough)
        XCTAssertEqual(service.currentStep, 0)
    }

    func testCheckOnboardingStatusDoesNotShowWhenAlreadyOnboarded() {
        defaults.set(true, forKey: "is_onboarded")
        service.checkOnboardingStatus()
        XCTAssertFalse(service.showWalkthrough)
    }

    // MARK: - Navigation: nextStep

    func testNextStepAdvancesStep() {
        service.checkOnboardingStatus()
        XCTAssertEqual(service.currentStep, 0)

        service.nextStep()
        XCTAssertEqual(service.currentStep, 1)
        XCTAssertTrue(service.showWalkthrough)

        service.nextStep()
        XCTAssertEqual(service.currentStep, 2)
    }

    func testNextStepOnLastStepCompletesOnboarding() {
        service.checkOnboardingStatus()
        // Navigate to last step
        for _ in 0..<(WalkthroughSteps.totalSteps - 1) {
            service.nextStep()
        }
        XCTAssertEqual(service.currentStep, WalkthroughSteps.totalSteps - 1)
        XCTAssertTrue(service.showWalkthrough)

        // Next on last step should complete
        service.nextStep()
        XCTAssertFalse(service.showWalkthrough)
        XCTAssertTrue(service.isOnboarded)
        XCTAssertEqual(service.currentStep, 0)
    }

    // MARK: - Navigation: previousStep

    func testPreviousStepGoesBack() {
        service.checkOnboardingStatus()
        service.nextStep()
        service.nextStep()
        XCTAssertEqual(service.currentStep, 2)

        service.previousStep()
        XCTAssertEqual(service.currentStep, 1)
    }

    func testPreviousStepDoesNotGoBelowZero() {
        service.checkOnboardingStatus()
        XCTAssertEqual(service.currentStep, 0)

        service.previousStep()
        XCTAssertEqual(service.currentStep, 0)
    }

    // MARK: - Skip

    func testSkipOnboardingSetsFlag() {
        service.checkOnboardingStatus()
        XCTAssertTrue(service.showWalkthrough)

        service.skipOnboarding()
        XCTAssertFalse(service.showWalkthrough)
        XCTAssertTrue(service.isOnboarded)
        XCTAssertTrue(defaults.bool(forKey: "is_onboarded"))
    }

    // MARK: - Complete

    func testCompleteOnboardingPersistsFlag() {
        service.checkOnboardingStatus()
        service.completeOnboarding()

        XCTAssertTrue(defaults.bool(forKey: "is_onboarded"))
        XCTAssertFalse(service.showWalkthrough)
        XCTAssertEqual(service.currentStep, 0)
    }

    // MARK: - Replay Tutorial

    func testReplayTutorialResetsState() {
        // First complete onboarding
        service.checkOnboardingStatus()
        service.completeOnboarding()
        XCTAssertTrue(service.isOnboarded)
        XCTAssertFalse(service.showWalkthrough)

        // Replay
        service.replayTutorial()
        XCTAssertFalse(service.isOnboarded)
        XCTAssertTrue(service.showWalkthrough)
        XCTAssertEqual(service.currentStep, 0)
        XCTAssertFalse(defaults.bool(forKey: "is_onboarded"))
    }

    // MARK: - WalkthroughStep model

    func testWalkthroughStepsHasSevenSteps() {
        XCTAssertEqual(WalkthroughSteps.totalSteps, 7)
        XCTAssertEqual(WalkthroughSteps.all.count, 7)
    }

    func testWalkthroughStepsHaveUniqueIds() {
        let ids = WalkthroughSteps.all.map(\.id)
        XCTAssertEqual(Set(ids).count, ids.count, "All step IDs should be unique")
    }

    func testWalkthroughStepsHaveContent() {
        for step in WalkthroughSteps.all {
            XCTAssertFalse(step.title.isEmpty, "Step \(step.id) should have a title")
            XCTAssertFalse(step.description.isEmpty, "Step \(step.id) should have a description")
            XCTAssertFalse(step.iconName.isEmpty, "Step \(step.id) should have an icon")
            XCTAssertFalse(step.targetIdentifier.isEmpty, "Step \(step.id) should have a target identifier")
        }
    }

    func testWalkthroughStepSequence() {
        let titles = WalkthroughSteps.all.map(\.title)
        XCTAssertEqual(titles, [
            "Dashboard Overview",
            "Manage Positions",
            "Stock Screener",
            "Watchlists",
            "Connect Broker",
            "AI Chatbot",
            "Kill Switch",
        ])
    }

    // MARK: - Full walkthrough flow

    func testFullWalkthroughFlow() {
        // Start
        service.checkOnboardingStatus()
        XCTAssertTrue(service.showWalkthrough)
        XCTAssertEqual(service.currentStep, 0)

        // Walk through all steps
        for expectedStep in 1..<WalkthroughSteps.totalSteps {
            service.nextStep()
            XCTAssertEqual(service.currentStep, expectedStep)
            XCTAssertTrue(service.showWalkthrough)
        }

        // Complete on last step
        service.nextStep()
        XCTAssertFalse(service.showWalkthrough)
        XCTAssertTrue(service.isOnboarded)

        // Subsequent check should not show walkthrough
        service.checkOnboardingStatus()
        XCTAssertFalse(service.showWalkthrough)
    }

    func testBackAndForthNavigation() {
        service.checkOnboardingStatus()

        service.nextStep() // 0 -> 1
        service.nextStep() // 1 -> 2
        service.nextStep() // 2 -> 3
        XCTAssertEqual(service.currentStep, 3)

        service.previousStep() // 3 -> 2
        service.previousStep() // 2 -> 1
        XCTAssertEqual(service.currentStep, 1)

        service.nextStep() // 1 -> 2
        XCTAssertEqual(service.currentStep, 2)
        XCTAssertTrue(service.showWalkthrough)
    }
}
