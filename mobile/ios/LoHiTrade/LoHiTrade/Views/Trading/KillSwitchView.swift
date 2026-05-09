import SwiftUI

/// Kill switch with confirmation dialog (Req 13.5).
struct KillSwitchView: View {
    @StateObject private var tradingService = TradingService.shared
    @State private var showActivateConfirmation = false
    @State private var showDeactivateConfirmation = false

    private var isActive: Bool {
        tradingService.killSwitchStatus?.isActive ?? false
    }

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: isActive ? "power.circle.fill" : "power.circle")
                .font(.system(size: 80))
                .foregroundColor(isActive ? .red : .green)

            Text(isActive ? "Kill Switch ACTIVE" : "Kill Switch Inactive")
                .font(.title2.bold())
                .foregroundColor(isActive ? .red : .primary)

            Text(isActive
                 ? "All trading is halted. Open positions are being closed."
                 : "Trading is running normally. Activate to halt all trading immediately.")
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            if let status = tradingService.killSwitchStatus {
                if let activatedAt = status.activatedAt {
                    Text("Activated: \(activatedAt)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                if let reason = status.reason {
                    Text("Reason: \(reason)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

            Spacer()

            Button(action: {
                if isActive {
                    showDeactivateConfirmation = true
                } else {
                    showActivateConfirmation = true
                }
            }) {
                Text(isActive ? "Deactivate Kill Switch" : "Activate Kill Switch")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(isActive ? Color.green : Color.red)
                    .foregroundColor(.white)
                    .cornerRadius(12)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
        }
        .navigationTitle("Kill Switch")
        .task {
            await tradingService.fetchKillSwitchStatus()
        }
        .alert("Activate Kill Switch?", isPresented: $showActivateConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Activate", role: .destructive) {
                Task {
                    _ = await tradingService.toggleKillSwitch(activate: true, reason: "Manual activation")
                }
            }
        } message: {
            Text("This will immediately halt all trading and close all open positions. Are you sure?")
        }
        .alert("Deactivate Kill Switch?", isPresented: $showDeactivateConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Deactivate") {
                Task {
                    _ = await tradingService.toggleKillSwitch(activate: false)
                }
            }
        } message: {
            Text("This will resume normal trading operations.")
        }
    }
}
