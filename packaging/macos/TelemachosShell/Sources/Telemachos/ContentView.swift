import AppKit
import SwiftUI

/// The whole window: a start-up screen until the engine is ready, then the
/// workspace. There is no server field, no setup step and no login — the app
/// starts what it needs and gets out of the way.
struct ContentView: View {
    @ObservedObject var engine: EngineController
    let coordinatorBox: WebViewCoordinatorBox

    var body: some View {
        switch engine.phase {
        case .ready(let url):
            WebView(url: url, coordinatorBox: coordinatorBox)
                .ignoresSafeArea()
        case .failed(let reason):
            FailureView(reason: reason, engine: engine)
        case .launching, .waiting:
            StartupView(engine: engine)
        }
    }
}

private struct StartupView: View {
    @ObservedObject var engine: EngineController

    var body: some View {
        VStack(spacing: 18) {
            Spacer()

            Image(systemName: "sailboat.fill")
                .font(.system(size: 52, weight: .light))
                .foregroundStyle(.tint)

            Text("Telemachos")
                .font(.system(size: 26, weight: .semibold, design: .rounded))

            ProgressView()
                .progressViewStyle(.linear)
                .frame(width: 240)

            Text(engine.status)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 340)

            // Only offer the log once a start is slow enough to be worth
            // investigating. Showing it immediately would imply something is
            // wrong on every normal launch.
            if engine.elapsed > 25 {
                Button("Show engine log") {
                    NSWorkspace.shared.open(EnginePaths.logDirectory)
                }
                .buttonStyle(.link)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
    }
}

private struct FailureView: View {
    let reason: String
    @ObservedObject var engine: EngineController

    var body: some View {
        VStack(spacing: 16) {
            Spacer()

            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 44))
                .foregroundStyle(.orange)

            Text("Telemachos could not start")
                .font(.title2.weight(.semibold))

            Text(reason)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)

            HStack(spacing: 12) {
                Button("Try again") { engine.restart() }
                    .keyboardShortcut(.defaultAction)
                Button("Open log folder") {
                    NSWorkspace.shared.open(EnginePaths.logDirectory)
                }
            }
            .padding(.top, 4)

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
    }
}
