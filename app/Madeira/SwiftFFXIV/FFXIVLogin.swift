// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 Madeira contributors
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
// Final Fantasy XIV's sign-in, as Square Enix's own launcher does it, so a library
// Play starts ffxiv_dx11.exe straight away (docs/FFXIV.md):
//
// 1. ffxiv-login.square-enix.com's login page gives a one-use _STORED_ value;
// 2. login.send takes it with the Square Enix ID, password and one-time password and
//    answers with the session, the account's region and its newest expansion;
// 3. patch-gamever.ffxiv.com takes the session with the installed versions and the
//    boot programs' sizes and SHA-1s, and registers it when nothing needs patching;
// 4. the game starts with the session in its arguments (DEV.TestSID).
//
// Patching stays with Square Enix's launcher (LauncherSupport.swift) for now: when the
// server lists patches, the player updates there and plays here again. A Steam
// account's sign-in needs a Steam ticket Madeira does not make, so it is refused.
//
// Written for Madeira from the protocol XIVLauncher documents (goatcorp, GPL-3.0); no
// code is taken from it. Foundation only, so the host tests compile it.

import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum FFXIVLoginError: LocalizedError, Equatable {
    case missingID, missingPassword
    case wrongSignIn(String)
    case steamAccount
    case notPlayable, termsNotAccepted
    case needsGamePatch(Int), needsBootPatch, versionGone
    case badVersionFiles(String)
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .missingID: return "Enter your Square Enix ID."
        case .missingPassword: return "Enter your password."
        case .wrongSignIn(let message):
            return message.isEmpty ? "Square Enix did not accept the sign-in. Check the ID, password and one-time password." : message
        case .steamAccount:
            return "This is a Steam account. Madeira cannot sign in to Final Fantasy XIV for Steam yet."
        case .notPlayable: return "This account has no active Final Fantasy XIV service (subscription or free trial)."
        case .termsNotAccepted: return "Accept Square Enix's terms in the official launcher once, then play here."
        case .needsGamePatch(let count):
            return "Final Fantasy XIV has \(count) update\(count == 1 ? "" : "s") to install. Open the Final Fantasy XIV launcher in the library to update, then play here again."
        case .needsBootPatch:
            return "The Final Fantasy XIV launcher needs an update. Open it from the library once, then play here again."
        case .versionGone: return "Square Enix no longer serves this game version. Open the Final Fantasy XIV launcher to update."
        case .badVersionFiles(let file): return "The game's version file \(file) is damaged. Repair the game in the official launcher."
        case .invalid(let what): return "Square Enix's sign-in answered in a way Madeira does not understand (\(what))."
        }
    }
}

/// The account's game session, for one launch.
struct FFXIVSession: Equatable, Sendable {
    var sessionID: String
    var region: Int
    var maxExpansion: Int
}

/// What the sign-in reads from the installed game: the versions and the boot programs.
struct FFXIVInstall: Sendable {
    static let baseVersion = "2012.01.01.0000.0000"
    static let bootPrograms = ["ffxivboot.exe", "ffxivboot64.exe", "ffxivlauncher64.exe", "ffxivupdater64.exe"]

    var bootVersion: String
    var gameVersion: String
    /// ex1.ver, ex2.ver, ... as far as the game folder has them.
    var expansionVersions: [String]
    /// "size/sha1" of each boot program, in bootPrograms' order.
    var bootHashes: [String]

    /// Reads the install at root (the folder with boot and game). sha1 gives a file's
    /// SHA-1 in lower-case hex (CryptoKit in the app).
    static func read(root: URL, sha1: (URL) throws -> String) throws -> FFXIVInstall {
        let manager = FileManager.default
        func version(_ relative: String) throws -> String {
            let url = root.appendingPathComponent(relative)
            guard let data = manager.contents(atPath: url.path) else { return baseVersion }
            guard let text = String(data: data, encoding: .utf8) else { throw FFXIVLoginError.badVersionFiles(relative) }
            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return baseVersion }
            guard FFXIVFormat.validVersion(text) else { throw FFXIVLoginError.badVersionFiles(relative) }
            return text
        }
        let boot = try version("boot/ffxivboot.ver")
        let game = try version("game/ffxivgame.ver")
        var expansions: [String] = []
        for n in 1...20 {
            let folder = root.appendingPathComponent("game/sqpack/ex\(n)", isDirectory: true)
            guard manager.fileExists(atPath: folder.path) else { break }
            expansions.append(try version("game/sqpack/ex\(n)/ex\(n).ver"))
        }
        var hashes: [String] = []
        for program in bootPrograms {
            let url = root.appendingPathComponent("boot/" + program)
            guard let size = (try? manager.attributesOfItem(atPath: url.path))?[.size] as? NSNumber else {
                throw FFXIVLoginError.badVersionFiles("boot\\" + program)
            }
            hashes.append("\(size.int64Value)/\(try sha1(url))")
        }
        return FFXIVInstall(bootVersion: boot, gameVersion: game, expansionVersions: expansions, bootHashes: hashes)
    }
}

/// The text formats of the sign-in, kept apart from the network for the host tests.
enum FFXIVFormat {
    static let loginTop = "https://ffxiv-login.square-enix.com/oauth/ffxivarr/login/top"
    static let loginSend = "https://ffxiv-login.square-enix.com/oauth/ffxivarr/login/login.send"
    static let gameVersionServer = "https://patch-gamever.ffxiv.com/http/win32/ffxivneo_release_game/"
    static let patcherAgent = "FFXIV PATCH CLIENT"
    /// Square Enix's launcher page, sent as the login page's referrer.
    static let frontierPage = "https://launcher.finalfantasyxiv.com/v650/index.html"
    /// The launcher's answer for "start again through Steam".
    static let restartup = "window.external.user(\"restartup\");"

    /// 2024.07.23.0000.0001 and the like.
    static func validVersion(_ text: String) -> Bool {
        !text.isEmpty && text.count < 64 && text.allSatisfy { $0.isASCII && ($0.isNumber || $0 == ".") }
    }

    /// The launcher's user agent carries a computer id: a checksum byte (minus the sum
    /// of the other four) and four bytes. Madeira's four are random, made once.
    static func computerID(_ four: [UInt8]) -> String {
        precondition(four.count == 4)
        let sum = four.reduce(0) { $0 &+ $1 }
        return ([0 &- sum] + four).map { String(format: "%02x", $0) }.joined()
    }

    static func userAgent(computerID: String) -> String { "SQEXAuthor/2.0.0(Windows 6.2; ja-jp; \(computerID))" }

    static func topURL(region: Int = 3, freeTrial: Bool = false) -> URL {
        URL(string: "\(loginTop)?lng=en&rgn=\(region)&isft=\(freeTrial ? 1 : 0)&cssmode=1&isnew=1&launchver=3")!
    }

    static func referer(at date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd-HH-mm"
        return "\(frontierPage)?rc_lang=en_gb&time=\(formatter.string(from: date))"
    }

    private static func first(_ pattern: String, in text: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)), match.numberOfRanges > 1,
              let range = Range(match.range(at: 1), in: text) else { return nil }
        return String(text[range])
    }

    /// The login page's one-use value: <input type="hidden" name="_STORED_" value="...">.
    static func stored(in page: String) -> String? {
        guard let value = first(#"<\s*input [^>]*name="_STORED_"[^>]*value="([^"]*)""#, in: page), !value.isEmpty else { return nil }
        return value
    }

    struct LoginAnswer: Equatable {
        var sessionID: String
        var region: Int
        var termsAccepted: Bool
        var playable: Bool
        var maxExpansion: Int
    }

    /// login.send's answer: window.external.user("login=auth,ok,sid,<sid>,terms,<0|1>,region,<n>,
    /// etmadd,<n>,playable,<0|1>,ps3pkg,<n>,maxex,<n>,product,<n>");
    static func loginAnswer(in page: String) -> LoginAnswer? {
        guard let text = first(#"window\.external\.user\("login=auth,ok,(.*)"\);"#, in: page) else { return nil }
        let fields = text.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
        guard fields.count > 13, let region = Int(fields[5]), let maxExpansion = Int(fields[13]),
              !fields[1].isEmpty, fields[1].allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) else { return nil }
        return LoginAnswer(sessionID: fields[1], region: region, termsAccepted: fields[3] != "0",
                           playable: fields[9] != "0", maxExpansion: maxExpansion)
    }

    /// Square Enix's own words for a refused sign-in: login=auth,ng,err,<message>.
    static func loginRefusal(in page: String) -> String? {
        guard let message = first(#"window\.external\.user\("login=auth,ng,err,([^"]*)"\);"#, in: page) else { return nil }
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : String(trimmed.prefix(300))
    }

    static func form(_ fields: [(String, String)]) -> Data {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._*")
        let body = fields.map { key, value in
            let encoded = value.unicodeScalars.map { scalar -> String in
                if scalar == " " { return "+" }
                if scalar.isASCII, allowed.contains(scalar) { return String(scalar) }
                return String(scalar).utf8.map { String(format: "%%%02X", $0) }.joined()
            }.joined()
            return key + "=" + encoded
        }.joined(separator: "&")
        return Data(body.utf8)
    }

    /// What patch-gamever checks: the boot version and programs, then each expansion
    /// the account has, one line each.
    static func versionReport(_ install: FFXIVInstall, maxExpansion: Int) -> String {
        var report = install.bootVersion + "="
        report += zip(FFXIVInstall.bootPrograms, install.bootHashes).map { "\($0)/\($1)" }.joined(separator: ",") + "\n"
        if maxExpansion >= 1 {
            for n in 1...maxExpansion {
                let version = n <= install.expansionVersions.count ? install.expansionVersions[n - 1] : FFXIVInstall.baseVersion
                report += "ex\(n)\t\(version)\n"
            }
        }
        return report
    }

    /// The patch list's entries: one per non-empty line after the header lines
    /// (--Boundary, Content-Type and the like). Only the count is used.
    static func patchCount(_ body: String) -> Int {
        body.split(whereSeparator: \.isNewline).filter { line in
            let fields = line.split(separator: "\t")
            return fields.count >= 5 && fields.contains(where: { $0.hasPrefix("http://") || $0.hasPrefix("https://") })
        }.count
    }

    /// ffxiv_dx11.exe's arguments for the session. language: 0 Japanese, 1 English,
    /// 2 German, 3 French.
    static func gameArguments(_ session: FFXIVSession, gameVersion: String, language: Int = 1) -> String {
        [("DEV.DataPathType", "1"), ("DEV.MaxEntitledExpansionID", String(session.maxExpansion)),
         ("DEV.TestSID", session.sessionID), ("DEV.UseSqPack", "1"), ("SYS.Region", String(session.region)),
         ("language", String(language)), ("resetConfig", "0"), ("ver", gameVersion)]
            .map { "\($0)=\($1)" }.joined(separator: " ")
    }
}

actor FFXIVLogin {
    static let shared = FFXIVLogin()

    private let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieAcceptPolicy = .never
        configuration.timeoutIntervalForRequest = 30
        return URLSession(configuration: configuration)
    }()

    /// Signs in and registers the session for the installed game.
    func signIn(id rawID: String, password: String, oneTimePassword: String, install: FFXIVInstall,
                computerID: String) async throws -> FFXIVSession {
        let id = rawID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { throw FFXIVLoginError.missingID }
        guard !password.isEmpty else { throw FFXIVLoginError.missingPassword }
        let agent = FFXIVFormat.userAgent(computerID: computerID)
        let top = FFXIVFormat.topURL()

        var request = URLRequest(url: top)
        request.setValue(agent, forHTTPHeaderField: "User-Agent")
        request.setValue(FFXIVFormat.referer(at: Date()), forHTTPHeaderField: "Referer")
        request.setValue("en-US", forHTTPHeaderField: "Accept-Language")
        request.setValue("_rsid=\"\"", forHTTPHeaderField: "Cookie")
        let page = try await text(request, step: "login-top")
        if page.contains(FFXIVFormat.restartup) { throw FFXIVLoginError.steamAccount }
        guard let stored = FFXIVFormat.stored(in: page) else { throw FFXIVLoginError.invalid("no login form") }

        request = URLRequest(url: URL(string: FFXIVFormat.loginSend)!)
        request.httpMethod = "POST"
        request.setValue(agent, forHTTPHeaderField: "User-Agent")
        request.setValue(top.absoluteString, forHTTPHeaderField: "Referer")
        request.setValue("en-US", forHTTPHeaderField: "Accept-Language")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        request.setValue("_rsid=\"\"", forHTTPHeaderField: "Cookie")
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = FFXIVFormat.form([("_STORED_", stored), ("sqexid", id), ("password", password),
                                             ("otppw", oneTimePassword.trimmingCharacters(in: .whitespaces))])
        let reply = try await text(request, step: "login-send")
        guard let answer = FFXIVFormat.loginAnswer(in: reply) else {
            FFXIVLog.event("[ffxiv] sign-in refused")
            throw FFXIVLoginError.wrongSignIn(FFXIVFormat.loginRefusal(in: reply) ?? "")
        }
        guard answer.playable else { throw FFXIVLoginError.notPlayable }
        guard answer.termsAccepted else { throw FFXIVLoginError.termsNotAccepted }

        request = URLRequest(url: URL(string: FFXIVFormat.gameVersionServer + install.gameVersion + "/" + answer.sessionID)!)
        request.httpMethod = "POST"
        request.setValue(FFXIVFormat.patcherAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("enabled", forHTTPHeaderField: "X-Hash-Check")
        request.httpBody = Data(FFXIVFormat.versionReport(install, maxExpansion: answer.maxExpansion).utf8)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw FFXIVLoginError.invalid("game-version") }
        let body = String(decoding: data, as: UTF8.self)
        FFXIVLog.event("[ffxiv] game version check http=\(http.statusCode) region=\(answer.region) maxex=\(answer.maxExpansion)")
        switch http.statusCode {
        case 409: throw FFXIVLoginError.needsBootPatch
        case 410: throw FFXIVLoginError.versionGone
        case 200..<300: break
        default: throw FFXIVLoginError.invalid("game-version http \(http.statusCode)")
        }
        guard http.value(forHTTPHeaderField: "X-Patch-Unique-Id")?.isEmpty == false else {
            throw FFXIVLoginError.invalid("no session id")
        }
        if !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw FFXIVLoginError.needsGamePatch(max(1, FFXIVFormat.patchCount(body)))
        }
        return FFXIVSession(sessionID: answer.sessionID, region: answer.region, maxExpansion: answer.maxExpansion)
    }

    private func text(_ request: URLRequest, step: String) async throws -> String {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw FFXIVLoginError.invalid("\(step) http \((response as? HTTPURLResponse)?.statusCode ?? 0)")
        }
        return String(decoding: data, as: UTF8.self)
    }
}

/// The log lines; never the password, the one-time password or the session.
enum FFXIVLog {
    static func event(_ message: String) { LogStore.shared.log(message) }
}
