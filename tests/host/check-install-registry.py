#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Madeira Dock: the "Registry" values of a game's Steam install script.

Synthetic data only: no Steam, Wine, iOS or credentials. Compiles production
Swift (app/Madeira/DockInstallers.swift plus DockGame from MadeiraDock.swift)
under AddressSanitizer and checks:
  * the reader: "InstallScript" > "Registry" > key > "string" | "dword", values
    directly or in language blocks (Steam's language, else english, else the
    first), %INSTALLDIR% expanded, other %NAME% values left out, sections
    outside "InstallScript" ignored, "Run Process" entries still read;
  * Wine's .reg text: escapes as wineserver writes them, both registry views,
    a new key section, missing values added, present values kept unless they
    follow %INSTALLDIR% and differ, a second write changes nothing;
  * writeRegistry() and prepare() in a synthetic prefix: system.reg written with
    a .madeira-bak copy, the log line, MADEIRA_DOCK_INSTALL_REGISTRY=0.
"""
from pathlib import Path
import os, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
SWIFTC = os.environ.get('SWIFTC') or shutil.which('swiftc') or str(Path.home() / '.local/share/swiftly/bin/swiftc')
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


dock = (app / 'MadeiraDock.swift').read_text(encoding='utf-8')
installers = (app / 'DockInstallers.swift').read_text(encoding='utf-8')

# ------------------------------------------------------------------ static rules
prep = installers[installers.index('    static func prepare('):]
prep = prep[:prep.index('\n    }\n')]
require('flag("MADEIRA_DOCK_INSTALL_REGISTRY")' in prep and
        prep.index('writeRegistry(game, drive: drive, prefix: prefix)') < prep.index('guard enabled else'),
        'prepare() writes the registry values (own switch) before the installer switch is read')
require('reg.exe' not in installers, 'the registry is written from the app, never by a batch')

# ------------------------------------------------------------------ compiled Swift
game_src = dock[dock.index('/// A game Steam\'s client has installed'):dock.index('/// Madeira Dock: a small headless host')]
stubs = r'''
import Foundation
#if canImport(Glibc)
import Glibc
#else
import Darwin
#endif
enum SteamSignIn {
    static func flag(_ name: String, default fallback: Bool) -> Bool { getenv(name).map { String(cString: $0) != "0" } ?? fallback }
}
enum MadeiraConfig {
    nonisolated(unsafe) static var values: [String: String] = [:]
    static func get(_ key: String) -> String? { values[key] }
    static var gameURL: URL? { nil }
}
struct LogEntry { enum Level { case info, success, error, debug } }
@MainActor final class LogStore {
    static let shared = LogStore()
    var lines: [String] = []
    func log(_ message: String, level: LogEntry.Level = .info) { lines.append(message) }
}
enum MadeiraDock { static let executable = "C:\\windows\\system32\\dockhost.exe" }
''' + game_src

checks = r'''
import Foundation
#if canImport(Glibc)
import Glibc
#else
import Darwin
#endif
var failures = 0
func require(_ condition: @autoclosure () -> Bool, _ label: String) {
    if condition() { print("PASS: " + label) } else { print("FAIL: " + label); failures += 1 }
}
func write(_ url: URL, _ text: String) throws {
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data(text.utf8).write(to: url)
}

let installDir = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Fallout New Vegas"
let script = """
"InstallScript"
{
    // Bethesda-style script: a language block per language, and a Run Process entry
    "Registry"
    {
        "HKEY_LOCAL_MACHINE\\\\Software\\\\Bethesda Softworks\\\\FalloutNV"
        {
            "string"
            {
                "english"
                {
                    "Installed Path"    "%INSTALLDIR%"
                    "Language"          "english"
                }
                "german"
                {
                    "Installed Path"    "%INSTALLDIR%"
                    "Language"          "german"
                }
            }
            "dword"
            {
                "Version"   "17"
                "Flags"     "0x10"
                "Broken"    "many"
            }
        }
        "HKEY_CURRENT_USER\\\\Software\\\\Fixture"
        {
            "string"
            {
                ""          "default"
                "Other"     "%SOMETHING%\\\\x"
                "Quoted"    "a \\"b\\" é1 \\\\c"
            }
        }
    }
    "Run Process"
    {
        "DirectX"
        {
            "HasRunKey"     "HKEY_LOCAL_MACHINE\\\\Software\\\\Valve\\\\Steam\\\\Apps\\\\22380"
            "process 1"     "%INSTALLDIR%\\\\Redist\\\\DXSETUP.exe"
        }
    }
}
"""
let notScript = """
"Settings" { "Registry" { "HKEY_LOCAL_MACHINE\\\\Software\\\\Nope" { "string" { "X" "y" } } } }
"""

@main struct Checks {
    @MainActor static func main() throws {
        // ---- reader
        let values = SteamInstallRegistry.values(script: Data(script.utf8), installDir: installDir)
        func find(_ name: String) -> SteamInstallValue? { values.first { $0.name == name } }
        require(find("Installed Path") == SteamInstallValue(hive: .machine, key: "Software\\Bethesda Softworks\\FalloutNV", name: "Installed Path",
                                                           data: .string(installDir + "\\"), followsInstall: true),
                "Installed Path: HKLM key, %INSTALLDIR% expanded with Steam's trailing backslash, follows the install")
        require(find("Language")?.data == .string("english"), "no language recorded: the english block")
        require(values.filter { $0.name == "Installed Path" }.count == 1, "one copy per value, not one per language block")
        let german = SteamInstallRegistry.values(script: Data(script.utf8), installDir: installDir, language: "German")
        require(german.first { $0.name == "Language" }?.data == .string("german"), "Steam's language picks its block")
        let french = SteamInstallRegistry.values(script: Data(script.utf8), installDir: installDir, language: "french")
        require(french.first { $0.name == "Language" }?.data == .string("english"), "a language without a block falls back to english")
        require(find("Version")?.data == .dword(17) && find("Flags")?.data == .dword(16) && find("Broken") == nil,
                "dwords: decimal and 0x hex read, an unreadable one left out")
        require(find("")?.hive == .user && find("")?.data == .string("default") && find("")?.followsInstall == false,
                "HKCU default value read, does not follow the install")
        require(find("Other") == nil, "an unknown %NAME% value is left out")
        let sub = SteamInstallRegistry.values(script: Data("\"InstallScript\" { \"Registry\" { \"HKEY_LOCAL_MACHINE\\\\Software\\\\X\" { \"string\" { \"Bin\" \"%INSTALLDIR%\\\\bin\" } } } }".utf8), installDir: installDir)
        require(sub.first?.data == .string(installDir + "\\bin"), "%INSTALLDIR%\\sub keeps one backslash")
        require(find("Quoted")?.data == .string("a \"b\" é1 \\c"), "VDF escapes read")
        require(SteamInstallRegistry.values(script: Data(notScript.utf8), installDir: installDir).isEmpty,
                "a Registry section outside InstallScript is ignored")
        require(SteamInstallScripts.entries(script: Data(script.utf8)).map { $0.0.name } == ["directx"],
                "Run Process entries are still read from the same script")

        // ---- Wine text
        require(SteamInstallRegistry.line(find("Installed Path")!) ==
                "\"Installed Path\"=\"C:\\\\Program Files (x86)\\\\Steam\\\\steamapps\\\\common\\\\Fallout New Vegas\\\\\"",
                "string line with doubled backslashes")
        require(SteamInstallRegistry.line(find("Flags")!) == "\"Flags\"=dword:00000010", "dword line")
        require(SteamInstallRegistry.line(find("")!) == "@=\"default\"", "default value written as @")
        require(SteamInstallRegistry.line(find("Quoted")!) == "\"Quoted\"=\"a \\\"b\\\" \\x00e91 \\\\c\"",
                "quotes escaped; non-ASCII as \\x, padded before a hex digit")
        require(SteamInstallRegistry.text("é\u{1}\n", quote: "\"") == "\\xe9\\1\\n", "short \\x, octal and C escapes as wineserver writes them")
        require(SteamInstallRegistry.text("a[b]", quote: "[]") == "a\\[b\\]", "key names escape brackets")

        // ---- writing .reg text
        let machine = values.filter { $0.hive == .machine }
        let base = "WINE REGISTRY Version 2\n;; All keys relative to \\\\Machine\n\n[Software\\\\Wine] 1700000000\n\"Version\"=\"win10\"\n"
        let first = SteamInstallRegistry.write(machine, in: base, now: 1800000000)
        require(first.changed == 8, "four values in both views")
        require(first.text.contains("[Software\\\\Bethesda Softworks\\\\FalloutNV] 1800000000\n\"Installed Path\"=") &&
                first.text.contains("[Software\\\\Wow6432Node\\\\Bethesda Softworks\\\\FalloutNV] 1800000000\n\"Installed Path\"="),
                "new key sections in both registry views")
        require(first.text.hasPrefix(base.trimmingCharacters(in: .newlines)), "the rest of the file is kept")
        require(SteamInstallRegistry.write(machine, in: first.text, now: 1900000000).changed == 0, "a second write changes nothing")
        let moved = first.text.replacingOccurrences(of: "Fallout New Vegas\\\\\"", with: "Old Folder\\\\\"")
                              .replacingOccurrences(of: "dword:00000011", with: "dword:00000005")
        let again = SteamInstallRegistry.write(machine, in: moved, now: 1900000000)
        require(again.changed == 2 && again.text.contains("Fallout New Vegas\\\\\"") && !again.text.contains("Old Folder") &&
                again.text.components(separatedBy: "dword:00000005").count == 3,
                "an install path that differs is rewritten; a changed dword is kept")
        require(SteamInstallRegistry.kept(machine, in: first.text).isEmpty, "nothing kept when the stored values are the script's")
        let keptNotes = SteamInstallRegistry.kept(machine, in: moved)
        require(keptNotes == ["HKLM\\Software\\Bethesda Softworks\\FalloutNV \"Version\": stored dword:00000005, the script has dword:00000011",
                              "HKLM\\Software\\Wow6432Node\\Bethesda Softworks\\FalloutNV \"Version\": stored dword:00000005, the script has dword:00000011"],
                "the kept dword is named in both views with both texts; the moved install path (rewritten) is not")
        let secret = SteamInstallValue(hive: .user, key: "Software\\Fixture", name: "CDKey", data: .string("from-script"), followsInstall: false)
        let secretNotes = SteamInstallRegistry.kept([secret], in: "[Software\\\\Fixture] 1\n\"cdkey\"=\"AAAA-BBBB\"\n")
        require(secretNotes == ["HKCU\\Software\\Fixture \"CDKey\": stored text differs from the script's (not shown)"],
                "a name with key in it: found without case, its text not shown")
        let user = SteamInstallRegistry.write(values.filter { $0.hive == .user }, in: "", now: 1)
        require(user.changed == 2 && user.text.contains("[Software\\\\Fixture] 1\n") && !user.text.contains("Wow6432Node"),
                "HKCU: one view only")
        let reg = "[Software\\\\Valve\\\\Steam] 1\n\"AutoLoginUser\"=\"x\"\n\"Language\"=\"german\"\n\n[Software\\\\Other] 1\n\"Language\"=\"french\"\n"
        require(SteamInstallRegistry.language(userRegistry: reg) == "german", "Steam's language read from user.reg")
        require(SteamInstallRegistry.language(userRegistry: "") == nil, "no language without the key")

        // ---- in a synthetic prefix
        let tmp = URL(fileURLWithPath: CommandLine.arguments[1])
        let prefix = tmp.appendingPathComponent("wine"), drive = prefix.appendingPathComponent("drive_c")
        let game = DockGame(id: 22380, name: "Fallout: New Vegas", installDir: "Fallout New Vegas",
                            library: "Program Files (x86)/Steam/steamapps", installed: true, customExecutables: false)
        try write(drive.appendingPathComponent("Program Files (x86)/Steam/steamapps/common/Fallout New Vegas/installscript.vdf"), script)
        try write(prefix.appendingPathComponent("system.reg"), base)
        try write(prefix.appendingPathComponent("user.reg"), reg)
        DockInstallers.writeRegistry(game, drive: drive, prefix: prefix)
        let system = try String(contentsOf: prefix.appendingPathComponent("system.reg"), encoding: .utf8)
        require(system.contains("\"Installed Path\"=\"C:\\\\Program Files (x86)\\\\Steam\\\\steamapps\\\\common\\\\Fallout New Vegas\\\\\"") &&
                system.contains("\"Language\"=\"german\""), "system.reg gets the values, in Steam's language")
        require(FileManager.default.fileExists(atPath: prefix.appendingPathComponent("system.reg.madeira-bak").path), "a backup is kept")
        require(LogStore.shared.lines.contains { $0.hasPrefix("[dock-installers] app=22380 registry values=6 written=10 keys=HKLM\\Software\\Bethesda Softworks\\FalloutNV; HKCU\\Software\\Fixture") },
                "the log names what was written")
        LogStore.shared.lines = []
        DockInstallers.writeRegistry(game, drive: drive, prefix: prefix)
        require(LogStore.shared.lines.contains { $0.contains("registry values=6 written=0") }, "the next start writes nothing")
        require(!LogStore.shared.lines.contains { $0.contains("registry kept:") }, "no kept line when nothing differs")
        let stale = system.replacingOccurrences(of: "dword:00000011", with: "dword:00000005")
        try write(prefix.appendingPathComponent("system.reg"), stale)
        LogStore.shared.lines = []
        DockInstallers.writeRegistry(game, drive: drive, prefix: prefix)
        require(LogStore.shared.lines.filter { $0.hasPrefix("[dock-installers] app=22380 registry kept: HKLM\\Software\\") &&
                                               $0.hasSuffix("\"Version\": stored dword:00000005, the script has dword:00000011") }.count == 2 &&
                LogStore.shared.lines.firstIndex { $0.contains("registry values=6 written=0") }! <
                LogStore.shared.lines.firstIndex { $0.contains("registry kept:") }!,
                "a stored value that differs and stays is logged after the summary line, in both views")
        let afterKept = try String(contentsOf: prefix.appendingPathComponent("system.reg"), encoding: .utf8)
        require(afterKept == stale, "logging it changes nothing")

        // prepare() honours its switch.
        try write(prefix.appendingPathComponent("system.reg"), base)
        setenv("MADEIRA_DOCK_INSTALL_REGISTRY", "0", 1)
        setenv("MADEIRA_DOCK_INSTALLERS", "0", 1)
        DockInstallers.prepare(game, drive: drive, prefix: prefix, has32Bit: true, hasMsiexec: true, fusionSource: nil)
        let untouched = try String(contentsOf: prefix.appendingPathComponent("system.reg"), encoding: .utf8)
        require(untouched == base, "MADEIRA_DOCK_INSTALL_REGISTRY=0 writes nothing")
        unsetenv("MADEIRA_DOCK_INSTALL_REGISTRY")
        DockInstallers.prepare(game, drive: drive, prefix: prefix, has32Bit: true, hasMsiexec: true, fusionSource: nil)
        let written = try String(contentsOf: prefix.appendingPathComponent("system.reg"), encoding: .utf8)
        require(written.contains("FalloutNV"),
                "prepare() writes them by default, even with the installers off")

        if failures > 0 { print("FAILURES: \(failures)"); exit(1) }
        print("PASS: all install-script registry Swift checks")
    }
}
'''

with tempfile.TemporaryDirectory(prefix='madeira-install-registry-') as tmp:
    tmp = Path(tmp)
    (tmp / 'stubs.swift').write_text(stubs, encoding='utf-8')
    (tmp / 'checks.swift').write_text(checks, encoding='utf-8')
    exe = tmp / 'check'
    if not Path(SWIFTC).exists() and not shutil.which(SWIFTC):
        if '--require-swift' in sys.argv:
            require(False, 'Swift compiler available (--require-swift)')
        else:
            print('SKIP: Swift compiler unavailable; the compiled registry checks did not run')
    else:
        build = subprocess.run([SWIFTC, '-parse-as-library', '-swift-version', '5', '-sanitize=address', '-o', str(exe),
                                str(tmp / 'stubs.swift'), str(tmp / 'checks.swift'), str(app / 'DockInstallers.swift'),
                                str(app / 'DockReset.swift')])
        require(build.returncode == 0, 'production installer Swift compiles on the host')
        if build.returncode == 0:
            work = tmp / 'work'; work.mkdir()
            run = subprocess.run([str(exe), str(work)], env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
            require(run.returncode == 0, 'registry checks pass under AddressSanitizer')

if failures:
    print(f'FAILURES: {failures}')
    sys.exit(1)
print('PASS: install-script registry values')
