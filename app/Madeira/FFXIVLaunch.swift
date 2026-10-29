// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 Madeira contributors
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
// Play for Final Fantasy XIV: a library entry for game\ffxiv_dx11.exe asks for the
// Square Enix sign-in (FFXIVSignInView), signs in with FFXIVLogin and starts the
// game with the session as this launch's arguments only (LibraryEntry's transient
// arguments, as an Epic game's code). The password stays in this device's Keychain
// only when the player turns on Remember; the one-time password is asked every time.
// docs/FFXIV.md.

import CryptoKit
import Foundation
import Security
import SwiftUI

@MainActor
enum FFXIVLaunch {
    /// The install folder (with boot and game) of an entry that starts
    /// game\ffxiv_dx11.exe, or nil. A Steam entry has Steam's own launch.
    static func installRoot(_ entry: LibraryEntry, drive: URL = LibraryModel.drive) -> URL? {
        guard entry.desktop != true, entry.steamAppID == nil, entry.epicAppName == nil else { return nil }
        let parts = entry.launchRelativePath.split(separator: "/").map(String.init)
        guard parts.count >= 2, parts[parts.count - 1].lowercased() == "ffxiv_dx11.exe",
              parts[parts.count - 2].lowercased() == "game" else { return nil }
        return parts.dropLast(2).reduce(drive) { $0.appendingPathComponent($1, isDirectory: true) }
    }

    /// Four random bytes made once, for the launcher's computer id.
    static var computerID: String {
        let key = "ffxiv.computerID"
        if let saved = UserDefaults.standard.string(forKey: key), saved.count == 10 { return saved }
        let id = FFXIVFormat.computerID((0..<4).map { _ in UInt8.random(in: 0...255) })
        UserDefaults.standard.set(id, forKey: key)
        return id
    }

    /// Signs in and sets the entry's arguments for this launch.
    static func prepare(_ entry: LibraryEntry, id: String, password: String, oneTimePassword: String) async throws {
        guard let root = installRoot(entry) else { throw FFXIVLoginError.invalid("not the game") }
        let install = try await Task.detached { try FFXIVInstall.read(root: root, sha1: FFXIVLaunch.sha1) }.value
        let session = try await FFXIVLogin.shared.signIn(id: id, password: password, oneTimePassword: oneTimePassword,
                                                         install: install, computerID: computerID)
        LibraryEntry.setTransientArguments(FFXIVFormat.gameArguments(session, gameVersion: install.gameVersion), for: entry.id)
        FFXIVLog.event("[ffxiv] signed in region=\(session.region) maxex=\(session.maxExpansion) ver=\(install.gameVersion)")
    }

    /// A boot program's SHA-1, read in 1 MB pieces off the main actor.
    nonisolated static func sha1(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = Insecure.SHA1()
        while let piece = try handle.read(upToCount: 1 << 20), !piece.isEmpty { hasher.update(data: piece) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

/// The Square Enix ID (UserDefaults) and, with Remember on, its password (this
/// device's Keychain, never synchronised).
enum FFXIVAccountStore {
    private static let service = "madeira.ffxiv.password"
    private static let idKey = "ffxiv.squareEnixID"

    static var savedID: String { UserDefaults.standard.string(forKey: idKey) ?? "" }

    static func password(for id: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecAttrAccount as String: id, kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(id: String, password: String?) {
        UserDefaults.standard.set(id, forKey: idKey)
        forget()
        guard let password else { return }
        let item: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                   kSecAttrAccount as String: id, kSecValueData as String: Data(password.utf8),
                                   kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
                                   kSecAttrSynchronizable as String: false]
        SecItemAdd(item as CFDictionary, nil)
    }

    /// Every saved password (one account at a time).
    static func forget() {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary)
    }
}

struct FFXIVSignInView: View {
    let entry: LibraryEntry
    let onReady: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var id = FFXIVAccountStore.savedID
    @State private var password = FFXIVAccountStore.password(for: FFXIVAccountStore.savedID) ?? ""
    @State private var oneTimePassword = ""
    @State private var remember = FFXIVAccountStore.password(for: FFXIVAccountStore.savedID) != nil
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Square Enix ID", text: $id)
                        .textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("Password", text: $password).textContentType(.password)
                    TextField("One-time password (if you use one)", text: $oneTimePassword)
                        .textContentType(.oneTimeCode).keyboardType(.numberPad)
                    Toggle("Remember password on this device", isOn: $remember)
                } footer: {
                    Text("Madeira signs in to Square Enix the way the official launcher does and starts the game. Updates still install through the Final Fantasy XIV launcher (Settings › PC game launchers). Steam accounts are not supported yet.")
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
                Section {
                    Button(busy ? "Signing in…" : "Sign in and play") { signIn() }
                        .disabled(busy || id.isEmpty || password.isEmpty)
                }
            }
            .navigationTitle("Final Fantasy XIV")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }

    private func signIn() {
        busy = true; error = nil
        Task { @MainActor in
            defer { busy = false }
            do {
                try await FFXIVLaunch.prepare(entry, id: id, password: password, oneTimePassword: oneTimePassword)
                FFXIVAccountStore.save(id: id.trimmingCharacters(in: .whitespacesAndNewlines), password: remember ? password : nil)
                dismiss()
                onReady()
            } catch {
                self.error = error.localizedDescription
                FFXIVLog.event("[ffxiv] not started: \((error as? FFXIVLoginError).map { "\($0)".prefix(40) } ?? "network")")
            }
        }
    }
}
