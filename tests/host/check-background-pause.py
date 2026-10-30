#!/usr/bin/env python3
"""Metal games wait while Madeira is in the background
(build/dxmt-patches/0004-pause-metal-in-background.patch).

iOS refuses GPU work from a background app (MTLCommandBufferErrorDomain 7).
winemetal's commit and nextDrawable wait from WillResignActive until
DidBecomeActive, never on the main thread, behind madeira.cfg
background-pause (default 1). Checks the patch's text, that it applies on the
pinned dxmt after the earlier patches (when the submodule is checked out),
and the catalog line.
"""
from pathlib import Path
import shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
patches = root / 'build/dxmt-patches'
patch = (patches / '0004-pause-metal-in-background.patch').read_text(encoding='utf-8')
catalog = (root / 'app/Madeira/ConfigCatalog.generated.swift').read_text(encoding='utf-8')
gen = (root / 'build/tools/gen-config-catalog.py').read_text(encoding='utf-8')
failures = 0


def check(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


added = '\n'.join(l[1:] for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++'))
check(patch.count('diff --git') == 1 and 'src/winemetal/unix/winemetal_unix.c' in patch, 'one file: winemetal_unix.c')
check(not any(l.startswith('-') and not l.startswith('---') for l in patch.splitlines()), 'adds only, removes nothing')
check('madeira_cfg_bool("background-pause", 1)' in added, 'background-pause, on by default')
check('UIApplicationWillResignActiveNotification' in added and 'UIApplicationDidBecomeActiveNotification' in added,
      'waits from WillResignActive until DidBecomeActive')
check('[NSThread isMainThread]' in added and added.index('[NSThread isMainThread]') < added.index('pthread_cond_wait'),
      'the main thread never waits')
check('while (g_bg_inactive)' in added, 'a wait re-checks its condition')
check('#if TARGET_OS_IOS' in added and 'static inline void madeira_bg_wait(const char *where) { (void)where; }' in added,
      'macOS builds get an empty gate')
check('_MTLCommandBuffer_commit(void *obj) {\n   struct unixcall_generic_obj_noret *params = obj;\n+  madeira_bg_wait("commit");' in patch,
      'commit waits first (before the remote path too)')
check('_MetalLayer_nextDrawable(void *obj) {\n   struct unixcall_generic_obj_obj_ret *params = obj;\n+  madeira_bg_wait("nextDrawable");' in patch,
      'nextDrawable waits first')
check('ConfigOption(key: "background-pause", title: "Pause Metal games in the background", kind: .bool, defaultValue: "1"' in catalog
      and '"background-pause": {' in gen, 'catalog lists background-pause')

dxmt = root / 'dxmt'
if not (dxmt / 'src/winemetal/unix/winemetal_unix.c').exists() or not shutil.which('git'):
    print('SKIP: dxmt submodule not checked out, patch not applied')
else:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'dxmt'
        subprocess.run(['git', 'worktree', 'add', '--detach', '-q', str(work), 'HEAD'], cwd=dxmt, check=True)
        try:
            ok = True
            for p in sorted(patches.glob('*.patch')):
                if subprocess.run(['git', 'apply', '--reverse', '--check', str(p)], cwd=work, capture_output=True).returncode == 0:
                    continue
                r = subprocess.run(['git', 'apply', str(p)], cwd=work, capture_output=True, text=True)
                if r.returncode:
                    ok = False
                    print(r.stderr)
            check(ok, 'every dxmt patch applies on the pinned dxmt, in order')
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', str(work)], cwd=dxmt)

if failures:
    print(f'{failures} check(s) failed')
    sys.exit(1)
print('PASS: Metal work waits in the background')
