#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""The starting screen's line about what Steam downloads or installs (app/Madeira/SteamActivity.swift).

Compiles SteamActivity with the production KeyValues reader and feeds it
content_log.txt lines and app manifests shaped like Valve's client writes them.
Synthetic data only: no Steam, accounts or credentials.
"""
from pathlib import Path
import os, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
SWIFTC = os.environ.get('SWIFTC') or shutil.which('swiftc') or str(Path.home() / '.local/share/swiftly/bin/swiftc')
checks = r'''
let busy = """
[2026-10-26 04:20:01] AppID 730 state changed : Fully Installed,
[2026-10-26 04:20:02] AppID 228980 state changed : Update Required,Update Queued,
[2026-10-26 04:20:03] AppID 228980 update started : download 0/432013312, store 0/0, reuse 0/0, delta 0/0, stage 0/432013312
[2026-10-26 04:20:03] AppID 228980 state changed : Update Running,Update Started,
[2026-10-26 04:20:04] AppID 228980 update changed : Running Update,Downloading,Staging,
"""
let u = SteamActivity.updates(busy)
assert(u.count == 2 && u[0].appID == 730 && u[0].finished && u[1].appID == 228980 && !u[1].finished)
assert(SteamActivity.stage(u[1].flags) == .downloading)
let counts = SteamActivity.Bytes(downloaded: 188_743_680, toDownload: 432_013_312, staged: 0, toStage: 432_013_312)
let line = SteamActivity.line(u, name: { _ in nil }, bytes: { _ in counts })
assert(line == "Downloading Steamworks Common Redistributables: 180 MB of 412 MB (43%)", line ?? "nil")
assert(SteamActivity.line(u, name: { $0 == 228980 ? "Redist" : nil }, bytes: { _ in nil }) == "Downloading Redist…")

func lineFor(_ text: String) -> String? { SteamActivity.line(SteamActivity.updates(text), name: { _ in "Game" }, bytes: { _ in nil }) }
assert(lineFor("[t] AppID 9 state changed : Update Required,Update Queued,\n") == "Waiting in Steam's download queue: Game")
assert(lineFor("[t] AppID 9 state changed : Update Running,Update Started,Validating,\n") == "Checking the files of Game…")
assert(lineFor("[t] AppID 9 state changed : Update Running,\n[t] AppID 9 update changed : Running Update,Committing,\n") == "Installing Game…")
assert(lineFor("[t] AppID 9 state changed : Update Running,Update Started,Paused,\n") == "Steam paused the download of Game")
assert(lineFor("[t] AppID 9 state changed : Update Running,Preallocating,\n") == "Making room on disk for Game…")
assert(lineFor(busy + "[2026-10-26 04:21:00] AppID 228980 finished update (BuildID 0 => 1)\n") == nil)
assert(lineFor(busy + "[t] AppID 228980 state changed : Fully Installed,\r\n") == nil)
assert(lineFor("[t] AppID 9 update canceled : Download\n") == nil)
assert(lineFor("Got 1 download sources\nAppID x state changed : Update Running,\n") == nil)
assert(SteamActivity.size(1_610_612_736) == "1.5 GB" && SteamActivity.progress((5, 0)) == "…")
assert(SteamActivity.progress((900, 100)) == ": 0 MB of 0 MB (100%)")

// The reader: only what Steam wrote after the start began, and the manifest's counts and name.
let dir = URL(fileURLWithPath: CommandLine.arguments[1])
let client = dir.appendingPathComponent("Steam", isDirectory: true)
let logs = client.appendingPathComponent("logs", isDirectory: true), apps = client.appendingPathComponent("steamapps", isDirectory: true)
try! FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
try! FileManager.default.createDirectory(at: apps, withIntermediateDirectories: true)
let contentLog = logs.appendingPathComponent("content_log.txt")
try! "[old] AppID 440 state changed : Update Running,Update Started,Downloading,\n".write(to: contentLog, atomically: true, encoding: .utf8)
let reader = SteamActivityReader(clientRoot: client, libraries: [])
assert(reader.line() == nil)
let handle = try! FileHandle(forWritingTo: contentLog); handle.seekToEndOfFile(); handle.write(busy.data(using: .utf8)!); handle.closeFile()
let manifest = """
"AppState"
{
\t"appid"\t\t"228980"
\t"name"\t\t"Steamworks Common Redistributables"
\t"BytesToDownload"\t\t"2147483648"
\t"BytesDownloaded"\t\t"1073741824"
}
"""
try! manifest.write(to: apps.appendingPathComponent("appmanifest_228980.acf"), atomically: true, encoding: .utf8)
assert(reader.line() == "Downloading Steamworks Common Redistributables: 1.0 GB of 2.0 GB (50%)", reader.line() ?? "nil")
// Steam started a new, shorter log: all of it is new.
try! "[t] AppID 228980 state changed : Update Running,Validating,\n".write(to: contentLog, atomically: true, encoding: .utf8)
assert(reader.line() == "Checking the files of Steamworks Common Redistributables…", reader.line() ?? "nil")
assert(SteamActivityReader(clientRoot: dir.appendingPathComponent("none"), libraries: []).line() == nil)
assert(DockStartStatusElapsed(45) == "45 s" && DockStartStatusElapsed(309) == "5 min 9 s")
print("PASS: Steam activity line: queue, download with sizes, install, file check, pause, finish and cancel, new lines only, manifest counts; elapsed time words")
'''
screen = (app / 'DockStartScreen.swift').read_text()
elapsed = screen[screen.index('    static func elapsed('):]
elapsed = elapsed[:elapsed.index('\n    }\n') + 7].replace('static func elapsed(', 'func DockStartStatusElapsed(')
with tempfile.TemporaryDirectory(prefix='madeira-steam-activity-') as directory:
    source = Path(directory) / 'main.swift'; binary = Path(directory) / 'check'
    source.write_text((app / 'SteamKeyValues.swift').read_text() + '\n'
                      + (app / 'SteamActivity.swift').read_text().replace('import Foundation\n', '', 1) + '\n'
                      + elapsed + '\n' + checks)
    subprocess.run([SWIFTC, str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary), directory], check=True)
