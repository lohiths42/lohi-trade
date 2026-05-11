import SwiftUI

/// 7-step guided walkthrough overlay with spotlight effect, tooltips,
/// and Next/Back/Skip navigation (Req 33.2, 33.3, 33.5, 33.8).
struct WalkthroughView: View {
    @ObservedObject var onboardingService: OnboardingService

    /// Tracks whether the view has appeared (drives entry animation).
    @State private var isVisible = false

    private var step: WalkthroughStep {
        WalkthroughSteps.all[onboardingService.currentStep]
    }

    var body: some View {
        ZStack {
            // Dimmed overlay (spotlight effect — Req 33.3)
            Color.black.opacity(isVisible ? 0.6 : 0.0)
                .ignoresSafeArea()
                .animation(.easeInOut(duration: 0.3), value: isVisible)
                .onTapGesture { /* block taps on background */ }

            VStack(spacing: 0) {
                Spacer()

                // Tooltip card with step content
                tooltipCard
                    .padding(.horizontal, 24)
                    .opacity(isVisible ? 1 : 0)
                    .offset(y: isVisible ? 0 : 30)
                    .scaleEffect(isVisible ? 1 : 0.9)
                    .animation(
                        .spring(response: 0.4, dampingFraction: 0.8),
                        value: isVisible
                    )

                Spacer()

                // Navigation bar: Back / Progress / Next + Skip
                navigationBar
                    .padding(.horizontal, 24)
                    .padding(.bottom, 32)
                    .opacity(isVisible ? 1 : 0)
                    .animation(.easeInOut(duration: 0.3).delay(0.15), value: isVisible)
            }
        }
        .onAppear { isVisible = true }
        .onDisappear { isVisible = false }
    }

    // MARK: - Tooltip Card

    private var tooltipCard: some View {
        VStack(spacing: 16) {
            // Animated pointer arrow
            arrowIndicator
                .offset(y: isVisible ? 0 : -8)
                .animation(
                    .easeInOut(duration: 1.0).repeatForever(autoreverses: true),
                    value: isVisible
                )

            // Icon
            Image(systemName: step.iconName)
                .font(.system(size: 40))
                .foregroundColor(.accentColor)
                .scaleEffect(isVisible ? 1 : 0.5)
                .animation(
                    .spring(response: 0.5, dampingFraction: 0.6).delay(0.1),
                    value: onboardingService.currentStep
                )
                .id(step.id) // force re-render on step change

            // Title
            Text(step.title)
                .font(.title2.bold())
                .multilineTextAlignment(.center)

            // Description
            Text(step.description)
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color(.systemBackground))
                .shadow(color: .black.opacity(0.15), radius: 12, y: 4)
        )
        .transition(.asymmetric(
            insertion: .opacity.combined(with: .scale(scale: 0.95)),
            removal: .opacity.combined(with: .scale(scale: 0.95))
        ))
        .id(step.id) // animate card swap
        .animation(.easeInOut(duration: 0.25), value: onboardingService.currentStep)
    }

    // MARK: - Arrow Indicator

    private var arrowIndicator: some View {
        Image(systemName: arrowSystemName)
            .font(.title3)
            .foregroundColor(.accentColor)
    }

    private var arrowSystemName: String {
        switch step.tooltipPosition {
        case .top: return "arrow.up"
        case .bottom: return "arrow.down"
        case .leading: return "arrow.left"
        case .trailing: return "arrow.right"
        }
    }

    // MARK: - Navigation Bar

    private var navigationBar: some View {
        VStack(spacing: 12) {
            // Progress indicator (Req 33.5)
            progressIndicator

            HStack {
                // Back button
                if onboardingService.currentStep > 0 {
                    Button(action: {
                        withAnimation(.easeInOut(duration: 0.25)) {
                            onboardingService.previousStep()
                        }
                    }) {
                        HStack(spacing: 4) {
                            Image(systemName: "chevron.left")
                            Text("Back")
                        }
                        .font(.body)
                        .foregroundColor(.secondary)
                    }
                } else {
                    // Skip button on first step
                    Button("Skip") {
                        onboardingService.skipOnboarding()
                    }
                    .font(.body)
                    .foregroundColor(.secondary)
                }

                Spacer()

                // Step counter text
                Text("Step \(onboardingService.currentStep + 1) of \(WalkthroughSteps.totalSteps)")
                    .font(.caption)
                    .foregroundColor(.secondary)

                Spacer()

                // Next / Done button
                Button(action: {
                    withAnimation(.easeInOut(duration: 0.25)) {
                        onboardingService.nextStep()
                    }
                }) {
                    HStack(spacing: 4) {
                        Text(isLastStep ? "Done" : "Next")
                        if !isLastStep {
                            Image(systemName: "chevron.right")
                        }
                    }
                    .font(.body.bold())
                    .foregroundColor(.white)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 10)
                    .background(Capsule().fill(Color.accentColor))
                }
            }

            // Skip on non-first steps
            if onboardingService.currentStep > 0 {
                Button("Skip Tutorial") {
                    onboardingService.skipOnboarding()
                }
                .font(.caption)
                .foregroundColor(.secondary)
            }
        }
    }

    // MARK: - Progress Indicator

    private var progressIndicator: some View {
        HStack(spacing: 6) {
            ForEach(0..<WalkthroughSteps.totalSteps, id: \.self) { index in
                Capsule()
                    .fill(index <= onboardingService.currentStep ? Color.accentColor : Color.gray.opacity(0.3))
                    .frame(
                        width: index == onboardingService.currentStep ? 24 : 8,
                        height: 6
                    )
                    .animation(.easeInOut(duration: 0.25), value: onboardingService.currentStep)
            }
        }
    }

    private var isLastStep: Bool {
        onboardingService.currentStep == WalkthroughSteps.totalSteps - 1
    }
}
