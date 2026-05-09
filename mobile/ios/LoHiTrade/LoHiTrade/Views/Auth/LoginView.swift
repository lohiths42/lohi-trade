import SwiftUI
import AuthenticationServices

/// Login screen with email, Google, and Apple sign-in options (Req 12.2, 12.3).
struct LoginView: View {
    @EnvironmentObject var authService: AuthService
    @State private var email = ""
    @State private var password = ""
    @State private var showRegister = false

    private let biometric = BiometricService.shared

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                // Logo / title
                VStack(spacing: 8) {
                    Text("LoHi-TRADE")
                        .font(.largeTitle.bold())
                    Text("Algorithmic Trading Platform")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                // Social login buttons (prominently placed per Req 32.8)
                VStack(spacing: 12) {
                    // Apple Sign-In
                    SignInWithAppleButton(.signIn) { request in
                        request.requestedScopes = [.fullName, .email]
                    } onCompletion: { result in
                        handleAppleSignIn(result)
                    }
                    .signInWithAppleButtonStyle(.black)
                    .frame(height: 50)
                    .cornerRadius(10)

                    // Google Sign-In placeholder
                    Button {
                        // Google Sign-In SDK integration point
                    } label: {
                        HStack {
                            Image(systemName: "globe")
                            Text("Continue with Google")
                        }
                        .frame(maxWidth: .infinity)
                        .frame(height: 50)
                        .background(Color(.systemGray6))
                        .cornerRadius(10)
                    }
                    .foregroundStyle(.primary)
                }

                // Divider
                HStack {
                    Rectangle().frame(height: 1).foregroundStyle(.secondary.opacity(0.3))
                    Text("or").foregroundStyle(.secondary).font(.footnote)
                    Rectangle().frame(height: 1).foregroundStyle(.secondary.opacity(0.3))
                }

                // Email/password fields
                VStack(spacing: 12) {
                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocapitalization(.none)
                        .textFieldStyle(.roundedBorder)

                    SecureField("Password", text: $password)
                        .textContentType(.password)
                        .textFieldStyle(.roundedBorder)

                    Button {
                        Task { await authService.login(email: email, password: password) }
                    } label: {
                        if authService.isLoading {
                            ProgressView()
                                .frame(maxWidth: .infinity)
                                .frame(height: 50)
                        } else {
                            Text("Sign In")
                                .frame(maxWidth: .infinity)
                                .frame(height: 50)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(email.isEmpty || password.isEmpty || authService.isLoading)
                }

                // Biometric login button
                if biometric.isBiometricAvailable {
                    Button {
                        Task { await authService.loginWithBiometric() }
                    } label: {
                        HStack {
                            Image(systemName: biometric.availableBiometricType() == .faceID
                                  ? "faceid" : "touchid")
                            Text("Unlock with \(biometric.availableBiometricType() == .faceID ? "Face ID" : "Touch ID")")
                        }
                    }
                    .foregroundStyle(.blue)
                }

                // Error message
                if let error = authService.errorMessage {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                        .multilineTextAlignment(.center)
                }

                Spacer()

                // Register link
                Button("Don't have an account? Sign Up") {
                    showRegister = true
                }
                .font(.footnote)
            }
            .padding(.horizontal, 24)
            .navigationDestination(isPresented: $showRegister) {
                RegisterView()
                    .environmentObject(authService)
            }
        }
    }

    private func handleAppleSignIn(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .success(let auth):
            guard let credential = auth.credential as? ASAuthorizationAppleIDCredential,
                  let authCodeData = credential.authorizationCode,
                  let authCode = String(data: authCodeData, encoding: .utf8) else {
                return
            }
            let fullName = [credential.fullName?.givenName, credential.fullName?.familyName]
                .compactMap { $0 }
                .joined(separator: " ")
            Task {
                await authService.loginWithApple(
                    authCode: authCode,
                    userName: fullName.isEmpty ? nil : fullName
                )
            }
        case .failure(let error):
            authService.errorMessage = error.localizedDescription
        }
    }
}
