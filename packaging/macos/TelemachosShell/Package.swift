// swift-tools-version: 5.9
import PackageDescription

// The native shell for Telemachos. SwiftPM produces a bare executable; the
// build script (packaging/macos/build.sh) is what wraps it into Telemachos.app
// together with the frozen engine, the Info.plist and the icon.
let package = Package(
    name: "Telemachos",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "Telemachos",
            path: "Sources/Telemachos"
        )
    ]
)
