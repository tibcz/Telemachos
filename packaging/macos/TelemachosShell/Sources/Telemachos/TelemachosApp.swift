import AppKit
import SwiftUI

@main
struct TelemachosApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var engine = EngineController.shared

    private let coordinatorBox = WebViewCoordinatorBox()

    var body: some Scene {
        WindowGroup("Telemachos") {
            ContentView(engine: engine, coordinatorBox: coordinatorBox)
                .frame(minWidth: 900, minHeight: 620)
                .onAppear { engine.start() }
        }
        .commands {
            TelemachosCommands(engine: engine, coordinatorBox: coordinatorBox)
        }

        Window("About Telemachos", id: "credits") {
            CreditsView()
        }
        .windowResizability(.contentSize)
    }
}

/// Menu commands.
///
/// Split into its own Commands type so it can hold @Environment(\.openWindow):
/// the About window is a scene, and a scene can only be opened through that
/// environment action, which is not available inside the App's own body.
struct TelemachosCommands: Commands {
    @ObservedObject var engine: EngineController
    let coordinatorBox: WebViewCoordinatorBox

    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        // Replace the stock About panel, which would show only the bundle
        // version, with the attribution the AGPL requires this build to carry.
        CommandGroup(replacing: .appInfo) {
            Button("About Telemachos") { openWindow(id: "credits") }
        }

        // The app is its own workspace; a "New Window" that opens a second view
        // of the same local engine is confusing, so it goes.
        CommandGroup(replacing: .newItem) {}

        CommandGroup(after: .toolbar) {
            Button("Reload") { coordinatorBox.coordinator?.reload() }
                .keyboardShortcut("r", modifiers: .command)

            Button("Restart Engine") { engine.restart() }
                .keyboardShortcut("r", modifiers: [.command, .shift])

            Divider()

            Button("Open Data Folder") {
                NSWorkspace.shared.open(EnginePaths.dataDirectory)
            }
            Button("Show Engine Log") {
                NSWorkspace.shared.open(EnginePaths.logDirectory)
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    /// Stop the engine before the app goes away.
    ///
    /// Deferring termination gives the engine time to shut down cleanly -
    /// flushing the database and closing the built-in MCP servers - instead of
    /// being killed mid-write when the process tree is torn down.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task { @MainActor in
            EngineController.shared.shutdown()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
