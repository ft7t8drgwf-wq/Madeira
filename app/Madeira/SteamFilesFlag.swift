//
//  SteamFilesFlag.swift
//  Madeira
//
//  Game details › Steam: clears the "files missing" or "files corrupted" mark
//  Steam left in a game's install record (appmanifest_<appid>.acf, StateFlags
//  bits 32 and 128). With either bit set Valve's client refuses every start and
//  waits for an update that never comes, even when the files are fine. The
//  record's other text stays as it is; a copy is kept beside it first.
//

import Foundation
import SwiftUI

enum SteamFilesFlag {
    static let missing: UInt32 = 32
    static let corrupt: UInt32 = 128
    static let installed: UInt32 = 4

    static func record(appID: Int, steamApps: URL) -> URL {
        steamApps.appendingPathComponent("appmanifest_\(appID).acf")
    }

    /// The `"StateFlags" "<n>"` line's number and where the number sits.
    static func flags(in text: String) -> (value: UInt32, range: Range<String.Index>)? {
        guard let regex = try? NSRegularExpression(pattern: #"^\s*"StateFlags"\s+"(\d+)""#,
                                                   options: [.anchorsMatchLines, .caseInsensitive]),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let range = Range(match.range(at: 1), in: text),
              let value = UInt32(text[range]) else { return nil }
        return (value, range)
    }

    /// Set when the game is installed but Steam marked its files missing or corrupted.
    static func isMarked(_ value: UInt32) -> Bool {
        value & installed != 0 && value & (missing | corrupt) != 0
    }

    /// The record's text with both bits cleared, or nil when there is nothing to clear.
    static func cleared(_ text: String) -> String? {
        guard let found = flags(in: text), isMarked(found.value) else { return nil }
        var text = text
        text.replaceSubrange(found.range, with: String(found.value & ~(missing | corrupt)))
        return text
    }

    static func isMarked(appID: Int, steamApps: URL) -> Bool {
        guard let data = try? Data(contentsOf: record(appID: appID, steamApps: steamApps)), data.count <= 1 << 20,
              let text = String(data: data, encoding: .utf8), let found = flags(in: text) else { return false }
        return isMarked(found.value)
    }

    /// Rewrites the record without the mark; the first time, the old record is
    /// kept as `appmanifest_<appid>.acf.before-clear`.
    static func clear(appID: Int, steamApps: URL) throws {
        let url = record(appID: appID, steamApps: steamApps)
        let data = try Data(contentsOf: url)
        guard data.count <= 1 << 20, let text = String(data: data, encoding: .utf8),
              let fixed = cleared(text) else { return }
        let backup = url.appendingPathExtension("before-clear")
        if !FileManager.default.fileExists(atPath: backup.path) { try data.write(to: backup) }
        try Data(fixed.utf8).write(to: url, options: .atomic)
    }
}

// MARK: Views

/// Shown only while Steam's record carries the mark.
struct SteamFilesFlagRows: View {
    let appID: Int
    /// The game's drive-relative steamapps folder.
    let library: String
    @State private var marked = false
    @State private var confirm = false
    @State private var error: String?

    private var steamApps: URL { MadeiraDock.drive.appendingPathComponent(library, isDirectory: true) }

    static var sessionRunning: Bool {
        LibraryModel.shared.current != nil || LibraryModel.shared.preparing != nil
            || wine_process_is_running() != 0 || wineserver_is_running() != 0
    }

    var body: some View {
        Group {
            if marked {
                Button { confirm = true } label: {
                    Label("Clear \"files corrupted\" mark", systemImage: "checkmark.shield")
                }
                Text("Steam marked this game's files as missing or corrupted, so it won't start the game. If the files are fine, clearing the mark lets it start again.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
        }
        .task(id: appID) { await check() }
        .confirmationDialog("Clear the mark?", isPresented: $confirm, titleVisibility: .visible) {
            Button("Clear mark") { clear() }
        } message: {
            Text("Only do this if the game's files are really there. If files are missing, the game may crash; Steam will download them again at its next update.")
        }
    }

    private func check() async {
        let appID = appID, steamApps = steamApps
        marked = await Task.detached(priority: .utility) { SteamFilesFlag.isMarked(appID: appID, steamApps: steamApps) }.value
    }

    private func clear() {
        guard !Self.sessionRunning else {
            error = "Close the game first: Steam writes this record while it runs."
            return
        }
        do {
            try SteamFilesFlag.clear(appID: appID, steamApps: steamApps)
            SteamLog.event("[steam-files-flag] cleared app=\(appID)")
            error = nil
            marked = SteamFilesFlag.isMarked(appID: appID, steamApps: steamApps)
            SteamGamesModel.shared.refresh()
        } catch {
            self.error = "Couldn't change Steam's record: \(error.localizedDescription)"
        }
    }
}
