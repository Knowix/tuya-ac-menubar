import SwiftUI
import Foundation

// MARK: - Model

@MainActor
@Observable
final class ACModel {
    var power = false
    var mode = ""
    var fan = ""
    var target = 24
    var room: Double? = nil
    var reachable = true
    var eco = false
    var sleep = false
    var busy = false

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

    private let uv: String
    private let script: String

    init() {
        uv = Self.findUV()
        script = Self.findScript()
    }

    /// Locate the `uv` launcher. GUI apps don't inherit the shell PATH, so probe the usual spots.
    private static func findUV() -> String {
        let candidates = [
            "/opt/homebrew/bin/uv", "/usr/local/bin/uv",
            NSString(string: "~/.local/bin/uv").expandingTildeInPath,
            NSString(string: "~/.cargo/bin/uv").expandingTildeInPath,
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/env"
    }

    /// Prefer the `ac.py` bundled in the app; fall back to a dev checkout.
    private static func findScript() -> String {
        if let p = Bundle.main.path(forResource: "ac", ofType: "py") { return p }
        for d in ["~/Development/tuya-ac/ac.py", "~/Development/sendo-ac/ac.py"] {
            let e = NSString(string: d).expandingTildeInPath
            if FileManager.default.fileExists(atPath: e) { return e }
        }
        return NSString(string: "~/Development/sendo-ac/ac.py").expandingTildeInPath
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

    func refresh() async { await read() }

    func togglePower() async { await set(1, power ? "false" : "true") }
    func setTarget(_ c: Int) async { await set(2, "\(max(16, min(32, c)) * 10)") }
    func setMode(_ m: String) async { await set(4, m) }
    func setFan(_ f: String) async { await set(5, f) }
    func toggleEco() async { await set(8, eco ? "false" : "true") }
    func toggleSleep() async { await set(102, sleep ? "false" : "true") }

    private func set(_ dp: Int, _ value: String) async {
        busy = true
        _ = await shell(["set", "\(dp)", value])
        await read()
        busy = false
    }

    private func read() async {
        guard let out = await shell(["raw"]),
              let data = out.data(using: .utf8),
              let dps = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { reachable = false; return }
        reachable = true
        func b(_ k: String) -> Bool { (dps[k] as? Bool) ?? false }
        func i(_ k: String) -> Int? { (dps[k] as? NSNumber)?.intValue }
        power = b("1")
        if let t = i("2") { target = Int((Double(t) / 10).rounded()) }
        if let r = i("3") { room = Double(r) / 10 }
        mode = dps["4"] as? String ?? mode
        fan = dps["5"] as? String ?? fan
        eco = b("8")
        sleep = b("102")
    }

    private func shell(_ args: [String]) async -> String? {
        let uv = uv, script = script
        return await Task.detached {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: uv)
            // If uv wasn't found at an absolute path, go through `env` so PATH is consulted.
            let prefix = uv.hasSuffix("/env") ? ["uv", "run", "--quiet"] : ["run", "--quiet"]
            p.arguments = prefix + [script] + args
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = Pipe()
            do { try p.run() } catch { return nil }
            let d = pipe.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            return p.terminationStatus == 0 ? String(data: d, encoding: .utf8) : nil
        }.value
    }
}

// MARK: - App

@main
struct SendoACApp: App {
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
    @Bindable var ac: ACModel

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
        .opacity(ac.busy ? 0.6 : 1)
        .animation(.easeOut(duration: 0.15), value: ac.busy)
        .task { await ac.refresh() }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                await ac.refresh()
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Air Conditioner")
                    .font(.system(size: 16, weight: .semibold))
                Text(ac.statusLine)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                Task { await ac.togglePower() }
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
            stepButton("minus") { Task { await ac.setTarget(ac.target - 1) } }
            Spacer()
            VStack(spacing: 2) {
                Text("\(ac.target)°")
                    .font(.system(size: 56, weight: .semibold, design: .rounded))
                    .contentTransition(.numericText())
                if let r = ac.room {
                    Text("Room \(r, specifier: "%.1f")°")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            stepButton("plus") { Task { await ac.setTarget(ac.target + 1) } }
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
                        Task { await ac.setMode(m.key) }
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
                        Task { await ac.setFan(f.key) }
                    } label: {
                        Text(f.name).font(.system(size: 12)).padding(.vertical, 3)
                    }
                }
            }
        }
    }

    private var togglesRow: some View {
        HStack(spacing: 10) {
            glassToggle("Eco", "leaf", on: ac.eco) { Task { await ac.toggleEco() } }
            glassToggle("Sleep", "moon", on: ac.sleep) { Task { await ac.toggleSleep() } }
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
