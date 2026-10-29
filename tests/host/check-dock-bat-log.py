#!/usr/bin/env python3
"""A Dock start whose launch entry is a .bat or .cmd logs what the file runs.

Valve's client starts such an entry through cmd.exe, and the session log then
shows only cmd's exit code (Messiah's "Launch Messiah.bat" ends at once with
255). SteamDirectStart.batchLines (app/Madeira/SteamGames.swift) gives the log
the file's name, arguments and first lines. This compiles the SteamDirectStart
enum with swiftc against a copy of SteamLaunchOption, runs it on real files and
checks:
  - a .bat or .cmd entry inside the install folder (any case, backslashes) is
    named with its arguments, and its lines follow, CRLF or LF;
  - only maxLines lines are shown, the header says how many there are;
  - tabs become spaces, other control characters go, lines are cut to 160;
  - a file with a zero byte is named, not shown;
  - an .exe entry, a missing file, an entry outside the folder ("..") and an
    unknown key give no lines;
and that the Dock start logs the lines right after its launch option line.

Needs python3 and swiftc (SWIFTC to override).
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
SWIFTC = os.environ.get('SWIFTC') or shutil.which('swiftc') or str(Path.home() / '.local/share/swiftly/bin/swiftc')
failures = []


def check(what, cond):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


games = (app / 'SteamGames.swift').read_text(encoding='utf-8')
start = games.index('enum SteamDirectStart {')
end = games.index('\n}\n', start) + 3
enum = games[start:end]
info = (app / 'SwiftSteam/Library/SteamAppInfo.swift').read_text(encoding='utf-8')
ostart = info.index('struct SteamLaunchOption: Codable, Hashable, Sendable {')
option = info[ostart:info.index('\n}\n', ostart) + 3]

content = (app / 'ContentView.swift').read_text(encoding='utf-8')
at = content.index('LogStore.shared.log("[madeira-dock] launch option \\(launchOption)')
check('the Dock start logs the batch lines right after its launch option line',
      'for line in SteamDirectStart.batchLines(options ?? [], key: launchOption, installFolder: installFolder) {\n'
      '                LogStore.shared.log(line)' in content[at:at + 400])

checks = r'''
let root = URL(fileURLWithPath: CommandLine.arguments[1])
func opt(_ exe: String, _ index: UInt32, _ args: String = "") -> SteamLaunchOption {
    SteamLaunchOption(executable: exe, index: index, arguments: args)
}
let options = [opt("Messiah.exe", 0), opt("Launch Messiah.bat", 1, "-dx9\t-x"), opt("bin\\Run.CMD", 2),
               opt("long.bat", 3), opt("binary.bat", 4), opt("missing.bat", 5), opt("../outside.bat", 6)]
func dump(_ key: UInt32, _ max: Int = 30) {
    let lines = SteamDirectStart.batchLines(options, key: key, installFolder: root, maxLines: max)
    print("KEY \(key) \(lines.count)")
    for line in lines { print("L " + line) }
}
for key: UInt32 in [0, 1, 2, 3, 4, 5, 6, 9] { dump(key) }
dump(3, 2)
'''
tmp = Path(tempfile.mkdtemp(prefix='dock-bat-'))
try:
    game = tmp / 'game'
    (game / 'bin').mkdir(parents=True)
    (game / 'Messiah.exe').write_bytes(b'MZ')
    (game / 'launch messiah.bat').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\nstart "" Messiah.exe -dx9\r\n\r\n\r\n')
    (game / 'bin/run.cmd').write_bytes(b'echo one\nset X=\x01a\tb\x7f\n')
    (game / 'long.bat').write_text('\n'.join('rem line %d %s' % (i, 'x' * 300) for i in range(1, 51)) + '\n')
    (game / 'binary.bat').write_bytes(b'echo\x00x\r\n')
    (tmp / 'outside.bat').write_bytes(b'echo outside\r\n')
    src = tmp / 'main.swift'
    src.write_text('import Foundation\n' + option + enum + checks)
    exe = tmp / 'check'
    subprocess.run([SWIFTC, str(src), '-o', str(exe)], check=True)
    out = subprocess.run([str(exe), str(game)], capture_output=True, text=True, check=True).stdout
    if os.environ.get("DUMP"): print(out)
    blocks = {}
    for chunk in out.split('KEY ')[1:]:
        head, *rest = chunk.rstrip('\n').split('\n')
        key, count = head.split()
        blocks.setdefault(key, []).append([l[2:] for l in rest])
    def block(key, i=0):
        return blocks.get(key, [[None]])[i]

    check('an .exe entry gives no lines', block('0') == [])
    b = block('1')
    check('a .bat entry is named, spelt as on disk, with its arguments (tab as a space)',
          b[0] == '[dock-bat] launch option 1 runs launch messiah.bat with arguments "-dx9 -x" (3 lines)')
    check('its CRLF lines follow, trailing blank lines dropped',
          b[1:] == ['[dock-bat] 1: @echo off', '[dock-bat] 2: cd /d "%~dp0"', '[dock-bat] 3: start "" Messiah.exe -dx9'])
    b = block('2')
    check('a .CMD in a subfolder, backslash path, LF lines, control characters dropped',
          b == ['[dock-bat] launch option 2 runs bin/run.cmd (2 lines)', '[dock-bat] 1: echo one', '[dock-bat] 2: set X=a b'])
    b = block('3')
    check('30 lines shown of 50, the header says so',
          len(b) == 31 and b[0] == '[dock-bat] launch option 3 runs long.bat (50 lines, the first 30 below)')
    check('each line cut to 160 characters', all(len(l) <= len('[dock-bat] 30: ') + 160 for l in b[1:])
          and b[1] == '[dock-bat] 1: ' + ('rem line 1 ' + 'x' * 300)[:160])
    check('maxLines is honoured', block('3', 1)[0] == '[dock-bat] launch option 3 runs long.bat (50 lines, the first 2 below)'
          and len(block('3', 1)) == 3)
    check('a file with a zero byte is named, not shown', block('4') == ['[dock-bat] launch option 4 runs binary.bat (not a text file)'])
    check('a missing file gives no lines', block('5') == [])
    check('an entry outside the install folder gives no lines', block('6') == [])
    check('an unknown key gives no lines', block('9') == [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('PASS: Dock .bat start log' if not failures else 'FAILED: Dock .bat start log (%d)' % len(failures))
sys.exit(1 if failures else 0)
