#!/usr/bin/env python3
"""Each prefix gets a Windows MachineGuid of its own (app/Madeira/WineProcessBridge.m).

prefix-template.tar.gz carries the MachineGuid of the Mac it was made on, so every
Madeira install reported the same machine (Steam hashes the value as "BB3" of its
machine id). madeira_personalize_machine_guid rewrites the value in system.reg
before the wineserver starts: always on a fresh seed, once on an existing prefix
that still holds a template value, never on a value of the device's own.

Compiles the production helpers (cut from WineProcessBridge.m) on the host with
a stand-in LOG and checks, on registry files written here: the fresh-seed and
template cases are rewritten with a lowercase 8-4-4-4-12 version-4 value and the
rest of the file is byte-identical; a value of the device's own, a file without
the value and a missing file are left alone; two new values differ; the rewrite
goes through temp + rename (no stray temp file). No Wine, SDK or device needed.
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
SRC = (ROOT / "app/Madeira/WineProcessBridge.m").read_text(encoding="utf-8")
TEMPLATE = "2de3d850-4f7b-4098-92b5-ffbd212a9815"
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def cut(text, start, end):
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


def main():
    assert CC, "no C compiler"
    helper = cut(SRC, "/* begin madeira_machine_guid (host test cut) */", "/* end madeira_machine_guid (host test cut) */")
    assert TEMPLATE in helper, "the template GUID list must name the shipped template value"
    # the seeding code must pass whether the template was just extracted, and call the helper
    seed = cut(SRC, "void madeira_seed_prefix_if_needed(const char *prefix_path) {", "/* ====")
    assert "madeira_unique_machine_guid( prefix_path, fresh_seed )" in seed, "seeding does not personalize the MachineGuid"
    assert seed.index("madeira_repair_profile( prefix )") < seed.index("madeira_unique_machine_guid("), \
        "personalize after the registry repair, before anything reads the registry"
    prog = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <limits.h>
''' + helper + r'''
int main(int argc, char **argv)
{
    char guid[37], old[37];
    int r;
    if (argc < 3) return 2;
    if (!strcmp(argv[1], "new")) { madeira_new_machine_guid(guid); puts(guid); return 0; }
    madeira_new_machine_guid(guid);
    r = madeira_personalize_machine_guid(argv[2], atoi(argv[1]), argc > 3 ? argv[3] : guid, old);
    printf("%d %s %s\n", r, old[0] ? old : "-", argc > 3 ? argv[3] : guid);
    return 0;
}
'''
    ok = True
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "t.c").write_text(prog)
        subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-O1", "-o", str(d / "t"), str(d / "t.c")], check=True)
        t = str(d / "t")

        def run(*args):
            out = subprocess.run([t, *args], capture_output=True, text=True, check=True).stdout.split()
            return int(out[0]), out[1], out[2]

        def check(name, cond):
            nonlocal ok
            print(("ok   " if cond else "FAIL ") + name)
            ok &= bool(cond)

        head = 'WINE REGISTRY Version 2\n;; All keys relative to \\\\Machine\n\n#arch=win64\n\n'
        body = '[Software\\\\Microsoft\\\\Cryptography] 1776969663\n#time=1dcd350bcd96412\n"MachineGuid"="%s"\n\n[Software\\\\Wine] 1\n"Version"="wine-10.0"\n'
        # 1. new values are lowercase version-4 UUIDs and differ
        a, b = (subprocess.run([t, "new", "x"], capture_output=True, text=True, check=True).stdout.strip() for _ in range(2))
        check("new value is a lowercase 8-4-4-4-12 version-4 UUID: " + a, GUID_RE.match(a) and GUID_RE.match(b))
        check("two new values differ", a != b)
        # 2. template value on an existing prefix: rewritten once, rest of the file identical
        reg = d / "system.reg"
        reg.write_text(head + body % TEMPLATE)
        r, old, new = run("0", str(reg))
        after = reg.read_text()
        check("existing prefix with the template value is rewritten", r == 1 and old == TEMPLATE)
        check("only the 36 value characters changed", after == head + body % new and new != TEMPLATE)
        check("no temp file left behind", not (d / "system.reg.machine-guid").exists())
        r2, old2, new2 = run("0", str(reg))
        check("a value of the device's own is left alone", r2 == 0 and old2 == new and reg.read_text() == after)
        # 3. a fresh seed replaces whatever the template carries, even an unknown value
        reg.write_text(head + body % "11111111-2222-3333-4444-555555555555")
        r, old, new = run("1", str(reg))
        check("fresh seed replaces an unknown template value", r == 1 and old == "11111111-2222-3333-4444-555555555555"
              and reg.read_text() == head + body % new)
        # 4. an uppercase template value counts as the template too
        reg.write_text(head + body % TEMPLATE.upper())
        r, old, new = run("0", str(reg))
        check("an uppercase template value is recognised", r == 1 and reg.read_text() == head + body % new)
        # 5. no value, missing file, malformed value: untouched
        reg.write_text(head + '[Software\\\\Wine] 1\n"Version"="wine-10.0"\n')
        before = reg.read_text()
        r, old, new = run("1", str(reg))
        check("a file without the value is left alone", r == 0 and old == "-" and reg.read_text() == before)
        r, old, new = run("1", str(d / "missing.reg"))
        check("a missing file is left alone", r == 0)
        reg.write_text(head + '"MachineGuid"="short"\n')
        before = reg.read_text()
        r, old, new = run("1", str(reg))
        check("a malformed value is left alone", r == 0 and reg.read_text() == before)
        # 6. a bad replacement value fails cleanly
        reg.write_text(head + body % TEMPLATE)
        r, old, new = run("0", str(reg), "not-a-guid")
        check("a replacement that is not 36 characters is refused", r == -1 and reg.read_text() == head + body % TEMPLATE)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
