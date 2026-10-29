#!/usr/bin/env python3
"""Game details › Steam: a note when the program Steam's launch settings start is
not in the game's folder (Valve's client then stops with launch-client-error 28,
"could not find the game's executable", as Black Ops 2 did).

The note uses Steam's cached launch settings only, appears only for an installed
game with no download running, and offers Repair installed files where Madeira
manages the install. Source checks only (SteamGames.swift needs the app to build).
"""
from pathlib import Path
import re, sys

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
failures = 0


def check(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


games = (app / 'SteamGames.swift').read_text(encoding='utf-8')
dock = (app / 'MadeiraDock.swift').read_text(encoding='utf-8')

helper = games[games.index('static func missingProgram('):games.index("/// The install folder's Windows programs for the Program picker")]
check('choose(options, installFolder: root) == nil' in helper, 'no note when choose() finds a program on disk')
check('!otherKinds.contains(option.type.lowercased())' in helper and 'option.requiredDLC' in helper and 'option.betaKey.isEmpty' in helper,
      "the note looks at the same entries choose() does")
resolve = games[games.index('private func resolveProgram() async {'):]
check('steam.game(appID)?.launches ?? []' in resolve and 'launchOptions(appID: appID)' not in resolve[:resolve.index('SteamDirectStart.missingProgram(')],
      "only Steam's cached launch settings are used for the note")
check(re.search(r'if installed \{\s*missingProgram = await Task\.detached', resolve) is not None, 'only for an installed game, off the main thread')
check('if let missingProgram, download == nil, dockProgram == nil {' in games and '(downloads ? " Repair installed files downloads it again." : "")' in games,
      'shown with no download running; Repair offered only where Madeira manages the install')
check('case 28: return "Steam could not find the game\'s executable. Game details › Steam shows which program is missing when it can tell."' in dock,
      'the launch error points to Game details')

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
