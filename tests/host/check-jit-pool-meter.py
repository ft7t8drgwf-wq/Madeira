#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""The performance overlay's JIT memory field (app/Madeira/JITPoolMeter.swift).

Feeds log lines shaped like the JIT pool's own (a CS2 session: the pool shrunk to
560 MB, then ran out loading v8.dll) and checks the overlay text. Synthetic only.
"""
from pathlib import Path
import os, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[2]
SWIFTC = os.environ.get('SWIFTC') or shutil.which('swiftc') or str(Path.home() / '.local/share/swiftly/bin/swiftc')
checks = r'''
assert(JITPoolMeter.text(JITPoolMeter.current) == nil)
JITPoolMeter.note("[22:02:40.904] [ERR] ml1036: no hole fits a 896MB pool — SHRINKING to 560MB")
JITPoolMeter.note("[22:02:41.548] [OK] JIT pool: RX=0x148000000, RW=0x7000000000, size=560MB")
assert(JITPoolMeter.text(JITPoolMeter.current) == "JIT 0/560 MB (small)")
JITPoolMeter.note("[jit-pool] image 0x119810000+0x70000 (?) → pool 0x148004000 used=0x78000/0x23000000 tramp+0x4000")
JITPoolMeter.note("[jit-pool] reused freed range off=0x1000 size=0x2000 (freelist 1 ranges) no-madvise")
JITPoolMeter.note("[jit-pool] image 0x71ffcf0000+0x110000 (ntdll.dll) → pool 0x148078000 used=0x17600000/0x23000000 tramp+0x8000")
assert(JITPoolMeter.text(JITPoolMeter.current) == "JIT 374/560 MB (small)", JITPoolMeter.text(JITPoolMeter.current)!)
JITPoolMeter.note("[jit-pool] EXHAUSTED (image 0x73f5f00000+0x3059000): want=0x3060000 bump=0x17664000/0x23000000 tail_resv=0xa008000")
assert(JITPoolMeter.current.exhausted == 1 && JITPoolMeter.text(JITPoolMeter.current) == "JIT FULL 560 MB")
JITPoolMeter.note("[xp] 22:36:38.872 +35.70 dt=315 cpu=25")
JITPoolMeter.reset()
assert(JITPoolMeter.current == JITPoolMeter.State())
JITPoolMeter.note("[jit-pool] image 0x1+0x1 (x.dll) → pool 0x2 used=0x100000/0x25000000 tramp+0x4000")
assert(JITPoolMeter.text(JITPoolMeter.current) == "JIT 1/592 MB")
assert(JITPoolMeter.hexPair("used=0x10", after: "used=0x")! == (0x10, 0))
print("PASS: JIT memory overlay: size from setup, use from loads, small pool, FULL once exhausted, reset per session")
'''
with tempfile.TemporaryDirectory(prefix='madeira-jit-meter-') as directory:
    source = Path(directory) / 'main.swift'; binary = Path(directory) / 'check'
    source.write_text((root / 'app/Madeira/JITPoolMeter.swift').read_text() + '\n' + checks)
    subprocess.run([SWIFTC, str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
