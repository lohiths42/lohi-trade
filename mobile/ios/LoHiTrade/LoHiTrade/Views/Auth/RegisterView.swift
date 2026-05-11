import SwiftUI

/// Registration screen for email sign-up.
struct RegisterView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var email = ""
    @State private var phone = ""
    @State private var password = ""
    @State private var confirmPassword = ""

    private var isFormValid: Bool {
        !name.isEmpty
        && !email.isEmpty
        && phone.count == 10
        && !password.isEmpty
        && password == confirmPassword
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Text("Create Account")
                    .font(.title2.bold())
                    .padding(.top, 16)

                VStack(spacing: 12) {
                    TextField("Full Name", text: $name)
                        .textContentType(.name)
                        .textFieldStyle(.roundedBorder)

                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocapitalization(.none)
                        .textFieldStyle(.roundedBorder)

                    TextField("Mobile Number (10 digits)", text: $phone)
                        .textContentType(.telephoneNumber)
                        .keyboardType(.phonePad)
                        .textFieldStyle(.roundedBorder)

                    SecureField("Password", text: $password)
                        .textContentType(.newPassword)
                        .textFieldStyle(.roundedBorder)

                    SecureField("Confirm Password", text: $confirmPassword)
                        .textContentType(.newPassword)
                        .textFieldStyle(.roundedBorder)

                    if !password.isEmpty && !confirmPassword.isEmpty && password != confirmPassword {
                        Text("Passwords do not match")
                            .foregroundStyle(.red)
                            .font(.caption)
                    }
                }

                // Password requirements hint
                VStack(alignment: .leading, spacing: 4) {
                    Text("Password must contain:")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Group {
                        requirementRow("At least 8 characters", met: password.count >= 8)
                        requirementRow("One uppercase letter", met: password.range(of: "[A-Z]", options: .regularExpression) != nil)
                        requirementRow("One lowercase letter", met: password.range(of: "[a-z]", options: .regularExpression) != nil)
                        requirementRow("One digit", met: password.range(of: "[0-9]", options: .regularExpression) != nil)
                        requirementRow("One special character", met: password.range(of: "[^A-Za-z0-9]", options: .regularExpression) != nil)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Button {
                    Task {
                        await authService.register(email: email, password: password, phone: phone, name: name)
                        if authService.isAuthenticated { dismiss() }
                    }
                } label: {
                    if authService.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                    } else {
                        Text("Create Account")
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!isFormValid || authService.isLoading)

                if let error = authService.errorMessage {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                        .multilineTextAlignment(.center)
                }
            }
            .padding(.horizontal, 24)
        }
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    private func requirementRow(_ text: String, met: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: met ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(met ? .green : .secondary)
                .font(.caption)
            Text(text)
                .font(.caption)
                .foregroundStyle(met ? .primary : .secondary)
        }
    }
}
