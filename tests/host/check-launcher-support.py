#!/usr/bin/env python3
"""The publishers' launchers (app/Madeira/LauncherSupport.swift, docs/LAUNCHERS.md).

Source checks: the file is in the app target, the Settings section is listed, the
Ubisoft repair runs before a library start and before a Madeira Dock start (after
their checks, before the session), every installer and client the section knows is
recognised by GameRecommendations (so it gets its Wine desktop and services), and
the installers come from the publishers' own HTTPS addresses.

Swift (app/Madeira/LauncherSupport.swift without its SwiftUI half, with
DockInstallers.swift): in a scratch drive_c and prefix, a Ubisoft Connect install is
found, Uplay.exe and upc.exe are made as links beside it, the install folder goes
into both registry views and uplay:// / ubisoft-connect:// into the user's classes,
a second repair changes nothing, a real Uplay.exe stays, nothing happens while a
session runs or without the client.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
SWIFTC = os.environ.get('SWIFTC') or shutil.which('swiftc') or str(Path.home() / '.local/share/swiftly/bin/swiftc')
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


source = (app / 'LauncherSupport.swift').read_text(encoding='utf-8')
recs = (app / 'GameRecommendations.swift').read_text(encoding='utf-8')
library = (app / 'Library.swift').read_text(encoding='utf-8')
content = (app / 'ContentView.swift').read_text(encoding='utf-8')
project = (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text(encoding='utf-8')

# ------------------------------------------------------------------ static rules
require(project.count('/* LauncherSupport.swift in Sources */') == 2 and project.count('/* LauncherSupport.swift */') == 3,
        'LauncherSupport.swift is in the app target')
require('LauncherSupportSettingsSection()' in library, 'Settings lists the PC game launchers section')
start = content[content.index('    private func startLibraryEntry('):]
start = start[:start.index('\n    }\n')]
require(start.index('LauncherSupport.repairUbisoft()') < start.index('try entry.validate()') < start.index('entry.configureLaunch()'),
        'a library start repairs Ubisoft before the entry is checked and started')
dock = content[content.index('            try MadeiraDock.validate(game, drive: MadeiraDock.drive)'):]
require(dock.index('} catch { fail(error); return }') < dock.index('LauncherSupport.repairUbisoft()') < dock.index('Task { @MainActor in'),
        'a Madeira Dock start repairs Ubisoft after its checks, before the session')
repair = source[source.index('    static func repairUbisoft('):]
repair = repair[:repair.index('\n    }\n')]
require('guard wine_process_is_running() == 0' in repair, 'the registry is only written while no session runs')
require('reg.exe' not in source and 'Process(' not in source, 'the registry is written from the app, never by a program')

# Every program and installer the section knows has its recommended list.
names = set(re.findall(r'\\\\([^\\"]+\.exe)"', source.split('var installerURL')[0]))
names |= set(re.findall(r'return "([^"]+\.exe)"', source))
for name in sorted(names, key=str.lower):
    require('case "%s"' % name.lower() in recs or '"%s"' % name.lower() in recs, 'GameRecommendations recognises ' + name)
urls = re.findall(r'URL\(string: "([^"]+)"\)!', source)
require(len(urls) == 3 and all(u.startswith('https://') for u in urls) and
        any('ubistatic' in u for u in urls) and any('battle.net' in u for u in urls) and any('rockstargames.com' in u for u in urls),
        "the installers come from the publishers' own HTTPS addresses")
require('epic' not in source.split('enum LauncherID')[1].split('}')[0].lower(), "Epic's launcher is left out (Madeira has Epic's store)")
require((root / 'docs/LAUNCHERS.md').exists(), 'docs/LAUNCHERS.md')

# ------------------------------------------------------------------ compiled Swift
core = source[:source.index('@MainActor\nfinal class LauncherSupportModel')].replace('import SwiftUI\n', '')
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
nonisolated(unsafe) var sessionRunning: Int32 = 0
func wine_process_is_running() -> Int32 { sessionRunning }
enum LibraryModel {
    nonisolated(unsafe) static var work = URL(fileURLWithPath: "/nonexistent")
    static var documents: URL { work }
    static var drive: URL { work.appendingPathComponent("wine/drive_c", isDirectory: true) }
}
'''
dock_src = (app / 'MadeiraDock.swift').read_text(encoding='utf-8')
stubs += dock_src[dock_src.index('/// A game Steam\'s client has installed'):dock_src.index('/// Madeira Dock: a small headless host')]

checks = r'''
import Foundation
var failures = 0
func require(_ condition: @autoclosure () -> Bool, _ label: String) {
    if condition() { print("PASS: " + label) } else { print("FAIL: " + label); failures += 1 }
}

@main
struct Checks {
    @MainActor static func main() throws {
        LibraryModel.work = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let fm = FileManager.default
        let prefix = LibraryModel.documents.appendingPathComponent("wine", isDirectory: true)
        try fm.createDirectory(at: LibraryModel.drive, withIntermediateDirectories: true)
        try Data("WINE REGISTRY Version 2\n\n[Software\\\\Wine] 1\n".utf8).write(to: prefix.appendingPathComponent("system.reg"))
        try Data("WINE REGISTRY Version 2\n\n[Software\\\\Wine] 1\n".utf8).write(to: prefix.appendingPathComponent("user.reg"))

        require(LauncherSupport.installed(.ubisoft) == nil && LauncherSupport.repairUbisoft() == 0, "no client: nothing found, nothing changed")
        let folder = LibraryModel.drive.appendingPathComponent("Program Files (x86)/Ubisoft/Ubisoft Game Launcher", isDirectory: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)
        try Data("MZ".utf8).write(to: folder.appendingPathComponent("UbisoftConnect.exe"))
        require(LauncherSupport.installed(.ubisoft)?.lastPathComponent == "UbisoftConnect.exe", "the client is found")
        require(LauncherSupport.installed(.battleNet) == nil && LauncherSupport.installed(.rockstar) == nil, "the others are not")

        sessionRunning = 1
        require(LauncherSupport.repairUbisoft() == 0, "nothing while a session runs")
        sessionRunning = 0
        let first = LauncherSupport.repairUbisoft()
        require(first > 0, "the first repair changes something (\(first))")
        for alias in ["Uplay.exe", "upc.exe"] {
            let target = try? fm.destinationOfSymbolicLink(atPath: folder.appendingPathComponent(alias).path)
            require(target == "UbisoftConnect.exe", "\(alias) links to the client (\(target ?? "none"))")
        }
        let system = try String(contentsOf: prefix.appendingPathComponent("system.reg"), encoding: .utf8)
        let user = try String(contentsOf: prefix.appendingPathComponent("user.reg"), encoding: .utf8)
        let dir = #""InstallDir"="C:\\Program Files (x86)\\Ubisoft\\Ubisoft Game Launcher\\""#
        require(system.contains("[Software\\\\Ubisoft\\\\Launcher]") && system.contains("[Software\\\\Wow6432Node\\\\Ubisoft\\\\Launcher]")
                && system.components(separatedBy: dir).count == 3, "the install folder in both registry views")
        require(!system.lowercased().contains("classes"), "no protocol in the machine hive")
        require(user.contains("[Software\\\\Classes\\\\uplay]") && user.contains("\"URL Protocol\"=\"\"")
                && user.contains("[Software\\\\Classes\\\\uplay\\\\shell\\\\open\\\\command]")
                && user.contains(#"@="\"C:\\Program Files (x86)\\Ubisoft\\Ubisoft Game Launcher\\UbisoftConnect.exe\" \"%1\"""#)
                && user.contains("[Software\\\\Classes\\\\ubisoft-connect\\\\shell\\\\open\\\\command]"), "uplay:// and ubisoft-connect:// in the user's classes")
        require(!user.contains("Wow6432Node"), "the user's classes in one view")
        require(LauncherSupport.repairUbisoft() == 0, "a second repair changes nothing")

        // An older client's own Uplay.exe stays; a dangling link is made again.
        try fm.removeItem(at: folder.appendingPathComponent("Uplay.exe"))
        try Data("MZ real".utf8).write(to: folder.appendingPathComponent("Uplay.exe"))
        try fm.removeItem(at: folder.appendingPathComponent("upc.exe"))
        try fm.createSymbolicLink(atPath: folder.appendingPathComponent("upc.exe").path, withDestinationPath: "gone.exe")
        require(LauncherSupport.repairUbisoft() == 1, "only the dangling link is made again")
        require((try? fm.destinationOfSymbolicLink(atPath: folder.appendingPathComponent("Uplay.exe").path)) == nil
                && (try? fm.destinationOfSymbolicLink(atPath: folder.appendingPathComponent("upc.exe").path)) == "UbisoftConnect.exe",
                "a real Uplay.exe stays; upc.exe links to the client again")
        if failures > 0 { print("FAILURES: \(failures)"); exit(1) }
        print("PASS: all launcher Swift checks")
    }
}
'''

with tempfile.TemporaryDirectory(prefix='madeira-launchers-') as tmp:
    tmp = Path(tmp)
    (tmp / 'stubs.swift').write_text(stubs, encoding='utf-8')
    (tmp / 'core.swift').write_text(core, encoding='utf-8')
    (tmp / 'checks.swift').write_text(checks, encoding='utf-8')
    exe = tmp / 'check'
    if not Path(SWIFTC).exists() and not shutil.which(SWIFTC):
        if '--require-swift' in sys.argv:
            require(False, 'Swift compiler available (--require-swift)')
        else:
            print('SKIP: Swift compiler unavailable; the compiled launcher checks did not run')
    else:
        build = subprocess.run([SWIFTC, '-parse-as-library', '-swift-version', '5', '-o', str(exe),
                                str(tmp / 'stubs.swift'), str(tmp / 'core.swift'), str(tmp / 'checks.swift'),
                                str(app / 'DockInstallers.swift'), str(app / 'DockReset.swift')])
        require(build.returncode == 0, 'LauncherSupport.swift compiles on the host')
        if build.returncode == 0:
            work = tmp / 'work'; work.mkdir()
            run = subprocess.run([str(exe), str(work)])
            require(run.returncode == 0, 'launcher checks pass')

if failures:
    print(f'FAILURES: {failures}')
    sys.exit(1)
print('PASS: publishers\' launchers')
