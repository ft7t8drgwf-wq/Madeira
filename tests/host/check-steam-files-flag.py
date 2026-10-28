#!/usr/bin/env python3
"""Game details > Steam: clear the "files corrupted" mark (app/Madeira/SteamFilesFlag.swift).

Steam sets StateFlags bit 32 (files missing) or 128 (files corrupted) in a game's
appmanifest_<appid>.acf; with either one Valve's client refuses every start. The
row clears both bits (132 -> 4), keeps a copy of the record first, and leaves the
rest of the record as it is.

Source checks (every host): the row is in the Steam section, the file is in the project.

Swift fixture (macOS CI with --require-swift; skipped without a compiler): the part
of SteamFilesFlag.swift above "MARK: Views" on synthetic records.
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


source = (app / 'SteamFilesFlag.swift').read_text(encoding='utf-8')
steam = (app / 'SteamGames.swift').read_text(encoding='utf-8')
project = (app.parent / 'Madeira.xcodeproj/project.pbxproj').read_text(encoding='utf-8')

check('SteamFilesFlagRows(appID: appID, library: installed.library)' in steam, "the row is in a Steam game's Steam section")
check(project.count('A1000993 /* SteamFilesFlag.swift in Sources */') == 2 and project.count('A2000993 /* SteamFilesFlag.swift */') == 3,
      'SteamFilesFlag.swift is in the app target')
check('sessionRunning' in source and 'confirmationDialog' in source, 'asks first, and refuses while a session runs')
foundation = source[:source.index('// MARK: Views')]
check('LibraryModel' not in foundation and 'SteamLog' not in foundation, 'the model part is Foundation only')

record = '"AppState"\n{\n\t"appid"\t\t"730"\n\t"name"\t\t"Counter-Strike 2"\n\t"StateFlags"\t\t"%s"\n\t"installdir"\t\t"CS2"\n}\n'

main_swift = r'''
import Foundation
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
func text(_ name: String) -> String { (try? String(contentsOf: folder.appendingPathComponent(name), encoding: .utf8)) ?? "-" }
print("marked=" + [730, 731, 732, 733, 734].map { SteamFilesFlag.isMarked(appID: $0, steamApps: folder) ? "1" : "0" }.joined())
for id in [730, 731, 732] { try SteamFilesFlag.clear(appID: id, steamApps: folder) }
print("after=" + [730, 731, 732].map { SteamFilesFlag.isMarked(appID: $0, steamApps: folder) ? "1" : "0" }.joined())
print("flags=" + [730, 731, 732].map { String(SteamFilesFlag.flags(in: text("appmanifest_\($0).acf"))?.value ?? 0) }.joined(separator: ","))
print("backup=" + (text("appmanifest_730.acf.before-clear").contains("\"132\"") ? "1" : "0") +
      (text("appmanifest_732.acf.before-clear") == "-" ? "0" : "1"))
print("same=" + (text("appmanifest_730.acf") == text("expected_730.acf") ? "1" : "0"))
print("none=" + (SteamFilesFlag.cleared("\"AppState\"\n{\n}\n") == nil ? "1" : "0"))
'''

compiler = shutil.which('swiftc')
if not compiler:
    print('SKIP: Swift compiler unavailable locally; macOS CI must run this check with --require-swift')
    if args.require_swift:
        failures += 1
else:
    with tempfile.TemporaryDirectory(prefix='madeira-steamflag-') as directory:
        temporary = Path(directory)
        (temporary / 'SteamFilesFlag.swift').write_text(foundation.replace('import SwiftUI\n', ''))
        (temporary / 'main.swift').write_text(main_swift)
        binary = temporary / 'flag'
        subprocess.run([compiler, '-swift-version', '5', str(temporary / 'SteamFilesFlag.swift'), str(temporary / 'main.swift'),
                        '-o', str(binary)], check=True)
        apps = temporary / 'steamapps'
        apps.mkdir()
        (apps / 'appmanifest_730.acf').write_text(record % '132')    # installed + corrupt
        (apps / 'appmanifest_731.acf').write_text(record % '38')     # installed + missing + update required
        (apps / 'appmanifest_732.acf').write_text(record % '4')      # fine
        (apps / 'appmanifest_733.acf').write_text(record % '128')    # not installed: left alone
        (apps / 'expected_730.acf').write_text(record % '4')
        out = dict(line.split('=', 1) for line in subprocess.run([str(binary), str(apps)], capture_output=True, text=True,
                                                                 check=True).stdout.splitlines())
        check(out['marked'] == '11000', 'the mark is seen only on installed games that carry it')
        check(out['after'] == '000', 'clearing removes the mark')
        check(out['flags'] == '4,6,4', 'only bits 32 and 128 change')
        check(out['backup'] == '10', 'a copy of the old record is kept; untouched records get none')
        check(out['same'] == '1', 'the rest of the record stays as it was')
        check(out['none'] == '1', 'a record without StateFlags is left alone')

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
