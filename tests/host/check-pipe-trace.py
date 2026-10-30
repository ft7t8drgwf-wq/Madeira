#!/usr/bin/env python3
r"""[pipe-trace] follows any named pipe, both directions (dlls/ntdll/unix/file.c).

Steam's client service hands the CEG module's answer to the Steam client over
anonymous pipes (\\.\pipe\Win32.Pipes.<pid>.<n>), 32 KB a message, read 1 KB at
a time; the tracer used to show only writes to rgsc_ pipes, 48..1024 bytes each.
madeira_pipe_trace_io now takes the name to match from MADEIRA_PIPE_TRACE_MATCH,
traces reads with MADEIRA_PIPE_TRACE_READS=1 and shows up to 65536 bytes.

Compiles the production function (cut from the patched file.c, or from the patch in
build/wine-unix-patches when the submodule is not patched) on the host with
stand-ins for NtQueryObject, the TEB and dprintf, and checks: off by default; the
default name is rgsc_; MATCH is matched in any case against the pipe's object
name and a handle with another name is not traced; reads are off unless asked;
the BYTES and LIMIT clamps; a line up to 1024 bytes has spaced hex and a text
column, a longer one plain hex and no text; the name is looked up once per
(process, handle); and NtReadFile calls the tracer at its single exit with the
bytes actually read. No Wine, SDK or device needed.
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
FILE_C = ROOT / "wine/dlls/ntdll/unix/file.c"
PATCH = ROOT / "build/wine-unix-patches/0001-ntdll-pipe-trace-any-pipe-both-directions.patch"
START, END = "static void madeira_pipe_trace_io(", "static void madeira_pipe_trace( HANDLE handle, const void *buffer, ULONG length )\n{\n    madeira_pipe_trace_io( handle, buffer, length, FALSE );\n}"


def source():
    text = FILE_C.read_text(encoding="utf-8", errors="replace") if FILE_C.exists() else ""
    if START in text:
        return text, "wine/dlls/ntdll/unix/file.c"
    # the submodule is unpatched: rebuild the function from the patch's added lines
    lines = []
    for line in PATCH.read_text(encoding="utf-8").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
        elif line.startswith(" "):
            lines.append(line[1:])
    return "\n".join(lines) + "\n", PATCH.name


def main():
    assert CC, "no C compiler"
    text, where = source()
    i = text.index(START)
    body = text[i:text.index(END, i) + len(END)]
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + name)
        ok &= bool(cond)

    check("NtReadFile reports what it read at its single exit (" + where + ")",
          "madeira_pipe_trace_io( handle, buffer, total, TRUE )" in text)
    prog = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned short WCHAR;
typedef unsigned int ULONG;
typedef int BOOL;
typedef void *HANDLE;
typedef unsigned long ULONG_PTR;
#define TRUE 1
#define FALSE 0
typedef struct { unsigned short Length, MaximumLength; WCHAR *Buffer; } UNICODE_STRING;
typedef struct { UNICODE_STRING Name; } OBJECT_NAME_INFORMATION;
enum { ObjectNameInformation = 1 };
struct teb { void *Peb; struct { HANDLE UniqueProcess, UniqueThread; } ClientId; };
static struct teb g_teb = { (void *)0x1000, { (HANDLE)4, (HANDLE)0x44 } };
#define NtCurrentTeb() (&g_teb)
#define HandleToULong(h) ((ULONG)(ULONG_PTR)(h))
static const char *g_names[16];     /* object name per handle value 1..15 */
static int g_queries;
static int NtQueryObject( HANDLE h, int cls, OBJECT_NAME_INFORMATION *oni, ULONG len, ULONG *used )
{
    static WCHAR w[256]; const char *n; unsigned i;
    (void)cls; (void)len; (void)used; g_queries++;
    n = g_names[(ULONG_PTR)h & 15];
    if (!n) return -1;
    for (i = 0; n[i] && i < 255; i++) w[i] = (unsigned char)n[i];
    oni->Name.Buffer = w; oni->Name.Length = (unsigned short)(i * sizeof(WCHAR));
    return 0;
}
static char g_out[1 << 20]; static size_t g_len;
static int dprintf( int fd, const char *fmt, ... )
{
    va_list ap; int r; (void)fd; va_start( ap, fmt );
    r = vsnprintf( g_out + g_len, sizeof(g_out) - g_len, fmt, ap ); va_end( ap );
    if (r > 0) g_len += (size_t)r;
    return r;
}
''' + body + r'''
int main( int argc, char **argv )
{
    unsigned char *big = malloc( 70000 ); unsigned i;
    (void)argc;
    for (i = 0; i < 70000; i++) big[i] = (unsigned char)(i * 7);
    g_names[1] = "\\Device\\NamedPipe\\Win32.Pipes.00000188.00000001";
    g_names[2] = "\\Device\\NamedPipe\\chrome.rgsc_ipc_1234_channel_0";
    g_names[3] = "\\??\\C:\\windows\\system32\\kernel32.dll";
    if (!strcmp( argv[1], "write-all" ))
    {
        madeira_pipe_trace( (HANDLE)1, "hello pipe", 10 );
        madeira_pipe_trace( (HANDLE)2, "hello rgsc", 10 );
        madeira_pipe_trace( (HANDLE)3, "hello file", 10 );
        madeira_pipe_trace_io( (HANDLE)1, "read back", 9, TRUE );
        madeira_pipe_trace( (HANDLE)1, "again", 5 );
        printf( "queries=%d\n", g_queries );
    }
    else if (!strcmp( argv[1], "long" ))
    {
        madeira_pipe_trace( (HANDLE)1, big, 1024 );
        madeira_pipe_trace( (HANDLE)1, big, 31752 );
        madeira_pipe_trace( (HANDLE)1, big, 70000 );
    }
    fwrite( g_out, 1, g_len, stdout );
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "t.c").write_text(prog)
        subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-O1", "-o", str(d / "t"), str(d / "t.c")], check=True)
        t = str(d / "t")

        def run(mode, **env):
            e = {k: v for k, v in os.environ.items() if not k.startswith("MADEIRA_PIPE_TRACE")}
            e.update(env)
            return subprocess.run([t, mode], capture_output=True, text=True, check=True, env=e).stdout

        out = run("write-all")
        check("off unless MADEIRA_PIPE_TRACE=1", "[pipe-trace]" not in out)
        out = run("write-all", MADEIRA_PIPE_TRACE="1")
        check("default: writes to rgsc_ pipes only", out.count("[pipe-trace] #") == 1 and "hello rgsc" in out
              and "hello pipe" not in out and "hello file" not in out)
        check("the banner names the match and the sizes", 'whose name has "rgsc_", 2000 lines, 48 bytes' in out)
        out = run("write-all", MADEIRA_PIPE_TRACE="1", MADEIRA_PIPE_TRACE_MATCH="win32.PIPES")
        check("MATCH is matched in any case; other pipes and files are not traced",
              out.count("[pipe-trace] #") == 2 and "hello pipe" in out and "again" in out
              and "hello rgsc" not in out and "read back" not in out)
        check("the name is looked up once per (process, handle)", "queries=3" in out)
        out = run("write-all", MADEIRA_PIPE_TRACE="1", MADEIRA_PIPE_TRACE_MATCH="Win32.Pipes", MADEIRA_PIPE_TRACE_READS="1")
        check("reads are traced when asked, marked read", "read peb=" in out and "read back" in out
              and out.count("[pipe-trace] #") == 3 and "writes and reads" in out)
        out = run("write-all", MADEIRA_PIPE_TRACE="1", MADEIRA_PIPE_TRACE_MATCH="Win32.Pipes", MADEIRA_PIPE_TRACE_LIMIT="1")
        check("LIMIT caps the lines", out.count("[pipe-trace] #") == 1)
        out = run("long", MADEIRA_PIPE_TRACE="1", MADEIRA_PIPE_TRACE_MATCH="Win32.Pipes", MADEIRA_PIPE_TRACE_BYTES="65536")
        lines = [l for l in out.splitlines() if l.startswith("[pipe-trace] #")]
        check("BYTES up to 65536 is accepted", "65536 bytes a line" in out and len(lines) == 3)
        l1, l2, l3 = lines
        check("1024 bytes: spaced hex and a text column", "len=1024 | 00 07 0e 15" in l1 and l1.rstrip().endswith("|") is False and l1.count(" ") > 1030)
        hex2 = l2.split(" | ")[1].split("| ")[0]
        check("31752 bytes: plain hex, every byte, no text column", len(hex2) == 2 * 31752 and " " not in hex2 and l2.endswith("| "))
        hex3 = l3.split(" | ")[1].split("| ")[0]
        check("70000 bytes: cut at BYTES", len(hex3) == 2 * 65536 and "len=70000" in l3)
        out = run("long", MADEIRA_PIPE_TRACE="1", MADEIRA_PIPE_TRACE_MATCH="Win32.Pipes", MADEIRA_PIPE_TRACE_BYTES="999999")
        check("an out-of-range BYTES falls back to 48", "48 bytes a line" in out)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
