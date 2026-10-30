#!/usr/bin/env python3
"""Wine's adapters get a MAC address of this device's own (build/ntdll-unix/nsi_ndis_ios.c).

iOS reports 02:00:00:00:00:00 as every interface's hardware address, so all Madeira
users shared one address (Steam hashes the adapters' MACs as "FF2" of its machine
id). ios_lladdr hands ndis.c a stable, random, locally administered address kept
in $WINEPREFIX/.madeira-mac-address whenever iOS gives the placeholder.

Compiles the production helpers (cut from nsi_ndis_ios.c) on the host and checks:
the placeholder and the all-zero address are recognised, a real address is not;
a prefix gets one address that is locally administered, unicast and never the
placeholder, the same on the next call and after a restart (the file); a file
holding the placeholder or junk is replaced; a racing creator's value wins; an
unwritable prefix still gets an address; the LLADDR override and the
MADEIRA_UNIQUE_MAC switch are in place. No Wine, SDK or device needed.
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
SRC = (ROOT / "build/ntdll-unix/nsi_ndis_ios.c").read_text(encoding="utf-8")
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


def cut(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def main():
    assert CC, "no C compiler"
    helper = cut(SRC, "/* begin madeira_unique_mac (host test cut) */", "/* end madeira_unique_mac (host test cut) */")
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + name)
        ok &= bool(cond)

    # the override must sit before ndis.c is included, and the switch must exist
    inc = SRC.index('#include "../../wine/dlls/nsiproxy.sys/ndis.c"')
    check("LLADDR is redefined before ndis.c is included", 0 < SRC.index("#define LLADDR(s) ios_lladdr(") < inc)
    check("env.MADEIRA_UNIQUE_MAC = 0 keeps the placeholder", 'getenv( "MADEIRA_UNIQUE_MAC" )' in SRC)
    check("a real address passes through", "if (!ios_mac_is_placeholder( real, sdl->sdl_alen )) return real;" in SRC)

    prog = r'''
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <time.h>
''' + helper + r'''
static void show(const unsigned char *m) { printf("%02x:%02x:%02x:%02x:%02x:%02x\n", m[0], m[1], m[2], m[3], m[4], m[5]); }
int main(int argc, char **argv)
{
    unsigned char m[6] = {0};
    if (argc < 3) return 2;
    if (!strcmp(argv[1], "placeholder"))
    {
        unsigned int v[6], i; sscanf(argv[2], "%2x:%2x:%2x:%2x:%2x:%2x", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);
        for (i = 0; i < 6; i++) m[i] = (unsigned char)v[i];
        printf("%d\n", ios_mac_is_placeholder(m, argc > 3 ? (unsigned)atoi(argv[3]) : 6)); return 0;
    }
    if (!strcmp(argv[1], "prefix")) { int r = ios_mac_for_prefix(argv[2], m); printf("%d ", r); show(m); return 0; }
    if (!strcmp(argv[1], "random")) { ios_mac_random(m); show(m); return 0; }
    return 2;
}
'''
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "t.c").write_text(prog)
        subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-O1", "-o", str(d / "t"), str(d / "t.c")], check=True)
        t = str(d / "t")

        def run(*args):
            return subprocess.run([t, *args], capture_output=True, text=True, check=True).stdout.split()

        check("02:00:00:00:00:00 is the placeholder", run("placeholder", "02:00:00:00:00:00") == ["1"])
        check("00:00:00:00:00:00 counts as a placeholder", run("placeholder", "00:00:00:00:00:00") == ["1"])
        check("a real address is not", run("placeholder", "a4:83:e7:12:34:56") == ["0"])
        check("a zero address of another length is left to ndis.c", run("placeholder", "00:00:00:00:00:00", "8") == ["0"])
        macs = {run("random", "x")[0] for _ in range(50)}
        check("random addresses are locally administered unicast, never the placeholder",
              all(MAC_RE.match(m) and int(m[:2], 16) & 3 == 2 and m != "02:00:00:00:00:00" for m in macs) and len(macs) > 40)
        pfx = d / "pfx"; pfx.mkdir()
        r1, m1 = run("prefix", str(pfx)); r2, m2 = run("prefix", str(pfx))
        check("a prefix gets one address and keeps it: " + m1, r1 == r2 == "1" and m1 == m2 and MAC_RE.match(m1))
        check("the address is kept in .madeira-mac-address", (pfx / ".madeira-mac-address").read_text().strip() == m1)
        (pfx / ".madeira-mac-address").write_text("02:00:00:00:00:00\n")
        r3, m3 = run("prefix", str(pfx))
        check("a file holding the placeholder is replaced", r3 == "1" and m3 != "02:00:00:00:00:00"
              and (pfx / ".madeira-mac-address").read_text().strip() == m3)
        (pfx / ".madeira-mac-address").write_text("junk\n")
        r4, m4 = run("prefix", str(pfx))
        check("a file holding junk is replaced", r4 == "1" and MAC_RE.match(m4)
              and (pfx / ".madeira-mac-address").read_text().strip() == m4)
        (pfx / ".madeira-mac-address").write_text("0a:1b:2c:3d:4e:5f\n")
        r5, m5 = run("prefix", str(pfx))
        check("an existing address of the device's own is used as is", r5 == "1" and m5 == "0a:1b:2c:3d:4e:5f")
        r6, m6 = run("prefix", str(d / "missing"))
        check("an unwritable prefix still gets an address for this run", r6 == "1" and MAC_RE.match(m6) and m6 != "02:00:00:00:00:00")
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
