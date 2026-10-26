// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

// What Valve's client is downloading or installing while a Dock start waits, in
// plain words for the starting screen ("Downloading Steamworks Common
// Redistributables: 180 MB of 412 MB (44%)"). The host only reports that Steam
// is busy (launch-update-wait); the client itself writes each update's stages to
// <Steam>/logs/content_log.txt and its byte counts to the app's
// appmanifest_<appid>.acf. Both are only read, never written. Only the part of
// content_log.txt written since the start began is read, so an old update from an
// earlier session is never shown as running.

// MARK: - Rules (Foundation only; tests/host/check-steam-activity.py compiles this part)

enum SteamActivity {
    /// One app's update as content_log.txt tells it, newest state last.
    struct Update: Equatable {
        var appID: Int
        /// "state changed" flags (Update Running, Update Started) and the newer
        /// "update changed" ones (Downloading, Staging), which name the stage.
        var state: [String] = []
        var steps: [String] = []
        var finished = false
        var flags: [String] { state + steps }
    }

    /// The updates content_log.txt `text` mentions, the most recently active last.
    /// Lines: "[2026-10-26 04:20:13] AppID 228980 state changed : Update Running,Update Started,"
    /// and "update changed :", "finished update", "update canceled".
    static func updates(_ text: String) -> [Update] {
        var updates: [Update] = []
        for raw in text.split(whereSeparator: { $0 == "\n" || $0 == "\r" }) {
            guard let r = raw.range(of: "AppID ") else { continue }
            let rest = raw[r.upperBound...]
            let digits = rest.prefix { $0.isNumber }
            guard let appID = Int(digits), appID > 0 else { continue }
            let event = rest.dropFirst(digits.count).drop { $0 == " " }
            var update = updates.last { $0.appID == appID } ?? Update(appID: appID)
            if event.hasPrefix("state changed :") || event.hasPrefix("update changed :") {
                let flags = event.drop { $0 != ":" }.dropFirst()
                    .split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                if event.hasPrefix("state changed :") {
                    update.state = flags
                    update.finished = !flags.contains { busyState($0) }
                    if update.finished { update.steps = [] }
                } else {
                    update.steps = flags
                    update.finished = false
                }
            } else if event.hasPrefix("finished update") || event.hasPrefix("update canceled") {
                update.finished = true
                update.state = []; update.steps = []
            } else if event.hasPrefix("update started") || event.hasPrefix("scheduler update") {
                update.finished = false
            } else {
                continue
            }
            updates.removeAll { $0.appID == appID }
            updates.append(update)
        }
        return updates
    }

    /// A state flag that means the app's update still runs.
    static func busyState(_ flag: String) -> Bool {
        flag.hasPrefix("Update") || flag.hasPrefix("Running") ||
            ["Downloading", "Staging", "Committing", "Validating", "Verifying", "Preallocating",
             "Reconfiguring", "Paused", "Suspended"].contains(flag)
    }

    /// What the update is doing, from its newest flags.
    enum Stage: Equatable { case queued, downloading, installing, checking, preparing, paused, setup, updating }

    static func stage(_ flags: [String]) -> Stage {
        let set = Set(flags)
        if set.contains("Paused") || set.contains("Suspended") { return .paused }
        if set.contains("Validating") || set.contains("Verifying") { return .checking }
        if flags.contains(where: { $0.localizedCaseInsensitiveContains("install script") }) { return .setup }
        if set.contains("Downloading") { return .downloading }
        if set.contains("Committing") || set.contains("Staging") { return .installing }
        if set.contains("Preallocating") || set.contains("Reconfiguring") { return .preparing }
        if set.contains("Update Queued") || (set.contains("Update Required") && !set.contains("Update Running")) {
            return .queued
        }
        return .updating
    }

    /// Byte counts from the app's manifest (AppState): downloaded and staged.
    struct Bytes: Equatable {
        var downloaded: UInt64 = 0
        var toDownload: UInt64 = 0
        var staged: UInt64 = 0
        var toStage: UInt64 = 0
    }

    /// The starting screen's line for the newest unfinished update; nil when none runs.
    static func line(_ updates: [Update], name: (Int) -> String?, bytes: (Int) -> Bytes?) -> String? {
        guard let update = updates.last(where: { !$0.finished }) else { return nil }
        let what = name(update.appID) ?? knownNames[update.appID] ?? "Steam content (App \(update.appID))"
        let counts = bytes(update.appID)
        switch stage(update.flags) {
        case .queued: return "Waiting in Steam's download queue: \(what)"
        case .paused: return "Steam paused the download of \(what)"
        case .checking: return "Checking the files of \(what)…"
        case .setup: return "Running the first-time setup of \(what)…"
        case .preparing: return "Making room on disk for \(what)…"
        case .downloading:
            return "Downloading \(what)" + progress(counts.map { ($0.downloaded, $0.toDownload) })
        case .installing:
            return "Installing \(what)" + progress(counts.map { ($0.staged, $0.toStage) })
        case .updating:
            return "Updating \(what)" + progress(counts.map { ($0.downloaded, $0.toDownload) })
        }
    }

    /// Apps Steam installs for games and that have no name of their own on disk.
    static let knownNames: [Int: String] = [228980: "Steamworks Common Redistributables"]

    /// ": 180 MB of 412 MB (44%)", or "…" when the counts say nothing.
    static func progress(_ pair: (done: UInt64, total: UInt64)?) -> String {
        guard let pair, pair.total > 0 else { return "…" }
        let done = min(pair.done, pair.total)
        return ": \(size(done)) of \(size(pair.total)) (\(done * 100 / pair.total)%)"
    }

    /// "412 MB", "1.4 GB".
    static func size(_ bytes: UInt64) -> String {
        let mb = Double(bytes) / 1_048_576
        if mb < 1024 { return "\(Int(mb.rounded())) MB" }
        return String(format: "%.1f GB", mb / 1024)
    }

    /// The manifest's AppState fields Steam keeps the counts in.
    static func bytes(_ state: [String: String]) -> Bytes {
        func value(_ key: String) -> UInt64 { state[key.lowercased()].flatMap { UInt64($0) } ?? 0 }
        return Bytes(downloaded: value("BytesDownloaded"), toDownload: value("BytesToDownload"),
                     staged: value("BytesStaged"), toStage: value("BytesToStage"))
    }
}

// MARK: - Reading

/// The starting screen's reader: remembers where content_log.txt ended when the start
/// began, and reads only what Steam wrote after that (at most the last 256 KB).
struct SteamActivityReader {
    let contentLog: URL
    let libraries: [URL]
    private(set) var offset: UInt64

    init(clientRoot: URL, libraries: [URL]) {
        contentLog = clientRoot.appendingPathComponent("logs/content_log.txt")
        self.libraries = [clientRoot.appendingPathComponent("steamapps", isDirectory: true)] + libraries
        offset = ((try? FileManager.default.attributesOfItem(atPath: contentLog.path))?[.size] as? NSNumber)?.uint64Value ?? 0
    }

    func line() -> String? {
        guard let handle = try? FileHandle(forReadingFrom: contentLog) else { return nil }
        defer { try? handle.close() }
        guard let end = try? handle.seekToEnd() else { return nil }
        // A smaller file: Steam started a new log; all of it is new.
        let start = end < offset ? 0 : max(offset, end > 256 * 1024 ? end - 256 * 1024 : 0)
        guard end > start, (try? handle.seek(toOffset: start)) != nil,
              let data = try? handle.readToEnd() else { return nil }
        let updates = SteamActivity.updates(String(decoding: data, as: UTF8.self))
        guard !updates.isEmpty else { return nil }
        return SteamActivity.line(updates, name: { manifest($0)?["name"] },
                                  bytes: { manifest($0).map(SteamActivity.bytes) })
    }

    /// AppState of appmanifest_<appid>.acf from the first library that has it, flattened to text fields.
    private func manifest(_ appID: Int) -> [String: String]? {
        for library in libraries {
            let url = library.appendingPathComponent("appmanifest_\(appID).acf")
            guard let data = try? Data(contentsOf: url), data.count <= 1 << 20,
                  var parser = try? SteamKeyValues(data), let root = try? parser.read(),
                  let state = root["AppState"] else { continue }
            return state.fields.compactMapValues(\.string)
        }
        return nil
    }
}
