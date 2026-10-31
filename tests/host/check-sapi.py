#!/usr/bin/env python3
"""SAPI's COM server is shipped and reachable at the path the prefix registers.

Grounded (Steam 962130) froze on its loading screen (builds 48 and 50): its
narration (SpeechSynthWrapper.dll on System.Speech in Wine Mono) created
CLSID_SpDataKey, the prefix registers that class at
C:\\windows\\system32\\Speech\\Common\\sapi.dll, and the farm had no sapi.dll,
so CoCreateInstance failed with REGDB_E_CLASSNOTREG and the unhandled
COMException brought the game down. Checks the farm's sapi.dll (ARM64EC, COM
exports, no delay imports, every import in the farm), the prefix's
registrations, and that WineProcessBridge.m links system32\\Speech\\Common to
the session's farm. Packaging only; a device run proves the rest.

Run with an optional DLL farm path to check an extracted App/IPA as well.
"""
from pathlib import Path
import re
import runpy
import struct
import sys
import tarfile

root = Path(__file__).resolve().parents[2]
PE = runpy.run_path(str(root / 'tools/check-wine-media-dlls.py'))['PE']
farm = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'app/Madeira/arm64ec-windows'
shipped = {p.name.lower(): p for p in farm.iterdir() if p.is_file()}
assert 'sapi.dll' in shipped, 'the prefix registers SAPI at Speech\\Common\\sapi.dll, but the farm has no sapi.dll'
module = PE(shipped['sapi.dll'])
pe_offset = struct.unpack_from('<I', module.data, 0x3c)[0]
machine = struct.unpack_from('<H', module.data, pe_offset + 4)[0]
assert machine in (0x8664, 0xa641), 'expected an ARM64EC-compatible COM server'
optional = pe_offset + 24
image_base = struct.unpack_from('<Q', module.data, optional + 24)[0]
config_rva, config_size = module.directories[10]
assert config_rva and config_size >= 208, 'missing ARM64EC load configuration'
metadata_va = module.unpack('<Q', module.offset(config_rva + 200, 8))[0]
assert metadata_va >= image_base, 'missing ARM64EC CHPE metadata'
exports = module.exports()
for symbol in ('DllGetClassObject', 'DllCanUnloadNow', 'DllRegisterServer', 'DllUnregisterServer'):
    assert exports.get(symbol), 'missing COM export: ' + symbol
assert not module.imports(True), 'sapi.dll keeps ARM64EC delay imports (build-modules.sh links them as plain imports)'
missing = {dep for dep in module.imports() if dep not in shipped and
           not (dep.startswith(('api-ms-', 'ext-ms-')) and 'apisetschema.dll' in shipped)}
assert not missing, 'missing sapi.dll imports: ' + ', '.join(sorted(missing))

with tarfile.open(root / 'app/Madeira/prefix-template.tar.gz') as archive:
    registry = archive.extractfile('prefix/system.reg').read().decode('utf-8')
for name, clsid in (('SpDataKey', '{D9F6EE60-58C9-458B-88E1-2F908FD7F87C}'),
                    ('SpObjectTokenCategory', '{A910187F-0C7A-45AC-92CC-59EDAFB77B53}'),
                    ('SpVoice', '{96749377-3391-11D2-9EE3-00C04F797396}'),
                    ('SpMMAudioOut', '{A8C680EB-3D32-11D2-9EE7-00C04F797396}')):
    section = r'[Software\\Classes\\CLSID\\' + clsid + r'\\InprocServer32]'
    assert section in registry, 'missing native registration of ' + name
    entry = registry.split(section, 1)[1].split('\n[', 1)[0]
    assert re.search(r'@="C:\\\\windows\\\\system32\\\\Speech\\\\Common\\\\sapi\.dll"', entry, re.I), \
        name + ' is not registered at system32\\Speech\\Common\\sapi.dll'

bridge = (root / 'app/Madeira/WineProcessBridge.m').read_text()
helper = bridge[bridge.index('static void madeira_link_speech('):]
helper = helper[:helper.index('\n}\n')]
assert 'stringByAppendingPathComponent:@"Speech/Common"' in helper and '@"sapi.dll"' in helper, 'Speech\\Common\\sapi.dll is not linked'
assert 'createSymbolicLinkAtPath:dst withDestinationPath:src' in helper and 'removeItemAtPath:dst' in helper, \
    'the link is not re-made each session (the bundle path changes on reinstall)'
assert 'madeira_link_speech(fm, prefix, @"system32", dllSource);' in bridge, 'system32\\Speech\\Common is not linked to the session farm'
farm_list = (root / 'build/wine-pe/farm-modules.txt').read_text().split()
assert 'sapi' in farm_list, 'build-modules.sh would not rebuild sapi'
print('check-sapi: ok')
