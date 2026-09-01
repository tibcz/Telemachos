import AppKit
import SwiftUI

/// Attribution and licensing.
///
/// Telemachos is a packaging of Odysseus, which is licensed under the AGPL.
/// That licence requires a distributed build to carry its notices and to offer
/// the corresponding source, so this window is a condition of shipping the app
/// at all, not decoration.
struct CreditsView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Telemachos")
                    .font(.title.weight(.semibold))

                Text("A standalone macOS application built on Odysseus, a self-hosted AI workspace.")
                    .foregroundStyle(.secondary)

                Divider()

                Text("Licence")
                    .font(.headline)

                Text("""
                Telemachos bundles Odysseus, which is licensed under the GNU Affero \
                General Public License, version 3 or later. Telemachos is distributed \
                under the same licence.

                This build is a modified version of the upstream Odysseus project.
                """)
                .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 12) {
                    Button("Upstream project") {
                        if let url = URL(string: "https://github.com/odysseus-dev/odysseus") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    Button("Full licence text") {
                        openBundledFile(named: "LICENSE")
                    }
                    Button("Acknowledgments") {
                        openBundledFile(named: "ACKNOWLEDGMENTS.md")
                    }
                }

                Divider()

                Text("Your data")
                    .font(.headline)

                Text("""
                Everything Telemachos stores — conversations, documents, notes, mail \
                and the local vector index — lives in a single folder on this Mac. \
                Nothing is written inside the application itself.
                """)
                .fixedSize(horizontal: false, vertical: true)

                Button("Open data folder") {
                    NSWorkspace.shared.open(EnginePaths.dataDirectory)
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(width: 520, height: 480)
    }

    /// The licence texts ride along inside the engine payload, which is where
    /// the build script puts them.
    private func openBundledFile(named name: String) {
        guard let resources = Bundle.main.resourceURL else { return }
        let candidates = [
            resources.appendingPathComponent("engine/_internal/\(name)"),
            resources.appendingPathComponent("engine/\(name)"),
            resources.appendingPathComponent(name),
        ]
        for candidate in candidates where FileManager.default.fileExists(atPath: candidate.path) {
            NSWorkspace.shared.open(candidate)
            return
        }
    }
}
