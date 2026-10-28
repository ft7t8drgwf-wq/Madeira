#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 Madeira contributors
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Static host checks for the GOG store (docs/GOG.md).

Never contacts GOG. Checks licence headers, every GOG source in the Xcode
project, the device-only Keychain item, no token or code in a log line, GOG
games kept out of Other games, every Settings sheet switch handling the GOG
sign-in, the settings catalog entry, and the play task reader's rules on a
sample goggame-<id>.info (mirrored here in Python).
"""
from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


sources = sorted((app / 'SwiftGOG').glob('*.swift')) + [app / 'GOGLibrary.swift', app / 'GOGGames.swift']
project = (app.parent / 'Madeira.xcodeproj/project.pbxproj').read_text()
for path in sources:
    require(path.exists(), f'{path.name}: exists')
sources = [p for p in sources if p.exists()]
for path in sources:
    text = path.read_text()
    require(text.startswith('// SPDX-License-Identifier: GPL-3.0-or-later'), f'{path.name}: licence header')
    require(re.search(r'/\* (SwiftGOG/)?' + re.escape(path.name) + r' in Sources \*/,', project) is not None,
            f'{path.name}: in the Xcode project sources')
    require('thebcd69' not in text and 'BCD Material' not in text, f'{path.name}: no BCD code or credit lines')

api = (app / 'SwiftGOG/GOGAPI.swift').read_text()
require('kSecAttrAccessibleWhenUnlockedThisDeviceOnly' in api and 'kSecAttrSynchronizable as String: false' in api,
        'tokens: one device-only Keychain item, not synchronised')
for path in sources:
    for line in path.read_text().splitlines():
        if 'GOGLog.event' in line or 'LogStore' in line:
            compact = line.replace(' ', '')
            bad = [w for w in ('accessToken', 'refreshToken', 'code', 'userName', 'userID', 'accountName', 'url')
                   if '\\(' + w in compact]
            if bad:
                require(False, f'{path.name}: no credential in a log line: {line.strip()[:80]}')

library = (app / 'Library.swift').read_text()
require('var gogProductID: String?' in library, 'library entries record their GOG product')
require(library.count('$0.steamAppID == nil && $0.gogProductID == nil') >= 2,
        'Other games: no GOG game (it is listed in the GOG section)')
require('case .gogSignIn: GOGSignInView()' in library and 'gogSignIn' in library[library.index('enum SettingsSheet'):],
        'Settings: the GOG sign-in sheet')
content = (app / 'ContentView.swift').read_text()
require('case .gogSignIn: GOGSignInView()' in content, 'the developer strip handles the GOG sign-in sheet')
require('GOGLibrary.shared.sessionChanged(active: true)' in content, 'GOG downloads pause for a game session')
catalog = (app / 'ConfigCatalog.generated.swift').read_text()
require('key: "env.MADEIRA_GOG"' in catalog, 'Settings › All settings lists env.MADEIRA_GOG')
require('case .gog: GOGEntrySection(' in library, 'Game details: the GOG page')
gog = '\n'.join(path.read_text() for path in sources)
require(re.search(r'\bEpic[A-Z]\w*', gog) is None, 'GOG code stands on its own (no Epic store types)')


# The play task reader (GOGLibrary.playTask(info:)), mirrored.
def play_task(info):
    tasks = info.get('playTasks') or []
    files = [t for t in tasks if t.get('type', 'FileTask') == 'FileTask' and isinstance(t.get('path'), str)]
    task = next((t for t in files if t.get('isPrimary') is True), None) \
        or next((t for t in files if t.get('category', 'game') == 'game'), None) or (files[0] if files else None)
    if not task:
        return None
    return task['path'].replace('\\', '/').strip('/'), task.get('arguments', ''), task.get('workingDir')


sample = json.loads('''{"gameId": "1207664663", "playTasks": [
  {"category": "document", "type": "FileTask", "path": "manual.pdf"},
  {"category": "game", "type": "URLTask", "link": "https://www.gog.com"},
  {"category": "game", "isPrimary": true, "type": "FileTask", "path": "bin\\\\x64\\\\game.exe",
   "arguments": "-nolauncher", "workingDir": "bin\\\\x64"}]}''')
require(play_task(sample) == ('bin/x64/game.exe', '-nolauncher', 'bin\\x64'), 'play task: the primary file task')
library_source = (app / 'GOGLibrary.swift').read_text()
require('$0["isPrimary"] as? Bool == true' in library_source and '"FileTask"' in library_source,
        'play task: the Swift reader follows the same rules')

print('\nAll GOG store checks passed.' if failures == 0 else f'\n{failures} GOG store check(s) failed.')
raise SystemExit(1 if failures else 0)
