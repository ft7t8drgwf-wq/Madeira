#!/usr/bin/env python3
"""The [guest-log] mirror reads a Ren'Py game's error files, and no other text files.

The mirror in wine/dlls/ntdll/unix/file.c (ios_guest_log_mirror) copies a game's
own error lines into the session log. Ren'Py games (Doki Doki Literature Club)
write their Python errors to traceback.txt, errors.txt, log.txt and, in older
versions, stderr.txt, none of which is a *.log; build/wine-patches/0010 adds
them. This check applies the patch to a copy of the submodule's file.c, compiles
the region between the guest-log-test markers on the host with stubs for
dprintf's Wine neighbours, writes real files and checks:
  - *.log, output_log.txt and the four Ren'Py names (any case) are mirrored,
    and the path is announced once;
  - other text files (readme.txt, save.txt, options.ini) are not;
  - a Python traceback header line is kept by the default filter, and a line
    with no error word is still dropped;
  - MADEIRA_GUEST_LOG=0 still turns the mirror off.

Needs python3, git, a C compiler (CC) and the wine submodule checked out.
"""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
PATCH = ROOT / "build/wine-patches/0010-ntdll-guest-log-renpy-error-files.patch"
SRC = ROOT / "wine/dlls/ntdll/unix/file.c"

failures = []


def check(what, cond):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


if not SRC.exists():
    sys.exit("wine submodule not checked out (git submodule update --init wine)")
if not CC:
    sys.exit("no C compiler (set CC)")

tmp = Path(tempfile.mkdtemp(prefix="guest-log-"))
try:
    # Patch a copy, so the check runs whether or not apply.sh has run on the submodule.
    work = tmp / "wine"
    (work / "dlls/ntdll/unix").mkdir(parents=True)
    shutil.copy(SRC, work / "dlls/ntdll/unix/file.c")
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    rev = subprocess.run(["git", "-C", str(work), "apply", "--reverse", "--check", str(PATCH)], capture_output=True)
    if rev.returncode != 0:
        subprocess.run(["git", "-C", str(work), "apply", str(PATCH)], check=True)
    text = (work / "dlls/ntdll/unix/file.c").read_text()
    begin = text.index("/* guest-log-test:begin")
    end = text.index("/* guest-log-test:end */")
    region = text[begin:end]
    check("the region has the file-name helper and the gate calls it",
          "static int ios_guest_log_wanted( const char *name )" in region
          and "if (!ios_guest_log_wanted( name )) goto out;" in region)

    harness = tmp / "harness.c"
    harness.write_text(r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>
static unsigned int GetCurrentThreadId(void) { return 0x24; }
''' + region + r'''
int main(int argc, char **argv)
{
    int i;
    for (i = 1; i + 1 < argc; i += 2)
    {
        int fd = open(argv[i], O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd < 0) { perror(argv[i]); return 2; }
        ios_guest_log_mirror(fd, argv[i + 1], (unsigned int)strlen(argv[i + 1]));
        close(fd);
    }
    return 0;
}
''')
    exe = tmp / "harness"
    subprocess.run([CC, "-std=gnu11", "-Wall", "-Wextra", "-Wno-unused-function", "-Werror",
                    "-fsanitize=address,undefined", str(harness), "-o", str(exe)], check=True)

    files = tmp / "game"
    files.mkdir()

    def run(pairs, env_extra=None):
        args = [str(exe)]
        for name, line in pairs:
            args += [str(files / name), line]
        env = dict(os.environ)
        env.pop("MADEIRA_GUEST_LOG", None)
        env.update(env_extra or {})
        r = subprocess.run(args, capture_output=True, text=True, env=env)
        check("harness exits cleanly (%s)" % (r.stderr.strip().splitlines()[-1:] if r.returncode else "rc 0"),
              r.returncode == 0)
        return r.stderr

    wanted = ["traceback.txt", "Traceback.TXT", "errors.txt", "log.txt", "stderr.txt", "output_log.txt", "Player.log"]
    others = ["readme.txt", "save.txt", "options.ini", "mylog.txt"]
    out = run([(n, "Exception: wanted %d\n" % i) for i, n in enumerate(wanted)] +
              [(n, "Exception: other %d\n" % i) for i, n in enumerate(others)])
    for i, n in enumerate(wanted):
        check("%s is mirrored" % n, "Exception: wanted %d" % i in out)
        check("%s is announced once" % n, out.count("[guest-log] file %s\n" % (files / n)) == 1)
    for i, n in enumerate(others):
        check("%s is not mirrored" % n, "Exception: other %d" % i not in out and str(files / n) not in out)

    out = run([("traceback.txt", "Traceback (most recent call last):\n  File \"game/script.rpy\", line 1\n"
                                  "IOError: [Errno 2] No such file or directory\n")])
    check("a Python traceback header is kept", "Traceback (most recent call last):" in out)
    check("the error line after it is kept", "IOError: [Errno 2] No such file or directory" in out)
    check("a line with no error word is dropped", 'File "game/script.rpy"' not in out)

    out = run([("traceback.txt", "Exception: off\n")], {"MADEIRA_GUEST_LOG": "0"})
    check("MADEIRA_GUEST_LOG=0 turns it off", "Exception: off" not in out and "[guest-log] file" not in out)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("PASS: guest-log files" if not failures else "FAILED: guest-log files (%d)" % len(failures))
sys.exit(1 if failures else 0)
