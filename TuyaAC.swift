import SwiftUI
import Foundation

// MARK: - Backend

/// Output of one `ac.py` invocation.
struct CommandResult: Sendable {
    let ok: Bool
    let output: String
    let error: String
}

/// Runs the bundled `ac.py` through `uv`. All device knowledge (datapoints,
/// temperature scale, valid values) lives in ac.py; the app only uses its CLI.
struct ACBackend: Sendable {
    let uv: String
    let script: String

    init() {
        uv = Self.findUV()
        script = Self.findScript()
    }

    func run(_ args: [String]) async -> CommandResult {
        let uv = uv, script = script
        return await Task.detached { Self.runBlocking(uv: uv, script: script, args: args) }.value
    }

    private static func runBlocking(uv: String, script: String, args: [String]) -> CommandResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: uv)
        // Without an absolute uv path, go through `env` so PATH is consulted.
        let prefix = uv.hasSuffix("/env") ? ["uv", "run", "--quiet"] : ["run", "--quiet"]
        process.arguments = prefix + [script] + args
        let stdout = Pipe()
        process.standardOutput = stdout
        // stderr goes to a temp file: an unread pipe can fill up and block the child.
        let errURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("tuya-ac-\(UUID().uuidString).log")
        defer { try? FileManager.default.removeItem(at: errURL) }
        guard FileManager.default.createFile(atPath: errURL.path, contents: nil),
              let stderr = try? FileHandle(forWritingTo: errURL)
        else { return CommandResult(ok: false, output: "", error: "Couldn't create a temporary file.") }
        process.standardError = stderr
        do {
            try process.run()
        } catch {
            return CommandResult(ok: false, output: "", error: "Couldn't launch uv: \(error.localizedDescription)")
        }
        let data = stdout.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        try? stderr.close()
        let message = (try? String(contentsOf: errURL, encoding: .utf8)) ?? ""
        return CommandResult(ok: process.terminationStatus == 0,
                             output: String(decoding: data, as: UTF8.self),
                             error: message)
    }

    /// GUI apps don't inherit the shell PATH, so probe the usual install spots.
    private static func findUV() -> String {
        let candidates = [
            "/opt/homebrew/bin/uv", "/usr/local/bin/uv",
            NSString(string: "~/.local/bin/uv").expandingTildeInPath,
            NSString(string: "~/.cargo/bin/uv").expandingTildeInPath,
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/env"
    }

    /// Prefer the ac.py bundled in the app; next to the binary covers dev builds.
    private static func findScript() -> String {
        if let bundled = Bundle.main.path(forResource: "ac", ofType: "py") { return bundled }
        let beside = Bundle.main.executableURL?.deletingLastPathComponent().appendingPathComponent("ac.py")
        return beside?.path ?? "ac.py"
    }
}

/// The `ac.py json` payload.
struct ACState: Decodable {
    var power: Bool
    var mode: String?
    var fan: String?
    var target: Double?
    var current: Double?
    var eco: Bool
    var sleep: Bool
    var minTemp: Int
    var maxTemp: Int

    static func decode(_ text: String) -> ACState? {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try? decoder.decode(ACState.self, from: Data(text.utf8))
    }
}

// MARK: - Model

@MainActor
@Observable
final class ACModel {
    var power = false
    var mode = ""
    var fan = ""
    var target = 24
    var room: Double?
    var eco = false
    var sleep = false
    var minTemp = 16
    var maxTemp = 32
    var reachable = true
    var lastError: String?
    var busy = false

    /// Chip labels and icons; the keys must match MODES / FANS in ac.py.
    let modes: [(key: String, name: String, icon: String)] = [
        ("cold", "Cool", "snowflake"),
        ("hot", "Heat", "flame"),
        ("auto", "Auto", "a.circle"),
        ("wind", "Fan", "wind"),
        ("wet", "Dry", "humidity"),
    ]
    let fans: [(key: String, name: String)] = [
        ("mute", "Quiet"), ("low", "Low"), ("mid", "Mid"), ("high", "High"), ("auto", "Auto"),
    ]

    private let backend = ACBackend()
    /// Tail of the device-I/O chain. Tuya devices usually accept only one local
    /// connection, so each ac.py call starts after the previous one finishes.
    @ObservationIgnored private var lastIO: Task<Void, Never>?
    /// Bumped on every user change; reads begun before the latest change are
    /// dropped so a slow poll can't overwrite what the user just picked.
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var pendingTemp: Task<Void, Never>?
    @ObservationIgnored private var poller: Task<Void, Never>?

    init() {
        // Poll from launch (not from the panel) so the menu bar label stays current.
        poller = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refresh()
                try? await Task.sleep(for: .seconds(60))
            }
        }
    }

    var statusLine: String {
        if !reachable { return "Offline" }
        guard power else { return "Off" }
        let name = modes.first { $0.key == mode }?.name ?? mode.capitalized
        return "\(name) · \(target)°"
    }
    var menuLabel: String {
        guard reachable, power else { return "" }
        return "\(target)°"
    }
    var menuIcon: String {
        guard reachable, power else { return "air.conditioner.horizontal" }
        return modes.first { $0.key == mode }?.icon ?? "air.conditioner.horizontal"
    }

    func refresh() async {
        let gen = generation
        await serially { await self.load(gen) }
    }

    // Changes show in the UI immediately; the device read that follows confirms them.
    func togglePower() { power.toggle(); send([power ? "on" : "off"]) }
    func setMode(_ m: String) { mode = m; send(["mode", m]) }
    func setFan(_ f: String) { fan = f; send(["fan", f]) }
    func toggleEco() { eco.toggle(); send(["eco", eco ? "on" : "off"]) }
    func toggleSleep() { sleep.toggle(); send(["sleep", sleep ? "on" : "off"]) }

    /// Sent after a short pause so a burst of taps becomes one command.
    func nudgeTarget(by delta: Int) {
        let value = min(maxTemp, max(minTemp, target + delta))
        guard value != target else { return }
        target = value
        generation += 1
        pendingTemp?.cancel()
        pendingTemp = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(600))
            guard !Task.isCancelled else { return }
            self?.send(["temp", "\(value)"])
        }
    }

    private func send(_ args: [String]) {
        generation += 1
        let gen = generation
        busy = true
        Task {
            await serially {
                let result = await self.backend.run(args)
                // A newer change is queued; its own read will show the final state.
                guard gen == self.generation else { return }
                await self.load(gen)
                if !result.ok {
                    self.lastError = Self.summary(result.error) ?? "The AC didn't accept that change."
                }
            }
            if gen == self.generation { self.busy = false }
        }
    }

    private func serially(_ work: @escaping @MainActor @Sendable () async -> Void) async {
        let previous = lastIO
        let task = Task { @MainActor in
            await previous?.value
            await work()
        }
        lastIO = task
        await task.value
    }

    private func load(_ gen: Int) async {
        let result = await backend.run(["json"])
        guard gen == generation else { return }
        guard result.ok, let state = ACState.decode(result.output) else {
            reachable = false
            lastError = Self.summary(result.error) ?? "No response from the AC."
            return
        }
        reachable = true
        lastError = nil
        power = state.power
        mode = state.mode ?? mode
        fan = state.fan ?? fan
        if let t = state.target { target = Int(t.rounded()) }
        room = state.current
        eco = state.eco
        sleep = state.sleep
        minTemp = state.minTemp
        maxTemp = state.maxTemp
    }

    /// Last meaningful line of ac.py / uv stderr, for display.
    private static func summary(_ stderr: String) -> String? {
        stderr.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .last { !$0.isEmpty }
    }
}

// MARK: - App

@main
struct TuyaACApp: App {
    @State private var ac = ACModel()

    var body: some Scene {
        MenuBarExtra {
            PanelView(ac: ac)
        } label: {
            Image(systemName: ac.menuIcon)
            Text(ac.menuLabel)
        }
        .menuBarExtraStyle(.window)
    }
}

// MARK: - Panel

struct PanelView: View {
    let ac: ACModel

    var body: some View {
        VStack(spacing: 16) {
            header
            tempCard
            picker(title: "Mode") { modeRow }
            picker(title: "Fan") { fanRow }
            togglesRow
        }
        .padding(18)
        .frame(width: 300)
        .task { await ac.refresh() }  // fresh state whenever the panel opens
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Air Conditioner")
                    .font(.system(size: 16, weight: .semibold))
                HStack(spacing: 6) {
                    Text(ac.statusLine)
                    if ac.busy { ProgressView().controlSize(.mini) }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                if let error = ac.lastError {
                    Text(error)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                        .lineLimit(2)
                        .help(error)
                }
            }
            Spacer()
            Button {
                ac.togglePower()
            } label: {
                Image(systemName: "power")
                    .font(.system(size: 15, weight: .bold))
                    .frame(width: 22, height: 22)
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.circle)
            .controlSize(.extraLarge)
            .tint(ac.power ? .accentColor : .secondary)
        }
    }

    private var tempCard: some View {
        HStack {
            stepButton("minus") { ac.nudgeTarget(by: -1) }
                .disabled(ac.target <= ac.minTemp)
            Spacer()
            VStack(spacing: 2) {
                Text("\(ac.target)°")
                    .font(.system(size: 56, weight: .semibold, design: .rounded))
                    .contentTransition(.numericText())
                    .animation(.snappy, value: ac.target)
                if let r = ac.room {
                    Text("Room \(r, specifier: "%.1f")°")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            stepButton("plus") { ac.nudgeTarget(by: 1) }
                .disabled(ac.target >= ac.maxTemp)
        }
        .padding(.vertical, 18)
        .padding(.horizontal, 20)
        .glassEffect(.regular, in: .rect(cornerRadius: 26))
    }

    private func stepButton(_ symbol: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 22, weight: .medium))
                .frame(width: 30, height: 30)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .controlSize(.large)
    }

    private var modeRow: some View {
        GlassEffectContainer(spacing: 7) {
            HStack(spacing: 7) {
                ForEach(ac.modes, id: \.key) { m in
                    chip(active: ac.mode == m.key) {
                        ac.setMode(m.key)
                    } label: {
                        VStack(spacing: 4) {
                            Image(systemName: m.icon).font(.system(size: 16))
                            Text(m.name).font(.system(size: 11))
                        }
                    }
                }
            }
        }
    }

    private var fanRow: some View {
        GlassEffectContainer(spacing: 7) {
            HStack(spacing: 7) {
                ForEach(ac.fans, id: \.key) { f in
                    chip(active: ac.fan == f.key) {
                        ac.setFan(f.key)
                    } label: {
                        Text(f.name).font(.system(size: 12)).padding(.vertical, 3)
                    }
                }
            }
        }
    }

    private var togglesRow: some View {
        HStack(spacing: 10) {
            glassToggle("Eco", "leaf", on: ac.eco) { ac.toggleEco() }
            glassToggle("Sleep", "moon", on: ac.sleep) { ac.toggleSleep() }
        }
    }

    private func glassToggle(_ title: String, _ icon: String, on: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 14))
                Text(title).font(.system(size: 13, weight: .medium))
                Spacer()
                Circle()
                    .fill(on ? Color.green : Color.secondary.opacity(0.4))
                    .frame(width: 9, height: 9)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .foregroundStyle(on ? .primary : .secondary)
        .glassEffect(on ? .regular.tint(.green.opacity(0.25)).interactive() : .regular.interactive(),
                     in: .rect(cornerRadius: 16))
    }

    @ViewBuilder
    private func chip<L: View>(active: Bool, action: @escaping () -> Void, @ViewBuilder label: () -> L) -> some View {
        Button(action: action) {
            label()
                .frame(maxWidth: .infinity)
                .padding(.vertical, 9)
        }
        .buttonStyle(.plain)
        .foregroundStyle(active ? AnyShapeStyle(.white) : AnyShapeStyle(.primary))
        .glassEffect(active ? .regular.tint(.accentColor).interactive() : .regular.interactive(),
                     in: .rect(cornerRadius: 15))
    }

    @ViewBuilder
    private func picker<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .padding(.leading, 4)
            content()
        }
    }
}
