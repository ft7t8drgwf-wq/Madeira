#!/usr/bin/env python3
"""Settings > Registry (app/Madeira/WineRegistryEditor.swift).

Browse and change Wine's registry (system.reg, user.reg) in the app, only while no
session runs. A change rewrites only the lines it touches: timestamps, #time= lines
and Wine's escaping elsewhere stay.

Source checks (every host): the page is in Settings, the file is in the project,
writes are refused while a session runs or when the file changed.

Swift fixture (macOS CI with --require-swift; skipped without a compiler): the part
of WineRegistryEditor.swift above "MARK: Views" on a synthetic registry file.
"""
from pathlib import Path
import argparse, shutil, subprocess, sys, tempfile

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


source = (app / 'WineRegistryEditor.swift').read_text(encoding='utf-8')
library = (app / 'Library.swift').read_text(encoding='utf-8')
project = (app.parent / 'Madeira.xcodeproj/project.pbxproj').read_text(encoding='utf-8')

check('case .registry: RegistryEditorView()' in library and 'settingsSheet = .registry' in library,
      'Settings opens the registry editor as a sheet hung off the Form')
# Every sheet switch over SettingsSheet (Settings and the developer screen) has to name the new case.
switches = [path.name for path in sorted(app.glob('*.swift'))
            if 'case .steamSignIn: SteamSignInView()' in path.read_text(encoding='utf-8')]
check(switches and all('case .registry: RegistryEditorView()' in (app / name).read_text(encoding='utf-8') for name in switches),
      'every SettingsSheet switch opens the registry editor: ' + ', '.join(switches))
check(project.count('A1000992 /* WineRegistryEditor.swift in Sources */') == 2 and
      project.count('A2000992 /* WineRegistryEditor.swift */') == 3, 'WineRegistryEditor.swift is in the app target')
change = source[source.index('func change('):source.index('/// Settings › Registry: the two files')]
check('guard !Self.sessionRunning' in change and 'now == loaded[file]' in change and '"before-edit"' in change,
      'no write while a session runs or after the file changed; a copy is kept first')
foundation = source[:source.index('// MARK: Views')]
check('LibraryModel' not in foundation and 'LogStore' not in foundation, 'the model part is Foundation only')

main_swift = r'''
import Foundation
func show(_ s: String) -> String { s.replacingOccurrences(of: "\n", with: "<LF>") }
let text = """
WINE REGISTRY Version 2
;; All keys relative to \\\\User\\\\S-1-5-21-0-0-0-1000

#arch=win64

[Software\\\\Valve\\\\Half-Life\\\\Settings] 1700000000
#time=1da0000000000000
"CrashInitializingVideoMode"=dword:00000001
"EngineD3D"=dword:0000000a

[Software\\\\Wine\\\\AppDefaults\\\\FalloutNV.exe\\\\DllOverrides] 1700000001
#time=1da0000000000001
@="default"
"d3d9"="native,builtin"
"Path"=str(2):"%SystemRoot%\\\\x"
"Quote \\"q\\""="a\\\\b\\"c\\x00e9"
"Bin"=hex:01,02,\\
  03,04
"After"="z"

"""
var r = WineRegistry(text: text)
print("same=\(r.text == text)")
print("keys=" + r.keys.map(\.path).joined(separator: "|"))
print("subkeys=" + r.subkeys(of: "").joined(separator: ",") + "|" + r.subkeys(of: "software\\wine").joined(separator: ","))
let nv = r.key("Software\\Wine\\AppDefaults\\FalloutNV.exe\\DllOverrides")!
print("values=" + nv.values.map { "\($0.name)=\($0.data.display)" }.joined(separator: "|"))
print("bin=\(nv.values.first { $0.name == "Bin" }!.lines)")
r.set("Software\\Valve\\Half-Life\\Settings", "crashinitializingvideomode", .dword(0))
r.set("Software\\Valve\\Half-Life\\Settings", "New", .string("é \"x\""))
r.remove("Software\\Wine\\AppDefaults\\FalloutNV.exe\\DllOverrides", value: "bin")
print("edited=" + show(r.text))
r.set("Software\\Bethesda Softworks\\FalloutNV", "Installed Path", .string("C:\\Games\\NV\\"), now: Date(timeIntervalSince1970: 1800000000))
print("added=" + show(r.text.components(separatedBy: "\n").suffix(5).joined(separator: "\n")))
print("reread=" + (WineRegistry(text: r.text).key("software\\bethesda softworks\\falloutnv")?.values.first?.data.display ?? "nil"))
r.removeKey("Software\\Wine")
print("removed=" + r.keys.map(\.path).joined(separator: "|") + "|" + "\(r.text.contains("DllOverrides"))")
print("escape=" + WineRegistry.escapeKey("A[1]\\B") + "|" + WineRegistry.unescape("\\x41\\101\\q"))
'''

compiler = shutil.which('swiftc')
if not compiler:
    print('SKIP: Swift compiler unavailable locally; macOS CI must run this check with --require-swift')
    if args.require_swift:
        failures += 1
else:
    with tempfile.TemporaryDirectory(prefix='madeira-reg-') as directory:
        temporary = Path(directory)
        (temporary / 'WineRegistryEditor.swift').write_text(foundation.replace('import SwiftUI\n', ''))
        (temporary / 'main.swift').write_text(main_swift)
        binary = temporary / 'reg'
        subprocess.run([compiler, '-swift-version', '5', str(temporary / 'WineRegistryEditor.swift'), str(temporary / 'main.swift'),
                        '-o', str(binary)], check=True)
        out = dict(line.split('=', 1) for line in subprocess.run([str(binary)], capture_output=True, text=True,
                                                                 check=True).stdout.splitlines())
        check(out['same'] == 'true', 'an unchanged file comes back byte for byte')
        check(out['keys'] == 'Software\\Valve\\Half-Life\\Settings|Software\\Wine\\AppDefaults\\FalloutNV.exe\\DllOverrides',
              'key paths unescaped')
        check(out['subkeys'] == 'Software|AppDefaults', 'subkeys, also of keys with no lines of their own')
        check(out['values'] == '=default|d3d9=native,builtin|Path=%SystemRoot%\\x|Quote "q"=a\\b"c\u00e9|Bin=hex:01,02,03,04|After=z',
              'values read: default, text, %text%, escapes, hex continued over two lines')
        check(out['bin'] == '16..<18', "a continued value's lines")
        edited = out['edited']
        check('"CrashInitializingVideoMode"=dword:00000000<LF>"EngineD3D"=dword:0000000a<LF>"New"="\\x00e9 \\"x\\""<LF><LF>[Software' in edited,
              'a value changed in place (its name kept), a new one after the last value, escaped as Wine does')
        check('#time=1da0000000000000' in edited and '] 1700000001<LF>' in edited, 'timestamps elsewhere stay')
        check('"Bin"' not in edited and '  03,04' not in edited and '"After"="z"' in edited, 'a removed value takes its continuation line')
        check(out['added'] == '<LF>[Software\\\\Bethesda Softworks\\\\FalloutNV] 1800000000<LF>#time=1dda4c66b338000<LF>'
              '"Installed Path"="C:\\\\Games\\\\NV\\\\"<LF>', 'a new key gets a timestamp line and a #time= line')
        check(out['reread'] == 'C:\\Games\\NV\\', 'a new value reads back the same')
        check(out['removed'] == 'Software\\Valve\\Half-Life\\Settings|Software\\Bethesda Softworks\\FalloutNV|false',
              'deleting a key deletes its subkeys')
        check(out['escape'] == 'A\\[1\\]\\\\B|AAq', "Wine's escaping for key names and \\x, octal, other escapes")

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
