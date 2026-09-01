import Foundation

/// Where the app finds the engine it ships with, and where it keeps user data.
///
/// Nothing the user creates is ever written inside the bundle: an app bundle is
/// read-only in the general case and gets replaced wholesale on update, so
/// state kept there would be lost. Application Support is the documented home
/// for it, and it is the same path the engine derives independently in
/// packaging/macos/telemachos_engine.py.
enum EnginePaths {

    /// The frozen engine executable inside Contents/Resources/engine/.
    static var engineExecutable: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let candidate = resources
            .appendingPathComponent("engine", isDirectory: true)
            .appendingPathComponent("TelemachosEngine")
        return FileManager.default.isExecutableFile(atPath: candidate.path) ? candidate : nil
    }

    /// The bundled llama.cpp server, when this build has one.
    ///
    /// Passed to the engine explicitly rather than discovered by walking up
    /// from the frozen payload: the engine's idea of its own root is
    /// PyInstaller's extraction directory, which is a poor place to start
    /// guessing bundle layout from.
    static var llamaServer: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let candidate = resources
            .appendingPathComponent("llama", isDirectory: true)
            .appendingPathComponent("llama-server")
        return FileManager.default.isExecutableFile(atPath: candidate.path) ? candidate : nil
    }

    /// ~/Library/Application Support/Telemachos
    static var dataDirectory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent("Telemachos", isDirectory: true)
    }

    static var logDirectory: URL {
        dataDirectory.appendingPathComponent("logs", isDirectory: true)
    }

    /// The engine's own log. Written by the engine process, read by the log viewer.
    static var engineLog: URL {
        logDirectory.appendingPathComponent("engine.log")
    }

    /// Captures the engine's stdout/stderr. Separate from engine.log because a
    /// crash during interpreter start-up happens before Python logging exists,
    /// and that traceback is exactly the one worth having.
    static var launchLog: URL {
        logDirectory.appendingPathComponent("launch.log")
    }

    static func ensureDirectories() {
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
    }
}
