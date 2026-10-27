#!/usr/bin/env python3
"""Game details > DLL overrides (app/Madeira/GameDllOverrides.swift).

Which copy of a DLL Wine loads for a game (its own or Wine's), chosen from a list
and written into the game's config as env.WINEDLLOVERRIDES; every other line of the
config stays. DLLs in the game's folder can be picked from a list.

Source checks (every host): the page is in Game details, the file is in the project.

Swift fixture (macOS CI with --require-swift; skipped without a compiler): the part
of GameDllOverrides.swift above "MARK: Views" on synthetic configs and folders.
"""
from pathlib import Path
import argparse, re, shutil, subprocess, sys, tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--require-swift', action='store_true')
args = parser.parse_args()

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
failures = 0


def check(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


source = (app / 'GameDllOverrides.swift').read_text(encoding='utf-8')
library = (app / 'Library.swift').read_text(encoding='utf-8')
project = (app.parent / 'Madeira.xcodeproj/project.pbxproj').read_text(encoding='utf-8')

check('case .dllOverrides: return "DLL overrides"' in library and
      'case .dllOverrides: GameDllOverridesSection(windowsPath: entry.windowsPath, gameFolder: overridesGameFolder)' in library,
      'Game details has a DLL overrides page')
more = re.search(r'let more: \[Page\] = entry\.desktop == true \? \[(.*?)\] : \[(.*?)\]', library)
desktop_pages, game_pages = (more.group(1), more.group(2)) if more else ('', '')
check('.dllOverrides' in game_pages and '.dllOverrides' in desktop_pages,
      'the page is offered for games and for the Desktop')
check(project.count('A1000991 /* GameDllOverrides.swift in Sources */') == 2 and project.count('A2000991 /* GameDllOverrides.swift */') == 3, 'GameDllOverrides.swift is in the app target')
check('DllOverrides.write(overrides, into: file.text)' in source and 'GameProfile(windowsPath: windowsPath)' in source,
      "changes go into the game's own config file")
foundation = source[:source.index('// MARK: Views')]
check('LibraryModel' not in foundation and 'LogStore' not in foundation and 'GameProfile' not in foundation,
      'the model part is Foundation only')

main_swift = r'''
import Foundation
func show(_ s: String) -> String { s.replacingOccurrences(of: "\r", with: "<CR>").replacingOccurrences(of: "\n", with: "<LF>") }
var o = DllOverrides("comdlg32,shell32=n,b; d3d9 = n ;video64=;stray")
print("parsed=" + o.entries.map { "\($0.name):\($0.mode)" }.joined(separator: ","))
print("value=" + o.value)
o.set("D3D9.dll", "b")
o.remove("shell32.DLL")
print("changed=" + o.value)
let config = "# mine\nfence-chain = 6\n# env.WINEDLLOVERRIDES = old\nenv.WINEDLLOVERRIDES = x=n\nenv.WINEDLLOVERRIDES = video64=\nenv.FEX_MULTIBLOCK = 1\n"
var r = DllOverrides.read(config: config)
print("read=" + r.value)
r.set("d3d9", "n")
print("written=" + show(DllOverrides.write(r, into: config)))
print("cleared=" + show(DllOverrides.write(DllOverrides(), into: config)))
let one = DllOverrides(entries: [.init(name: "d3d9", mode: "n")])
print("appended=" + show(DllOverrides.write(one, into: "a = 1\n")) + "|" + show(DllOverrides.write(one, into: "")) + "|" +
      show(DllOverrides.write(one, into: "a = 1")))
print("crlf=" + show(DllOverrides.write(one, into: "a = 1\r\nenv.WINEDLLOVERRIDES = x=b\r\n")))
print("titles=" + DllOverrides.title("n,b") + "|" + DllOverrides.title("") + "|" + DllOverrides.title("n,d"))
let drive = URL(fileURLWithPath: CommandLine.arguments[1])
print("found=" + DllOverrides.candidates(drive: drive, gameFolder: "Games/NV").joined(separator: ","))
print("folder=" + DllOverrides.gameFolder(relativePath: "Games/NV/FalloutNV.exe", isDirectory: false) + "|" +
      DllOverrides.gameFolder(relativePath: "Games/NV", isDirectory: true))
'''

compiler = shutil.which('swiftc')
if not compiler:
    print('SKIP: Swift compiler unavailable locally; macOS CI must run this check with --require-swift')
    if args.require_swift:
        failures += 1
else:
    with tempfile.TemporaryDirectory(prefix='madeira-dll-') as directory:
        temporary = Path(directory)
        (temporary / 'GameDllOverrides.swift').write_text(foundation.replace('import SwiftUI\n', ''))
        (temporary / 'main.swift').write_text(main_swift)
        binary = temporary / 'dll'
        subprocess.run([compiler, '-swift-version', '5', str(temporary / 'GameDllOverrides.swift'), str(temporary / 'main.swift'),
                        '-o', str(binary)], check=True)
        drive = temporary / 'drive_c'
        (drive / 'Games/NV/Data/Sub').mkdir(parents=True)
        (drive / 'Games/NV/d3d9.dll').write_text('x')
        (drive / 'Games/NV/Data/NVSE_1_4.DLL').write_text('x')
        (drive / 'Games/NV/Data/Sub/deep.dll').write_text('x')
        (drive / 'Games/NV/readme.txt').write_text('x')
        out = dict(line.split('=', 1) for line in subprocess.run([str(binary), str(drive)], capture_output=True, text=True,
                                                                 check=True).stdout.splitlines())
        check(out['parsed'] == 'comdlg32:n,b,shell32:n,b,d3d9:n,video64:', "Wine's syntax: lists, spaces, disabled")
        check(out['value'] == 'comdlg32=n,b;shell32=n,b;d3d9=n;video64=;stray', 'written back one name each; odd parts kept')
        check(out['changed'] == 'comdlg32=n,b;d3d9=b;video64=;stray', 'a DLL is found in any case, with or without .dll')
        check(out['read'] == 'video64=', 'the last line counts; commented lines do not')
        check(out['written'] == '# mine<LF>fence-chain = 6<LF># env.WINEDLLOVERRIDES = old<LF>'
              'env.WINEDLLOVERRIDES = video64=;d3d9=n<LF>env.FEX_MULTIBLOCK = 1<LF>',
              'the line is replaced in place; the other lines and comments stay')
        check(out['cleared'] == '# mine<LF>fence-chain = 6<LF># env.WINEDLLOVERRIDES = old<LF>env.FEX_MULTIBLOCK = 1<LF>',
              'no overrides: the line goes')
        check(out['appended'] == 'a = 1<LF>env.WINEDLLOVERRIDES = d3d9=n<LF>|env.WINEDLLOVERRIDES = d3d9=n<LF>|'
              'a = 1<LF>env.WINEDLLOVERRIDES = d3d9=n', 'a config without the line gets it at the end')
        check(out['crlf'] == 'a = 1<CR><LF>env.WINEDLLOVERRIDES = d3d9=n<CR><LF>', 'CRLF configs keep CRLF')
        check(out['titles'] == "Game's own, then Wine's|Off (not loaded)|Other (n,d)", 'modes in plain words')
        check(out['found'] == 'd3d9,NVSE_1_4', "DLLs in the game's folder, two levels down")
        check(out['folder'] == 'Games/NV|Games/NV', "the game's folder")

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
