// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "RockyCompanion",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "RockyCompanion", targets: ["RockyCompanion"])
    ],
    targets: [
        .executableTarget(
            name: "RockyCompanion",
            path: "RockyCompanion",
            exclude: [
                "Resources/Assets.xcassets",
                "Support/RockyCompanion.entitlements"
            ],
            resources: [
                .process("Resources/Sprites")
            ]
        )
    ]
)
