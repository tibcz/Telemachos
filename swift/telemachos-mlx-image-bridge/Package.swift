// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "telemachos-mlx-image-bridge",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "telemachos-mlx-inpaint", targets: ["TelemachosMLXInpaint"]),
        .executable(name: "telemachos-mlx-colorize", targets: ["TelemachosMLXColorize"]),
    ],
    dependencies: [
        .package(url: "https://github.com/xocialize/mlx-lama-swift", branch: "main"),
        .package(url: "https://github.com/xocialize/mlx-ddcolor-swift", branch: "main"),
    ],
    targets: [
        .executableTarget(
            name: "TelemachosMLXInpaint",
            dependencies: [
                .product(name: "LaMa", package: "mlx-lama-swift"),
                .product(name: "MIGAN", package: "mlx-lama-swift"),
            ]
        ),
        .executableTarget(
            name: "TelemachosMLXColorize",
            dependencies: [
                .product(name: "DDColor", package: "mlx-ddcolor-swift"),
            ]
        ),
    ]
)
