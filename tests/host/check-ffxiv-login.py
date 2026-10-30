#!/usr/bin/env python3
"""Final Fantasy XIV's sign-in (app/Madeira/SwiftFFXIV/FFXIVLogin.swift,
app/Madeira/FFXIVLaunch.swift, docs/FFXIV.md).

Source checks: both files are in the app target, Play asks for the sign-in before a
game\\ffxiv_dx11.exe entry starts and starts it again once the session is set, the
session is a transient argument only, the password is a device-only Keychain item,
no log line carries the password, the one-time password or the session, and the
sign-in only talks to Square Enix over HTTPS.

Swift (FFXIVLogin.swift, Foundation only): the login page's _STORED_ value, the
login answer and a refusal, the computer id's checksum, the form encoding, an
install's versions and boot hashes read from a scratch folder, the version report,
the patch list count and the game's arguments. Never contacts Square Enix.
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


login = (app / 'SwiftFFXIV/FFXIVLogin.swift').read_text()
launch = (app / 'FFXIVLaunch.swift').read_text()
content = (app / 'ContentView.swift').read_text()
library = (app / 'Library.swift').read_text()
launchers = (app / 'LauncherSupport.swift').read_text()
project = (app.parent / 'Madeira.xcodeproj/project.pbxproj').read_text()

# ------------------------------------------------------------------ static rules
for path, text in (('SwiftFFXIV/FFXIVLogin.swift', login), ('FFXIVLaunch.swift', launch)):
    name = path.split('/')[-1]
    require(text.startswith('// SPDX-License-Identifier: GPL-3.0-or-later'), f'{name}: licence header')
    require(f'/* {path} in Sources */,' in project and f'/* {name} */,' in project, f'{name}: in the Xcode project sources')
    for line in text.splitlines():
        if 'FFXIVLog.event' in line or 'LogStore' in line:
            compact = line.replace(' ', '')
            bad = [w for w in ('password', 'oneTimePassword', 'id', 'rawID', 'stored', 'sessionID', 'session)', 'reply', 'page', 'body')
                   if '\\(' + w in compact]
            require(not bad, f'{name}: no sign-in data in a log line: {line.strip()[:80]}')
require(not re.search(r'"http://[^"]', login), 'the sign-in uses HTTPS only (no http:// address)')
require(re.findall(r'"https://([^/"]+)', login) and all(h.endswith(('square-enix.com', 'ffxiv.com', 'finalfantasyxiv.com'))
        for h in re.findall(r'"https://([^/"]+)', login)), 'the sign-in only talks to Square Enix')
require('kSecAttrAccessibleWhenUnlockedThisDeviceOnly' in launch and 'kSecAttrSynchronizable as String: false' in launch,
        'the password: a device-only Keychain item, not synchronised')
require('remember ? password : nil' in launch, 'the password is kept only with Remember on')
require('LibraryEntry.setTransientArguments(FFXIVFormat.gameArguments(' in launch, 'the session is this launch\'s arguments only')
start = content[content.index('    private func startLibraryEntry('):]
start = start[:start.index('\n    }\n')]
require(start.index('if !ffxivReady, FFXIVLaunch.installRoot(entry) != nil {') < start.index('try entry.validate()'),
        'Play asks for the sign-in before the entry is checked and started')
require('FFXIVSignInView(entry: entry) { startLibraryEntry(entry, ffxivReady: true) }' in content,
        'the sign-in starts the entry again once the session is set')
require('guard let transient = Self.transientArguments(for: id), !transient.isEmpty else { return own }' in library,
        'the transient arguments reach any entry that has them (Epic and Final Fantasy XIV)')
require('case ffxiv' in launchers.replace('case ubisoft, battleNet, rockstar, ffxiv', 'case ffxiv')
        and 'https://gdl.square-enix.com/ffxiv/inst/ffxivsetup.exe' in launchers, 'Settings offers Square Enix\'s installer')
require('private func addFFXIVGame(boot: URL)' in launchers, 'adding the launcher adds the game too')
require((root / 'docs/FFXIV.md').exists(), 'docs/FFXIV.md')

# ------------------------------------------------------------------ compiled Swift
stubs = r'''
import Foundation
final class LogStore {
    nonisolated(unsafe) static let shared = LogStore()
    func log(_ message: String) {}
}
'''

checks = r'''
import Foundation
var failures = 0
func require(_ condition: @autoclosure () -> Bool, _ label: String) {
    if condition() { print("PASS: " + label) } else { print("FAIL: " + label); failures += 1 }
}

@main
struct Checks {
    static func main() throws {
        let work = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)

        let top = """
        <form>
        \t<input type="hidden" name="_STORED_" value="0123abcdEF+/=">
        </form>
        """
        require(FFXIVFormat.stored(in: top) == "0123abcdEF+/=", "the login page's _STORED_ value")
        require(FFXIVFormat.stored(in: "<html></html>") == nil, "no form, no value")

        let ok = #"<script>window.external.user("login=auth,ok,sid,a1b2c3d4e5f6,terms,1,region,3,etmadd,0,playable,1,ps3pkg,0,maxex,5,product,1");</script>"#
        require(FFXIVFormat.loginAnswer(in: ok) == FFXIVFormat.LoginAnswer(sessionID: "a1b2c3d4e5f6", region: 3, termsAccepted: true,
                                                                           playable: true, maxExpansion: 5), "the login answer")
        let lapsed = ok.replacingOccurrences(of: "playable,1", with: "playable,0").replacingOccurrences(of: "terms,1", with: "terms,0")
        require(FFXIVFormat.loginAnswer(in: lapsed).map { !$0.playable && !$0.termsAccepted } == true, "no service, terms not accepted")
        require(FFXIVFormat.loginAnswer(in: ok.replacingOccurrences(of: "a1b2c3d4e5f6", with: "a1\\b")) == nil, "an odd session is refused")
        let ng = #"window.external.user("login=auth,ng,err,The Square Enix ID or password is incorrect.");"#
        require(FFXIVFormat.loginAnswer(in: ng) == nil && FFXIVFormat.loginRefusal(in: ng) == "The Square Enix ID or password is incorrect.",
                "a refusal in Square Enix's words")
        require(FFXIVFormat.restartup == "window.external.user(\"restartup\");", "a Steam account's answer")

        let id = FFXIVFormat.computerID([0x10, 0x20, 0x30, 0x40])
        require(id == "6010203040", "the computer id's checksum (\(id))")
        require(FFXIVFormat.computerID([0xff, 0xff, 0xff, 0xff]) == "04ffffffff", "the checksum wraps")
        require(FFXIVFormat.userAgent(computerID: id) == "SQEXAuthor/2.0.0(Windows 6.2; ja-jp; 6010203040)", "the launcher's user agent")
        require(FFXIVFormat.topURL().absoluteString
                == "https://ffxiv-login.square-enix.com/oauth/ffxivarr/login/top?lng=en&rgn=3&isft=0&cssmode=1&isnew=1&launchver=3",
                "the login page's address")
        require(FFXIVFormat.referer(at: Date(timeIntervalSince1970: 1_700_000_000)).hasSuffix("rc_lang=en_gb&time=2023-11-14-22-13"),
                "the referrer's time, UTC")
        let form = String(decoding: FFXIVFormat.form([("_STORED_", "a+b/c="), ("sqexid", "me"), ("password", "p&ss wörd"), ("otppw", "")]), as: UTF8.self)
        require(form == "_STORED_=a%2Bb%2Fc%3D&sqexid=me&password=p%26ss+w%C3%B6rd&otppw=", "the form encoding (\(form))")

        // A scratch install: boot and game versions, two expansions, the four boot programs.
        let install = work.appendingPathComponent("FINAL FANTASY XIV - A Realm Reborn", isDirectory: true)
        let manager = FileManager.default
        for folder in ["boot", "game/sqpack/ex1", "game/sqpack/ex2"] {
            try manager.createDirectory(at: install.appendingPathComponent(folder), withIntermediateDirectories: true)
        }
        try "2024.06.01.0000.0001".write(to: install.appendingPathComponent("boot/ffxivboot.ver"), atomically: true, encoding: .utf8)
        try "2024.07.23.0000.0001".write(to: install.appendingPathComponent("game/ffxivgame.ver"), atomically: true, encoding: .utf8)
        try "2024.07.10.0000.0000".write(to: install.appendingPathComponent("game/sqpack/ex1/ex1.ver"), atomically: true, encoding: .utf8)
        for (n, program) in FFXIVInstall.bootPrograms.enumerated() {
            try Data(repeating: 7, count: n + 1).write(to: install.appendingPathComponent("boot/" + program))
        }
        let read = try FFXIVInstall.read(root: install) { "sha-" + $0.lastPathComponent }
        require(read.bootVersion == "2024.06.01.0000.0001" && read.gameVersion == "2024.07.23.0000.0001", "the boot and game versions")
        require(read.expansionVersions == ["2024.07.10.0000.0000", FFXIVInstall.baseVersion], "an expansion folder without its .ver is the base version")
        require(read.bootHashes == ["1/sha-ffxivboot.exe", "2/sha-ffxivboot64.exe", "3/sha-ffxivlauncher64.exe", "4/sha-ffxivupdater64.exe"],
                "each boot program's size and hash")
        let report = FFXIVFormat.versionReport(read, maxExpansion: 3)
        require(report == "2024.06.01.0000.0001=ffxivboot.exe/1/sha-ffxivboot.exe,ffxivboot64.exe/2/sha-ffxivboot64.exe,"
                + "ffxivlauncher64.exe/3/sha-ffxivlauncher64.exe,ffxivupdater64.exe/4/sha-ffxivupdater64.exe\n"
                + "ex1\t2024.07.10.0000.0000\nex2\t2012.01.01.0000.0000\nex3\t2012.01.01.0000.0000\n", "the version report:\n" + report)
        require(FFXIVFormat.versionReport(read, maxExpansion: 0).components(separatedBy: "\n").count == 2, "no expansions, the boot line only")

        try "2024.07.23\n0000".write(to: install.appendingPathComponent("game/ffxivgame.ver"), atomically: true, encoding: .utf8)
        do { _ = try FFXIVInstall.read(root: install) { _ in "x" }; require(false, "a damaged version file is refused") }
        catch let error as FFXIVLoginError { require(error == .badVersionFiles("game/ffxivgame.ver"), "a damaged version file is refused") }
        try manager.removeItem(at: install.appendingPathComponent("game/ffxivgame.ver"))
        try manager.removeItem(at: install.appendingPathComponent("boot/ffxivupdater64.exe"))
        do { _ = try FFXIVInstall.read(root: install) { _ in "x" }; require(false, "a missing boot program is refused") }
        catch let error as FFXIVLoginError { require(error == .badVersionFiles("boot\\ffxivupdater64.exe"), "a missing boot program is refused") }

        let patches = """
        --477D80B1_38BC_41d4_8B48_5273ADB89CAC\r
        Content-Type: application/octet-stream\r
        \r
        87543210\t87543210\t60\t49\t2024.07.24.0000.0001\tsha1\t50000000\tabc\thttp://patch-dl.ffxiv.com/game/4e9a232b/D2024.07.24.0000.0001.patch\r
        1000\t1000\t61\t50\t2024.07.25.0000.0000\tsha1\t50000000\tdef\thttp://patch-dl.ffxiv.com/game/4e9a232b/D2024.07.25.0000.0000.patch\r
        --477D80B1_38BC_41d4_8B48_5273ADB89CAC--\r
        """
        require(FFXIVFormat.patchCount(patches) == 2, "the patch list's entries")

        let args = FFXIVFormat.gameArguments(FFXIVSession(sessionID: "a1b2c3d4e5f6", region: 3, maxExpansion: 5), gameVersion: "2024.07.23.0000.0001")
        require(args == "DEV.DataPathType=1 DEV.MaxEntitledExpansionID=5 DEV.TestSID=a1b2c3d4e5f6 DEV.UseSqPack=1 SYS.Region=3 "
                + "language=1 resetConfig=0 ver=2024.07.23.0000.0001", "the game's arguments")
        require(FFXIVLoginError.needsGamePatch(2).errorDescription?.contains("2 updates") == true, "the update message")
        if failures > 0 { exit(1) }
    }
}
'''

with tempfile.TemporaryDirectory(prefix='madeira-ffxiv-') as tmp:
    tmp = Path(tmp)
    work = tmp / 'work'; work.mkdir()
    (tmp / 'stubs.swift').write_text(stubs)
    (tmp / 'checks.swift').write_text(checks)
    exe = tmp / 'check'
    if not Path(SWIFTC).exists() and not shutil.which(SWIFTC):
        if '--require-swift' in sys.argv:
            require(False, 'Swift compiler available (--require-swift)')
        else:
            print('SKIP: Swift compiler unavailable; the compiled Final Fantasy XIV checks did not run')
    else:
        build = subprocess.run([SWIFTC, '-parse-as-library', '-swift-version', '5', '-o', str(exe),
                                str(tmp / 'stubs.swift'), str(app / 'SwiftFFXIV/FFXIVLogin.swift'), str(tmp / 'checks.swift')])
        require(build.returncode == 0, 'the Final Fantasy XIV sign-in compiles on the host')
        if build.returncode == 0:
            run = subprocess.run([str(exe), str(work)])
            require(run.returncode == 0, 'Final Fantasy XIV checks pass')

if failures:
    print(f'FAILURES: {failures}')
    sys.exit(1)
print('PASS: Final Fantasy XIV sign-in')
