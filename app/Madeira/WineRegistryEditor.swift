//
//  WineRegistryEditor.swift
//  Madeira
//
//  Settings › Registry: browse and change Wine's registry (system.reg and
//  user.reg in the prefix) without the Files app. Only while no session runs:
//  Wine keeps the registry in memory and writes it back when it exits, which
//  would undo an edit made meanwhile. The file is edited in place: a change
//  rewrites only the lines of the value or key it touches, so key timestamps,
//  #time= lines, comments and Wine's escaping elsewhere stay as they were.
//  The first change in each visit keeps a copy of the file as <name>.before-edit.
//
//  Everything above "MARK: Views" is Foundation only:
//  tests/host/check-registry-editor.py compiles it with a test harness.
//

import Foundation
import SwiftUI

/// One registry file in Wine's text format ("WINE REGISTRY Version 2").
struct WineRegistry {
    /// A value's data, as far as the editor understands it.
    enum Data: Equatable {
        case string(String)        // "text"           REG_SZ
        case expandable(String)    // str(2):"text"    REG_EXPAND_SZ
        case dword(UInt32)         // dword:0000000a   REG_DWORD
        case other(String)         // hex:…, hex(7):…, str(7):… shown as written, not editable

        var typeName: String {
            switch self {
            case .string: return "Text"
            case .expandable: return "Text with %variables%"
            case .dword: return "Number (DWORD)"
            case .other(let raw):
                if raw.hasPrefix("hex(7)") || raw.hasPrefix("str(7)") { return "Text list" }
                if raw.hasPrefix("hex(b)") { return "Number (QWORD)" }
                return "Binary"
            }
        }
        var editable: Bool { if case .other = self { return false } else { return true } }
        var display: String {
            switch self {
            case .string(let s), .expandable(let s): return s
            case .dword(let n): return "\(n) (0x\(String(n, radix: 16)))"
            case .other(let raw): return raw
            }
        }
    }

    struct Value: Identifiable, Equatable {
        /// "" is the key's default value (@).
        let name: String
        let data: Data
        /// The lines it takes in the file (more than one for a long hex value).
        let lines: Range<Int>
        var id: String { name.lowercased() }
    }

    struct Key: Identifiable {
        /// Components joined by "\", as Windows writes it, relative to the file's root.
        let path: String
        let header: Int
        /// The line after the key's last line (its values and #meta lines).
        let end: Int
        let values: [Value]
        var id: String { path.lowercased() }
        var name: String { path.split(separator: "\\").last.map(String.init) ?? path }
    }

    private(set) var lines: [String]
    private(set) var keys: [Key] = []

    init(text: String) {
        lines = text.components(separatedBy: "\n")
        index()
    }

    var text: String { lines.joined(separator: "\n") }

    func key(_ path: String) -> Key? {
        let id = path.lowercased()
        return keys.first { $0.id == id }
    }

    /// The direct subkeys of `path` ("" is the root), by name, including keys that only
    /// exist as part of a longer path. Sorted as regedit does, ignoring case.
    func subkeys(of path: String) -> [String] {
        let prefix = path.isEmpty ? "" : path.lowercased() + "\\"
        var seen = Set<String>(), out: [String] = []
        for key in keys where key.id.hasPrefix(prefix) && key.id.count > prefix.count {
            let rest = key.path.dropFirst(prefix.count)
            let name = String(rest.split(separator: "\\", maxSplits: 1, omittingEmptySubsequences: false).first ?? rest)
            if seen.insert(name.lowercased()).inserted { out.append(name) }
        }
        return out.sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }

    // MARK: changes

    /// Sets a value, adding the key (and the value) when missing.
    mutating func set(_ path: String, _ name: String, _ data: Data, now: Date = Date()) {
        if key(path) == nil { addKey(path, now: now) }
        guard let key = key(path) else { return }
        if let value = key.values.first(where: { $0.id == name.lowercased() }) {
            // The name keeps its own spelling.
            lines.replaceSubrange(value.lines, with: [Self.valueLine(value.name, data)])
        } else {
            lines.insert(Self.valueLine(name, data), at: Self.lastContentLine(lines, key) + 1)
        }
        index()
    }

    mutating func remove(_ path: String, value name: String) {
        guard let value = key(path)?.values.first(where: { $0.id == name.lowercased() }) else { return }
        lines.removeSubrange(value.lines)
        index()
    }

    /// Adds an empty key (its parents need no lines of their own: Wine creates them).
    mutating func addKey(_ path: String, now: Date = Date()) {
        guard key(path) == nil, !path.isEmpty else { return }
        let seconds = Int(now.timeIntervalSince1970)
        let filetime = (UInt64(max(seconds, 0)) + 11_644_473_600) * 10_000_000
        var block = ["[\(Self.escapeKey(path))] \(seconds)", "#time=\(String(filetime, radix: 16))"]
        // A blank line between keys, as Wine writes them; the file's last empty line stays last.
        let at = lines.last == "" ? lines.count - 1 : lines.count
        if at > 0, lines[at - 1] != "" { block.insert("", at: 0) }
        lines.insert(contentsOf: block, at: at)
        index()
    }

    /// Removes the key, its subkeys and their values.
    mutating func removeKey(_ path: String) {
        let id = path.lowercased()
        let doomed = keys.filter { $0.id == id || $0.id.hasPrefix(id + "\\") }
        for key in doomed.sorted(by: { $0.header > $1.header }) {
            var start = key.header
            // The blank line that separates it from the key before.
            if start > 0, lines[start - 1].trimmingCharacters(in: .whitespaces).isEmpty { start -= 1 }
            lines.removeSubrange(start..<key.end)
        }
        index()
    }

    private static func lastContentLine(_ lines: [String], _ key: Key) -> Int {
        var last = key.header
        for i in key.header..<key.end where !lines[i].trimmingCharacters(in: .whitespaces).isEmpty { last = i }
        return last
    }

    // MARK: reading the file

    private mutating func index() {
        var keys: [Key] = []
        var current: (path: String, header: Int)?
        var values: [Value] = []
        var i = 0
        func close(_ end: Int) {
            if let c = current { keys.append(Key(path: c.path, header: c.header, end: end, values: values)) }
            values = []
        }
        while i < lines.count {
            let line = lines[i]
            if line.hasPrefix("[") {
                close(i)
                if let path = Self.keyPath(line) { current = (path: path, header: i) } else { current = nil }
                i += 1
                continue
            }
            guard current != nil, line.hasPrefix("\"") || line.hasPrefix("@") else { i += 1; continue }
            var end = i + 1
            var joined = line.hasSuffix("\r") ? String(line.dropLast()) : line
            while joined.hasSuffix("\\"), end < lines.count {
                joined = String(joined.dropLast()) + lines[end].trimmingCharacters(in: .whitespacesAndNewlines)
                end += 1
            }
            if let parsed = Self.value(joined) { values.append(Value(name: parsed.0, data: parsed.1, lines: i..<end)) }
            i = end
        }
        close(lines.count)
        self.keys = keys
    }

    /// The key path of a "[path] timestamp" line.
    static func keyPath(_ line: String) -> String? {
        let chars = Array(line)
        var i = 1, raw = ""
        while i < chars.count {
            if chars[i] == "\\", i + 1 < chars.count { raw.append(chars[i]); raw.append(chars[i + 1]); i += 2; continue }
            if chars[i] == "]" { return unescape(raw) }
            raw.append(chars[i]); i += 1
        }
        return nil
    }

    /// The name and data of a value line ("name"=data or @=data), continuation lines joined.
    static func value(_ line: String) -> (String, Data)? {
        let chars = Array(line)
        var name = "", i = 0
        if chars.first == "@" {
            i = 1
        } else {
            guard chars.first == "\"" else { return nil }
            i = 1
            var raw = ""
            while i < chars.count, chars[i] != "\"" {
                if chars[i] == "\\", i + 1 < chars.count { raw.append(chars[i]); raw.append(chars[i + 1]); i += 2; continue }
                raw.append(chars[i]); i += 1
            }
            guard i < chars.count else { return nil }
            name = unescape(raw)
            i += 1
        }
        guard i < chars.count, chars[i] == "=" else { return nil }
        return (name, data(String(chars[(i + 1)...])))
    }

    static func data(_ raw: String) -> Data {
        if let s = quoted(raw) { return .string(s) }
        if raw.hasPrefix("str(2):"), let s = quoted(String(raw.dropFirst(7))) { return .expandable(s) }
        if raw.lowercased().hasPrefix("dword:"), let n = UInt32(raw.dropFirst(6), radix: 16) { return .dword(n) }
        return .other(raw)
    }

    /// The text of a "…" token that ends the line, unescaped.
    private static func quoted(_ raw: String) -> String? {
        guard raw.count >= 2, raw.hasPrefix("\""), raw.hasSuffix("\"") else { return nil }
        let inner = Array(raw.dropFirst().dropLast())
        // The closing quote must be the line's last character and not escaped.
        var i = 0
        while i < inner.count {
            if inner[i] == "\\" { i += 2; continue }
            if inner[i] == "\"" { return nil }
            i += 1
        }
        if i > inner.count { return nil }
        return unescape(String(inner))
    }

    // MARK: Wine's escaping

    /// Wine's parse_strW: \a \b \e \f \n \r \t \v, \x and up to 4 hex digits,
    /// up to 3 octal digits, and \ before any other character for that character.
    static func unescape(_ s: String) -> String {
        let chars = Array(s.unicodeScalars)
        var out = String.UnicodeScalarView()
        var i = 0
        func hexValue(_ c: Unicode.Scalar) -> UInt32? { UInt32(String(c), radix: 16) }
        while i < chars.count {
            let c = chars[i]
            guard c == "\\", i + 1 < chars.count else { out.append(c); i += 1; continue }
            let n = chars[i + 1]
            i += 2
            switch n {
            case "a": out.append("\u{07}")
            case "b": out.append("\u{08}")
            case "e": out.append("\u{1B}")
            case "f": out.append("\u{0C}")
            case "n": out.append("\n")
            case "r": out.append("\r")
            case "t": out.append("\t")
            case "v": out.append("\u{0B}")
            case "x":
                var v: UInt32 = 0, digits = 0
                while digits < 4, i < chars.count, let d = hexValue(chars[i]) { v = v * 16 + d; i += 1; digits += 1 }
                if digits == 0 { out.append("x") } else if let u = Unicode.Scalar(v) { out.append(u) }
            case "0"..."7":
                var v = n.value - 48, digits = 1
                while digits < 3, i < chars.count, ("0"..."7").contains(chars[i]) { v = v * 8 + chars[i].value - 48; i += 1; digits += 1 }
                if let u = Unicode.Scalar(v) { out.append(u) }
            default: out.append(n)
            }
        }
        return String(out)
    }

    /// Wine's dump_strW: \\ and \" (and the characters in `extra`) escaped, control
    /// characters as \n \r \t or octal, anything past ASCII as \x and 4 hex digits.
    static func escape(_ s: String, extra: Set<Unicode.Scalar> = ["\""]) -> String {
        var out = ""
        for c in s.unicodeScalars {
            switch c {
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\0": out += "\\0"
            default:
                if extra.contains(c) { out += "\\" + String(c) }
                else if c.value < 32 { out += "\\" + String(c.value, radix: 8) }
                else if c.value > 127 {
                    if c.value > 0xFFFF {
                        // Wine stores UTF-16: a pair of \x escapes.
                        let v = c.value - 0x10000
                        out += String(format: "\\x%04x\\x%04x", 0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF))
                    } else {
                        out += String(format: "\\x%04x", c.value)
                    }
                } else { out.unicodeScalars.append(c) }
            }
        }
        return out
    }

    /// A key path for its [ ] line: each name escaped, joined by an escaped "\".
    static func escapeKey(_ path: String) -> String {
        path.split(separator: "\\", omittingEmptySubsequences: false)
            .map { escape(String($0), extra: ["[", "]"]) }.joined(separator: "\\\\")
    }

    static func valueLine(_ name: String, _ data: Data) -> String {
        let left = name.isEmpty ? "@" : "\"\(escape(name))\""
        switch data {
        case .string(let s): return "\(left)=\"\(escape(s))\""
        case .expandable(let s): return "\(left)=str(2):\"\(escape(s))\""
        case .dword(let n): return "\(left)=dword:" + String(format: "%08x", n)
        case .other(let raw): return "\(left)=\(raw)"
        }
    }

    /// The registry root the file's keys are under, for the editor's titles.
    static func rootName(_ file: String) -> String {
        file == "user.reg" ? "HKEY_CURRENT_USER" : "HKEY_LOCAL_MACHINE"
    }
}

// MARK: Views

/// The prefix's two registry files, read once per visit and written on each change.
@MainActor
final class RegistryStore: ObservableObject {
    static let files = ["system.reg", "user.reg"]
    @Published private(set) var hives: [String: WineRegistry] = [:]
    @Published var error: String?
    private var loaded: [String: Foundation.Data] = [:]
    private var backedUp = Set<String>()
    let prefix: URL

    init(prefix: URL = MadeiraDock.prefix) { self.prefix = prefix }

    /// A Wine session writes its registry back when it ends.
    static var sessionRunning: Bool {
        LibraryModel.shared.current != nil || LibraryModel.shared.preparing != nil
            || wine_process_is_running() != 0 || wineserver_is_running() != 0
    }

    func load() async {
        let prefix = self.prefix, files = Self.files
        let read: [(String, Foundation.Data, WineRegistry)] = await Task.detached(priority: .userInitiated) {
            files.compactMap { name in
                guard let data = try? Foundation.Data(contentsOf: prefix.appendingPathComponent(name)) else { return nil }
                return (name, data, WineRegistry(text: String(decoding: data, as: UTF8.self)))
            }
        }.value
        for (name, data, hive) in read { loaded[name] = data; hives[name] = hive }
        if read.isEmpty { error = "Wine's registry is not there yet. Start a game or the Windows desktop once first." }
    }

    /// Applies a change to a file and writes it, unless a session runs or the file
    /// changed since it was read here.
    func change(_ file: String, _ edit: (inout WineRegistry) -> Void) {
        guard !Self.sessionRunning else {
            error = "Close the game or the Windows desktop first: Wine writes the registry back when it ends, which would undo the change."
            return
        }
        guard var hive = hives[file] else { return }
        let url = prefix.appendingPathComponent(file)
        guard let now = try? Foundation.Data(contentsOf: url), now == loaded[file] else {
            error = "\(file) changed since it was opened here, so nothing was saved. Close this page and open it again."
            return
        }
        edit(&hive)
        let out = Foundation.Data(hive.text.utf8)
        do {
            if backedUp.insert(file).inserted {
                let copy = url.appendingPathExtension("before-edit")
                try? FileManager.default.removeItem(at: copy)
                try FileManager.default.copyItem(at: url, to: copy)
            }
            try out.write(to: url, options: .atomic)
            loaded[file] = out
            hives[file] = hive
            error = nil
            LogStore.shared.log("[registry-editor] saved \(file)")
        } catch {
            self.error = "Not saved: \(error.localizedDescription)"
        }
    }
}

/// Settings › Registry: the two files, then keys, subkeys and values.
struct RegistryEditorView: View {
    @StateObject private var store = RegistryStore()
    @Environment(\.dismiss) private var dismiss
    @State private var running = RegistryStore.sessionRunning

    var body: some View {
        NavigationStack {
            List {
                if running {
                    Section {
                        Label("A game or the Windows desktop is running. You can look, but changes are saved only once it has closed, because Wine writes the registry back when it ends.",
                              systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    }
                }
                if let error = store.error { Section { Text(error).foregroundStyle(.red) } }
                Section {
                    ForEach(RegistryStore.files, id: \.self) { file in
                        if store.hives[file] != nil {
                            NavigationLink {
                                RegistryKeyView(store: store, file: file, path: "")
                            } label: {
                                LabeledContent(WineRegistry.rootName(file), value: file)
                            }
                        }
                    }
                    if store.hives.isEmpty && store.error == nil {
                        HStack { ProgressView(); Text("Reading the registry").foregroundStyle(.secondary) }
                    }
                } footer: {
                    Text("Wine's registry for every game. Changes are saved straight away; the first change to a file keeps a copy of it next to it, named system.reg.before-edit or user.reg.before-edit.")
                }
            }
            .navigationTitle("Registry").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { if store.hives.isEmpty { await store.load() } }
            .onAppear { running = RegistryStore.sessionRunning }
        }
    }
}

/// One key: its subkeys, then its values. Add with +, delete with a swipe.
struct RegistryKeyView: View {
    @ObservedObject var store: RegistryStore
    let file: String
    let path: String
    @State private var query = ""
    @State private var newKey = false
    @State private var newValue: WineRegistry.Data?
    @State private var newName = ""
    @State private var deleting: String?

    private var hive: WineRegistry? { store.hives[file] }
    private var title: String { path.isEmpty ? WineRegistry.rootName(file) : (path.split(separator: "\\").last.map(String.init) ?? path) }

    var body: some View {
        List {
            if let error = store.error { Section { Text(error).foregroundStyle(.red) } }
            if !path.isEmpty {
                Section { Text(WineRegistry.rootName(file) + "\\" + path).font(.caption.monospaced()).foregroundStyle(.secondary) }
            }
            if let hive {
                if query.isEmpty {
                    let subkeys = hive.subkeys(of: path)
                    if !subkeys.isEmpty {
                        Section("Keys") {
                            ForEach(subkeys, id: \.self) { name in
                                NavigationLink {
                                    RegistryKeyView(store: store, file: file, path: child(name))
                                } label: {
                                    Label(name, systemImage: "folder")
                                }
                                .swipeActions { Button("Delete", role: .destructive) { deleting = child(name) } }
                            }
                        }
                    }
                    if let key = hive.key(path), !key.values.isEmpty {
                        Section("Values") {
                            ForEach(key.values) { value in
                                NavigationLink {
                                    RegistryValueView(store: store, file: file, path: path, value: value)
                                } label: {
                                    RegistryValueRow(value: value)
                                }
                                .swipeActions {
                                    Button("Delete", role: .destructive) {
                                        store.change(file) { $0.remove(path, value: value.name) }
                                    }
                                }
                            }
                        }
                    } else if !path.isEmpty && subkeys.isEmpty {
                        Section { Text("This key is empty.").foregroundStyle(.secondary) }
                    }
                } else {
                    let found = matches(hive)
                    Section(found.isEmpty ? "No key matches" : "Keys") {
                        ForEach(found, id: \.self) { full in
                            NavigationLink {
                                RegistryKeyView(store: store, file: file, path: full)
                            } label: {
                                Text(full).font(.caption.monospaced())
                            }
                        }
                    }
                }
            }
        }
        .searchable(text: $query, prompt: "Key name")
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button("New key", systemImage: "folder.badge.plus") { newName = ""; newKey = true }
                    if !path.isEmpty {
                        Button("New text value", systemImage: "textformat") { newName = ""; newValue = .string("") }
                        Button("New number value", systemImage: "number") { newName = ""; newValue = .dword(0) }
                    }
                } label: { Image(systemName: "plus") }
            }
        }
        .alert("New key", isPresented: $newKey) {
            TextField("Name", text: $newName).autocorrectionDisabled().textInputAutocapitalization(.never)
            Button("Add") {
                let name = newName.trimmingCharacters(in: .whitespaces)
                if !name.isEmpty, !name.contains("\\") { store.change(file) { $0.addKey(child(name)) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: { Text(path.isEmpty ? "A key at the top of \(WineRegistry.rootName(file))." : "A key inside \(title).") }
        .alert("New value", isPresented: Binding(get: { newValue != nil }, set: { if !$0 { newValue = nil } })) {
            TextField("Name", text: $newName).autocorrectionDisabled().textInputAutocapitalization(.never)
            Button("Add") {
                let name = newName.trimmingCharacters(in: .whitespaces)
                if let data = newValue, !name.isEmpty { store.change(file) { $0.set(path, name, data) } }
                newValue = nil
            }
            Button("Cancel", role: .cancel) { newValue = nil }
        } message: { Text("Its value is set on the next page; tap the new value.") }
        .confirmationDialog("Delete \(deletingName)?",
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Delete key and everything in it", role: .destructive) {
                if let doomed = deleting { store.change(file) { $0.removeKey(doomed) } }
                deleting = nil
            }
        }
    }

    private func child(_ name: String) -> String { path.isEmpty ? name : path + "\\" + name }

    private var deletingName: String {
        guard let deleting else { return "" }
        return deleting.split(separator: "\\").last.map(String.init) ?? deleting
    }

    private func matches(_ hive: WineRegistry) -> [String] {
        let prefix = path.isEmpty ? "" : path.lowercased() + "\\"
        return Array(hive.keys.lazy
            .filter { $0.id.hasPrefix(prefix) && $0.name.localizedCaseInsensitiveContains(query) }
            .map(\.path).prefix(200))
    }
}

struct RegistryValueRow: View {
    let value: WineRegistry.Value
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value.name.isEmpty ? "(Default)" : value.name).font(.callout.monospaced())
            Text(value.data.display).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(2)
        }
    }
}

/// One value: its type and data, editable for text and numbers.
struct RegistryValueView: View {
    @ObservedObject var store: RegistryStore
    let file: String
    let path: String
    let value: WineRegistry.Value
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var hex = false

    var body: some View {
        Form {
            if let error = store.error { Section { Text(error).foregroundStyle(.red) } }
            Section {
                LabeledContent("Name", value: value.name.isEmpty ? "(Default)" : value.name)
                LabeledContent("Type", value: value.data.typeName)
            }
            Section {
                switch value.data {
                case .string, .expandable:
                    TextField("Text", text: $text, axis: .vertical)
                        .font(.callout.monospaced()).autocorrectionDisabled().textInputAutocapitalization(.never)
                case .dword:
                    TextField(hex ? "Hexadecimal" : "Number", text: $text)
                        .font(.callout.monospaced()).keyboardType(hex ? .asciiCapable : .numberPad)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                    Toggle("Hexadecimal", isOn: Binding(get: { hex }, set: { on in
                        if let n = number { text = on ? String(n, radix: 16) : String(n) }
                        hex = on
                    }))
                case .other(let raw):
                    Text(raw).font(.caption.monospaced()).textSelection(.enabled)
                }
            } header: { Text("Value") } footer: {
                if !value.data.editable { Text("This type is shown as Wine stores it and cannot be changed here.") }
                else if invalidNumber { Text("Not a number from 0 to 4294967295.").foregroundStyle(.red) }
            }
        }
        .navigationTitle(value.name.isEmpty ? "(Default)" : value.name).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if value.data.editable {
                ToolbarItem(placement: .confirmationAction) { Button("Save", action: save).disabled(newData == nil || newData == value.data) }
            }
        }
        .onAppear {
            switch value.data {
            case .string(let s), .expandable(let s): text = s
            case .dword(let n): text = String(n)
            case .other: break
            }
        }
    }

    private var invalidNumber: Bool {
        if case .dword = value.data { return number == nil }
        return false
    }

    private var number: UInt32? { UInt32(text.trimmingCharacters(in: .whitespaces), radix: hex ? 16 : 10) }

    private var newData: WineRegistry.Data? {
        switch value.data {
        case .string: return .string(text)
        case .expandable: return .expandable(text)
        case .dword: return number.map { .dword($0) }
        case .other: return nil
        }
    }

    private func save() {
        guard let data = newData else { return }
        store.change(file) { $0.set(path, value.name, data) }
        if store.error == nil { dismiss() }
    }
}
