#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""The session wait loop's 1200 s cap (app/Madeira/ContentView.swift).

A Dock session is a desktop session, so only Wine exiting or the cap ends the
wait. The cap used to break into the teardown mid-game: a second detach BRK at
20 minutes, then the process died. Static checks only: the cap logs once and
keeps waiting, and the teardown never detaches twice.
"""
from pathlib import Path
import re, sys

root = Path(__file__).resolve().parents[2]
text = (root / 'app/Madeira/ContentView.swift').read_text(encoding='utf-8')
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


start = text.index('let maxWait = 1200.0')
loop = text[text.index('while wine_process_is_running() != 0 {', start):text.index('let wineElapsed = ', start)]
cap = loop[loop.index('if now - pollStart > maxWait'):]
cap = cap[:cap.index('\n                }\n')]
require(not re.search(r'^\s*break\s*$', cap, re.M), 'the cap does not leave the wait loop while Wine runs')
require('!capLogged' in cap and 'capLogged = true' in cap, 'the cap is logged once')
require(len(re.findall(r'^\s*break\s*$', loop, re.M)) == 1 and 'Early detach: game presenting and settled' in loop,
        'only the present-based early detach (not desktop sessions) breaks the loop')
teardown = text[text.index('// Step 6: Detach debugger', start):]
teardown = teardown[:teardown.index('DispatchQueue.main.async', 0)]
require('getenv("MADEIRA_DETACHED") != nil' in teardown and
        teardown.index('MADEIRA_DETACHED') < teardown.index('StikJITHelper.detachDebugger()'),
        'the teardown skips the detach after an early detach')
if failures:
    print(f'FAILURES: {failures}')
    sys.exit(1)
print('PASS: session cap')
