//
//  GameDllOverrides.swift
//  Madeira
//
//  Game details › DLL overrides: which copy of a DLL Wine loads for this game,
//  the game's own (native) or Wine's (builtin), chosen from a list instead of
//  writing env.WINEDLLOVERRIDES by hand. The list is that one line of the game's
//  config file, read and written back; every other line stays as it is.
//  A DLL that ships in the game's folder (a d3d9.dll wrapper, Mesa's opengl32.dll)
//  can be picked from a list of the folder's DLLs.
//
//  Everything above "MARK: Views" is Foundation only:
//  tests/host/check-dll-overrides.py compiles it with a test harness.
//

import Foundation
import SwiftUI

/// WINEDLLOVERRIDES as Wine reads it: `name[,name]=mode[;...]`, where mode is
/// n, b, n,b, b,n or empty (disabled).
struct DllOverrides: Equatable {
    struct Entry: Equatable, Identifiable {
        var name: String
        /// Wine's letters as written, without spaces: "n", "b", "n,b", "b,n" or "" (disabled).
        var mode: String
        var id: String { name.lowercased() }
    }

    /// The choices offered, in Wine's letters, with what they mean.
    struct Mode { let mode: String; let title: String }
    static let modes = [
        Mode(mode: "n,b", title: "Game's own, then Wine's"),
        Mode(mode: "n", title: "Game's own only"),
        Mode(mode: "b,n", title: "Wine's, then game's own"),
        Mode(mode: "b", title: "Wine's only"),
        Mode(mode: "", title: "Off (not loaded)"),
    ]

    static func title(_ mode: String) -> String {
        modes.first { $0.mode == mode }?.title ?? "Other (\(mode))"
    }

    var entries: [Entry] = []
    /// Parts Wine's syntax does not explain (no "="), written back unchanged.
    var unparsed: [String] = []

    init(entries: [Entry] = []) { self.entries = entries }

    init(_ value: String) {
        for part in value.split(separator: ";") {
            let chunk = part.trimmingCharacters(in: .whitespaces)
            if chunk.isEmpty { continue }
            guard let eq = chunk.firstIndex(of: "=") else { unparsed.append(chunk); continue }
            let mode = chunk[chunk.index(after: eq)...].filter { !$0.isWhitespace }.lowercased()
            for name in chunk[..<eq].split(separator: ",") {
                let n = name.trimmingCharacters(in: .whitespaces)
                if !n.isEmpty { set(n, mode) }
            }
        }
    }

    /// The value for WINEDLLOVERRIDES: one name per entry, in list order.
    var value: String {
        (entries.map { "\($0.name)=\($0.mode)" } + unparsed).joined(separator: ";")
    }

    /// Adds the DLL or changes its mode. ".dll" is dropped: Wine's names have no extension.
    mutating func set(_ name: String, _ mode: String) {
        let clean = Self.name(name)
        guard !clean.isEmpty else { return }
        if let i = entries.firstIndex(where: { $0.id == clean.lowercased() }) {
            entries[i].mode = mode
        } else {
            entries.append(Entry(name: clean, mode: mode))
        }
    }

    mutating func remove(_ name: String) {
        entries.removeAll { $0.id == Self.name(name).lowercased() }
    }

    static func name(_ raw: String) -> String {
        let t = raw.trimmingCharacters(in: .whitespaces)
        return t.lowercased().hasSuffix(".dll") ? String(t.dropLast(4)) : t
    }

    // MARK: the game's config

    static let key = "env.WINEDLLOVERRIDES"

    /// The overrides the config sets: its last env.WINEDLLOVERRIDES line, as the reader takes it.
    static func read(config: String) -> DllOverrides {
        var found = ""
        for line in config.components(separatedBy: "\n") {
            if let v = value(line) { found = v }
        }
        return DllOverrides(found)
    }

    /// The config with its env.WINEDLLOVERRIDES line set to these overrides (or removed
    /// when there are none). The last such line is replaced in place, earlier ones dropped;
    /// every other line, comment and blank stays.
    static func write(_ overrides: DllOverrides, into config: String) -> String {
        var lines = config.components(separatedBy: "\n")
        let hits = lines.indices.filter { value(lines[$0]) != nil }
        let new = overrides.value.isEmpty ? nil : "\(key) = \(overrides.value)"
        if let last = hits.last {
            let cr = lines[last].hasSuffix("\r") ? "\r" : ""
            if let new { lines[last] = new + cr } else { lines.remove(at: last) }
            for i in hits.dropLast().reversed() { lines.remove(at: i) }
        } else if let new {
            if lines.last == "" { lines.insert(new, at: lines.count - 1) } else { lines.append(new) }
        }
        return lines.joined(separator: "\n")
    }

    /// The value of an env.WINEDLLOVERRIDES line, or nil for any other line.
    private static func value(_ raw: String) -> String? {
        let line = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !line.hasPrefix("#"), let eq = line.firstIndex(of: "=") else { return nil }
        guard line[..<eq].trimmingCharacters(in: .whitespaces) == key else { return nil }
        return line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces)
    }

    // MARK: the game's folder

    /// The DLLs in the game's folder (two levels down), by name without ".dll", sorted, each once.
    static func candidates(drive: URL, gameFolder: String, limit: Int = 300) -> [String] {
        guard !gameFolder.isEmpty else { return [] }
        let folder = drive.appendingPathComponent(gameFolder, isDirectory: true)
        guard let walker = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: [.isRegularFileKey],
                                                          options: [.skipsHiddenFiles, .skipsPackageDescendants]) else { return [] }
        var seen = Set<String>(), found: [String] = []
        for case let url as URL in walker {
            if found.count >= limit { break }
            if walker.level > 2 { walker.skipDescendants(); continue }
            guard url.pathExtension.lowercased() == "dll" else { continue }
            let n = url.deletingPathExtension().lastPathComponent
            if seen.insert(n.lowercased()).inserted { found.append(n) }
        }
        return found.sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }

    /// The folder under drive_c that holds the game: the program's folder, or the
    /// entry's own path when it is a folder.
    static func gameFolder(relativePath: String, isDirectory: Bool) -> String {
        if isDirectory { return relativePath }
        return relativePath.split(separator: "/").dropLast().joined(separator: "/")
    }
}

// MARK: Views

/// Game details › DLL overrides: the game's overrides, each with its mode, and "Add DLL".
struct GameDllOverridesSection: View {
    let windowsPath: String
    let gameFolder: String
    /// Called after the config file changes, so the details page re-reads it.
    var changed: () -> Void = {}
    @State private var overrides = DllOverrides()

    var body: some View {
        Section {
            ForEach(overrides.entries) { entry in
                Picker(selection: Binding(get: { entry.mode }, set: { mode in
                    overrides.set(entry.name, mode); save()
                })) {
                    ForEach(DllOverrides.modes, id: \.mode) { Text($0.title).tag($0.mode) }
                    if !DllOverrides.modes.contains(where: { $0.mode == entry.mode }) {
                        Text(DllOverrides.title(entry.mode)).tag(entry.mode)
                    }
                } label: {
                    Text(entry.name).font(.callout.monospaced())
                }
            }
            .onDelete { offsets in
                for i in offsets.map({ overrides.entries[$0].name }) { overrides.remove(i) }
                save()
            }
            NavigationLink {
                DllPicker(gameFolder: gameFolder, added: Set(overrides.entries.map(\.id))) { name in
                    overrides.set(name, "n,b"); save()
                }
            } label: {
                Label("Add DLL", systemImage: "plus")
            }
        } footer: {
            Text("Which copy of a DLL Wine loads for this game: the game's own (from its folder, like a d3d9.dll fix) or Wine's. Applies at the game's next start. Swipe left to remove one. Saved in this game's config as env.WINEDLLOVERRIDES.")
        }
        .onAppear { overrides = DllOverrides.read(config: GameProfile(windowsPath: windowsPath).text) }
    }

    private func save() {
        let file = GameProfile(windowsPath: windowsPath)
        let text = DllOverrides.write(overrides, into: file.text)
        file.text = text
        LogStore.shared.log("[dll-overrides] \(DllOverrides.key) = \(overrides.value)")
        changed()
    }
}

/// The DLLs in the game's folder, or any name typed in, to add one.
struct DllPicker: View {
    let gameFolder: String
    let added: Set<String>
    let pick: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var found: [String]?
    @State private var typed = ""

    var body: some View {
        List {
            Section {
                HStack {
                    TextField("Name, like d3d9", text: $typed)
                        .font(.callout.monospaced()).autocorrectionDisabled().textInputAutocapitalization(.never)
                        .onSubmit(add)
                    Button("Add", action: add).disabled(DllOverrides.name(typed).isEmpty)
                }
            } footer: {
                Text("Any DLL name, with or without .dll.")
            }
            Section("In the game's folder") {
                if let found {
                    if found.isEmpty { Text("No DLLs in the game's folder.").foregroundStyle(.secondary) }
                    ForEach(found, id: \.self) { name in
                        Button {
                            pick(name); dismiss()
                        } label: {
                            HStack {
                                Text(name + ".dll").font(.callout.monospaced()).foregroundStyle(.primary)
                                Spacer()
                                if added.contains(name.lowercased()) { Image(systemName: "checkmark").foregroundStyle(.secondary) }
                            }
                        }
                        .disabled(added.contains(name.lowercased()))
                    }
                } else {
                    HStack { ProgressView(); Text("Looking for DLLs").foregroundStyle(.secondary) }
                }
            }
        }
        .navigationTitle("Add DLL").navigationBarTitleDisplayMode(.inline)
        .task {
            guard found == nil else { return }
            let folder = gameFolder, drive = LibraryModel.drive
            found = await Task.detached(priority: .userInitiated) { DllOverrides.candidates(drive: drive, gameFolder: folder) }.value
        }
    }

    private func add() {
        let name = DllOverrides.name(typed)
        guard !name.isEmpty else { return }
        pick(name); dismiss()
    }
}
