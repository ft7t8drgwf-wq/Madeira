#!/usr/bin/env python3
"""Report an NVIDIA GPU covers Direct3D 9 (app/Madeira/LibraryBCD.swift).

DXMT's D3D9 frontend reports its adapter by itself (dxmt/src/d3d9/d3d9_interface.cpp,
GetAdapterIdentifier) and takes d3d9.customVendorId / d3d9.customDeviceId from
DXMT_CONFIG. Fallout: New Vegas crashes loading a save (00B57AA9) on a vendor that is
not NVIDIA or AMD, so the switch sets both ids, the same GeForce RTX 3060 DXGI reports,
and leaves the description (the Metal device's name) alone.
"""
from pathlib import Path
import re, sys

root = Path(__file__).resolve().parents[2]
bcd = (root / 'app/Madeira/LibraryBCD.swift').read_text(encoding='utf-8')
failures = 0


def check(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


m = re.search(r'if nvidia \{(.*?)\n        \} else \{', bcd, re.S)
block = m.group(1) if m else ''
check('dxmtExtra.append("d3d9.customVendorId=10de")' in block, 'the switch gives Direct3D 9 the NVIDIA vendor id')
check('dxmtExtra.append("d3d9.customDeviceId=2544")' in block and 'dxmtExtra.append("dxgi.customDeviceId=2544")' in block,
      'Direct3D 9 and DXGI report the same device')
check('customDeviceDesc' not in block, "the description stays the Metal device's name")
check('setenv("MADEIRA_DXMT_EXTRA", dxmtExtra.joined(separator: ";"), 1)' in bcd, 'the ids reach DXMT_CONFIG')

d3d9 = root / 'dxmt/src/d3d9/d3d9_interface.cpp'
if d3d9.exists():
    text = d3d9.read_text(encoding='utf-8')
    check('"d3d9.customVendorId"' in text and '"d3d9.customDeviceId"' in text,
          'DXMT reads the two keys (submodule checked out)')
else:
    print('SKIP: dxmt submodule not checked out')

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
