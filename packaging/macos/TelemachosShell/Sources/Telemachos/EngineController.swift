import Foundation

/// Owns the embedded engine process for the lifetime of the app.
///
/// The app has no notion of a server address. It reserves a loopback port,
/// starts the engine it ships with, waits for that engine to report itself
/// ready, and hands the resulting URL to the web view. There is nothing for the
/// user to configure and nothing to install.
@MainActor
final class EngineController: ObservableObject {

    enum Phase: Equatable {
        case launching
        case waiting
        case ready(URL)
        case failed(reason: String)

        var isReady: Bool {
            if case .ready = self { return true }
            return false
        }
    }

    /// One engine per app. The SwiftUI scene and the application delegate both
    /// need to reach it - the scene to drive it, the delegate to stop it on the
    /// way out - and a second instance would mean a second orphaned process.
    static let shared = EngineController()

    @Published private(set) var phase: Phase = .launching
    /// Human-readable status for the splash screen.
    @Published private(set) var status: String = "Starting Telemachos…"
    /// Seconds since the current start attempt began.
    @Published private(set) var elapsed: TimeInterval = 0

    private var process: Process?
    private var supervisor: Task<Void, Never>?
    private var port: Int = 0

    /// First launch initialises a database and unpacks the embedding model, so
    /// the ceiling is generous. It only matters when something is genuinely
    /// wrong, and then the log is what the user needs.
    private let readinessTimeout: TimeInterval = 180

    // MARK: - Lifecycle

    func start() {
        guard supervisor == nil else { return }
        EnginePaths.ensureDirectories()
        supervisor = Task { await runStartSequence() }
    }

    func restart() {
        supervisor?.cancel()
        supervisor = nil
        stopEngine()
        phase = .launching
        status = "Restarting Telemachos…"
        elapsed = 0
        start()
    }

    /// Terminate the engine and wait briefly for it to go down cleanly.
    ///
    /// A graceful stop matters: the engine's shutdown flushes the database and
    /// closes the built-in MCP servers. Those are stdio children, so they exit
    /// on their own once the engine's pipes close - killing the engine is
    /// enough to bring the whole tree down.
    func shutdown() {
        supervisor?.cancel()
        supervisor = nil
        stopEngine()
    }

    private func stopEngine() {
        guard let process, process.isRunning else {
            self.process = nil
            return
        }
        process.terminate()

        let deadline = Date().addingTimeInterval(5)
        while process.isRunning && Date() < deadline {
            usleep(50_000)
        }
        if process.isRunning {
            kill(process.processIdentifier, SIGKILL)
        }
        self.process = nil
    }

    // MARK: - Start sequence

    private func runStartSequence() async {
        guard let executable = EnginePaths.engineExecutable else {
            fail("The bundled engine is missing from this copy of Telemachos. Reinstalling should fix it.")
            return
        }
        guard let reserved = Self.reserveLoopbackPort() else {
            fail("Could not reserve a local port for the engine.")
            return
        }
        port = reserved

        status = "Starting the Telemachos engine…"
        do {
            try launch(executable: executable, port: port)
        } catch {
            fail("The engine could not be started: \(error.localizedDescription)")
            return
        }

        await waitUntilReady()
    }

    private func launch(executable: URL, port: Int) throws {
        let process = Process()
        process.executableURL = executable
        process.arguments = ["--port", String(port)]
        process.currentDirectoryURL = executable.deletingLastPathComponent()

        var environment = ProcessInfo.processInfo.environment
        // The engine derives these itself; setting them here keeps the two
        // sides of the contract visible in one place and lets a developer
        // override the data directory when running a build by hand.
        environment["TELEMACHOS_PORT"] = String(port)
        environment["TELEMACHOS_DATA_DIR"] = EnginePaths.dataDirectory.path
        environment["CHROMADB_MODE"] = "embedded"
        // Only set when this build actually shipped the runtime; the engine
        // treats its absence as "local serving unavailable" rather than an
        // error, so a build without it still runs normally.
        if let llama = EnginePaths.llamaServer {
            environment["TELEMACHOS_LLAMA_SERVER"] = llama.path
        }
        process.environment = environment

        // stdout and stderr go to a file so a start-up crash leaves evidence.
        FileManager.default.createFile(atPath: EnginePaths.launchLog.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: EnginePaths.launchLog) {
            process.standardOutput = handle
            process.standardError = handle
        }

        try process.run()
        self.process = process
    }

    private func waitUntilReady() async {
        let started = Date()
        let readyURL = URL(string: "http://127.0.0.1:\(port)/api/ready")!
        status = "Preparing your workspace…"

        while !Task.isCancelled {
            elapsed = Date().timeIntervalSince(started)

            if let process, !process.isRunning {
                fail("The engine stopped unexpectedly during start-up.")
                return
            }
            if elapsed > readinessTimeout {
                fail("The engine did not become ready within \(Int(readinessTimeout)) seconds.")
                return
            }

            if await isReady(url: readyURL) {
                guard let appURL = URL(string: "http://127.0.0.1:\(port)/") else {
                    fail("Could not build the workspace address.")
                    return
                }
                status = "Ready"
                phase = .ready(appURL)
                return
            }

            // Give a longer-running first launch some narration rather than a
            // motionless spinner.
            if elapsed > 20 {
                status = "Still starting - first launch sets up your local database…"
            }

            try? await Task.sleep(nanoseconds: 400_000_000)
        }
    }

    /// The engine's readiness endpoint answers 200 only when the database, the
    /// data directory and local-first storage are all whole; it answers 503
    /// while any of them is not. Treating 503 as "not yet" is the difference
    /// between showing a working UI and showing a half-initialised one.
    private func isReady(url: URL) async -> Bool {
        var request = URLRequest(url: url)
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (_, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse else {
            return false
        }
        return http.statusCode == 200
    }

    private func fail(_ reason: String) {
        status = reason
        phase = .failed(reason: reason)
    }

    // MARK: - Port reservation

    /// Ask the kernel for an unused loopback port.
    ///
    /// Binding to port 0 and reading back the assignment is the standard way to
    /// get one that is genuinely free, rather than guessing a number and
    /// colliding with whatever else the user is running.
    static func reserveLoopbackPort() -> Int? {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return nil }
        defer { close(descriptor) }

        var address = sockaddr_in()
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = 0
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let addressSize = socklen_t(MemoryLayout<sockaddr_in>.size)

        let didBind = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { rebound in
                bind(descriptor, rebound, addressSize)
            }
        }
        guard didBind == 0 else { return nil }

        var assigned = sockaddr_in()
        var assignedSize = addressSize
        let didRead = withUnsafeMutablePointer(to: &assigned) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { rebound in
                getsockname(descriptor, rebound, &assignedSize)
            }
        }
        guard didRead == 0 else { return nil }

        return Int(UInt16(bigEndian: assigned.sin_port))
    }
}
