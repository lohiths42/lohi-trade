// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "LoHiTrade",
    platforms: [
        .iOS(.v16)
    ],
    products: [
        .library(name: "LoHiTrade", targets: ["LoHiTrade"]),
    ],
    dependencies: [
        .package(url: "https://github.com/firebase/firebase-ios-sdk.git", from: "10.0.0"),
    ],
    targets: [
        .target(
            name: "LoHiTrade",
            dependencies: [
                .product(name: "FirebaseMessaging", package: "firebase-ios-sdk"),
            ],
            path: "LoHiTrade"
        ),
        .testTarget(
            name: "LoHiTradeTests",
            dependencies: ["LoHiTrade"],
            path: "Tests"
        ),
    ]
)
