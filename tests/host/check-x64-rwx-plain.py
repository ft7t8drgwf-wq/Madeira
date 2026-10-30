#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""[x64-rwx]: a 64-bit Java process's RWX memory is plain read/write (build/ntdll-unix/virtual_ios.c).

Project Zomboid's JVM code cache went through the JIT pool, so every store into it
was emulated (4.35 M in a C2-only load, a one-minute stall). HotSpot reserves it
read-write and commits it read-write-execute, in 64 KB multiples, so the data-heap
rule (ios_guest_anon_rwx_view_ok) refuses it. Once a pseudo-process maps jvm.dll,
its anonymous RWX views are kept plain, as ml1279 does in a 32-bit window.

Compiles ios_guest_anon_rwx_is_host_data and the [x64-rwx] helpers verbatim against
stand-in views and lookups, under AddressSanitizer and UBSan, and checks:
  * no jvm.dll: the code cache keeps the pool path;
  * after jvm.dll in this process: the code cache is plain, and the view is marked;
  * a marked view stays plain when another process asks (no move to the pool);
  * another process without jvm.dll: still pool;
  * excluded: EC_CODE requests, ARM64EC / system / image / file views, views under
    64 KB, ranges inside the pool or under an existing alias, WoW windows, and a
    range mixing a marked and an unmarked view;
  * MADEIRA_X64_RWX_PLAIN=0 never, =1 always; the process's exit forgets it;
  * the jvm.dll match is by file name only (not "notjvm.dll"), any case.
Synthetic addresses only: no Wine, iOS or device.
"""
from pathlib import Path
import os, re, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / 'build/ntdll-unix/virtual_ios.c').read_text().replace('\r\n', '\n')
CC = os.environ.get('CC') or shutil.which('cc') or 'cc'
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


def function(head):
    start = src.index(head + '\n{')
    return src[start:src.index('\n}\n', start) + 3]


defs = ''.join(line + '\n' for line in src.split('\n')
               if re.match(r'#define (VPROT_|IOS_VIEW_|IOS_X64_RWX_PLAIN_MAX)', line))
parts = [
    'static void *ios_x64_rwx_plain_pebs[IOS_X64_RWX_PLAIN_MAX];\n',
    function('static int ios_guest_rwx_data_enabled(void)'),
    function('static int ios_guest_anon_rwx_view_ok( const struct file_view *view )'),
    function('static int ios_wow_rwx_view_ok( const struct file_view *view )'),
    function('static int ios_x64_rwx_plain_mode(void)'),
    function('static int ios_x64_rwx_plain_current(void)'),
    function('static int ios_image_name_is( const UNICODE_STRING *nt_name, const char *want )'),
    function('static void ios_x64_note_image( const void *base, const UNICODE_STRING *nt_name )'),
    function('static void ios_x64_rwx_plain_forget( void *peb )'),
    function('static int ios_x64_rwx_is_host_data( uintptr_t b, uintptr_t e )'),
    function('static int ios_guest_anon_rwx_is_host_data( const void *base, size_t size )'),
]

require('ios_x64_note_image( view->base, nt_name );' in src, 'every image mapping is noted')
reclaim = function('void ios_jit_reclaim_process( void *peb )')
require('ios_x64_rwx_plain_forget( peb );' in reclaim.split('if (!peb || !rx_base) return;')[0],
        'a process exit forgets it, before the early return')
host = function('static int ios_guest_anon_rwx_is_host_data( const void *base, size_t size )')
require(host.index('ios_x64_rwx_is_host_data') < host.index('if (!ios_guest_rwx_data_enabled()'),
        'decided before the data-heap rule')

code = r'''
#define WINE_IOS 1
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint16_t WCHAR;
typedef struct { unsigned short Length, MaximumLength; WCHAR *Buffer; } UNICODE_STRING;
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define SEC_FILE   0x00800000
#define SEC_IMAGE  0x01000000
#define SEC_RESERVE 0x04000000
#define SEC_COMMIT 0x08000000
#define IOS_WOW_WINDOW_SIZE 0x100000000ull
struct file_view { void *base; size_t size; unsigned int protect, ios_flags; };
struct ios_wow_window { uintptr_t base; int wine_mono; };
''' + defs + r'''
static int dprintf_n;
#define dprintf(fd, ...) ((void)(fd), dprintf_n++)
static volatile int ios_in_mach_exc;
static int ios_alloc_ec_code;
static struct file_view *arm64ec_view;
static void *cur_peb;
static uintptr_t wow_base;
void *ios_jit_rx_base_global;
size_t ios_jit_pool_size_global;
static uintptr_t alias_lo, alias_hi;
static struct file_view views[8];
static int nviews;

static inline int is_view_valloc( const struct file_view *view )
{
    return !(view->protect & (SEC_FILE | SEC_RESERVE | SEC_COMMIT));
}
static void *ios_jit_current_peb(void) { return cur_peb; }
static uintptr_t ios_wow_base(void) { return wow_base; }
static int ios_wow_in_window( const void *a )
{
    return wow_base && (uintptr_t)a >= wow_base && (uintptr_t)a < wow_base + IOS_WOW_WINDOW_SIZE;
}
static struct ios_wow_window *ios_wow_rwx_plain_window( const void *a ) { (void)a; return NULL; }
static struct file_view *find_view( const void *addr, size_t size )
{
    (void)size;
    for (int i = 0; i < nviews; i++)
        if ((uintptr_t)addr >= (uintptr_t)views[i].base && (uintptr_t)addr < (uintptr_t)views[i].base + views[i].size)
            return &views[i];
    return NULL;
}
int ios_jit_anon_alias_find_cover( void *b, size_t s, void **rw, void **rx )
{
    (void)rw; (void)rx;
    return (uintptr_t)b < alias_hi && (uintptr_t)b + s > alias_lo;
}
''' + ''.join(parts) + r'''
static struct file_view *add( uintptr_t base, size_t size, unsigned protect )
{
    struct file_view *v = &views[nviews++];
    v->base = (void *)base; v->size = size; v->protect = protect; v->ios_flags = 0;
    return v;
}
static UNICODE_STRING name( const char *s, WCHAR *buf )
{
    UNICODE_STRING u; size_t n = strlen( s );
    for (size_t i = 0; i < n; i++) buf[i] = (WCHAR)s[i];
    u.Buffer = buf; u.Length = u.MaximumLength = (unsigned short)(n * 2);
    return u;
}
#define P1 ((void *)0x7ffe0000)
#define P2 ((void *)0x7ffd0000)
#define CACHE 0x7000000000ull
static int plain( uintptr_t b, size_t s ) { return ios_guest_anon_rwx_is_host_data( (void *)b, s ); }

int main(int argc, char **argv)
{
    WCHAR buf[128];
    UNICODE_STRING u;
    const char *mode = argc > 1 ? argv[1] : "auto";

    ios_jit_rx_base_global = (void *)0x200000000ull; ios_jit_pool_size_global = 0x40000000;
    struct file_view *cache = add( CACHE, 0xf000000, VPROT_READ | VPROT_WRITE );          /* reserved RW, 240 MB */
    struct file_view *small = add( 0x7100000000ull, 0x8000, VPROT_READ | VPROT_WRITE );
    struct file_view *ec    = add( 0x7200000000ull, 0x100000, VPROT_READ | VPROT_WRITE | VPROT_ARM64EC );
    struct file_view *img   = add( 0x7300000000ull, 0x100000, SEC_IMAGE | VPROT_READ );
    struct file_view *file  = add( 0x7400000000ull, 0x100000, SEC_FILE | VPROT_READ | VPROT_WRITE );
    struct file_view *other = add( 0x7500000000ull, 0x100000, VPROT_READ | VPROT_WRITE );
    (void)small; (void)ec; (void)img; (void)file;

    if (!strcmp( mode, "off" ))
    {
        cur_peb = P1; u = name( "C:\\zulu\\bin\\server\\jvm.dll", buf ); ios_x64_note_image( (void *)0x7600000000ull, &u );
        assert( !plain( CACHE, 0x4000 ) && !cache->ios_flags );
        puts( "MADEIRA_X64_RWX_PLAIN=0: jvm.dll mapped, code cache still pool" );
        return 0;
    }
    if (!strcmp( mode, "all" ))
    {
        cur_peb = P2;
        assert( plain( CACHE, 0x4000 ) && (cache->ios_flags & IOS_VIEW_X64_PLAIN) );
        puts( "MADEIRA_X64_RWX_PLAIN=1: plain without jvm.dll" );
        return 0;
    }

    cur_peb = P1;
    assert( !plain( CACHE, 0x4000 ) && !cache->ios_flags );
    puts( "no jvm.dll: code cache keeps the pool path" );

    u = name( "C:\\zulu\\bin\\server\\notjvm.dll", buf ); ios_x64_note_image( (void *)0x7600000000ull, &u );
    assert( !plain( CACHE, 0x4000 ) );
    u = name( "jvm.dll.mui", buf ); ios_x64_note_image( (void *)0x7600000000ull, &u );
    assert( !plain( CACHE, 0x4000 ) );
    puts( "notjvm.dll / jvm.dll.mui: not a match" );

    u = name( "\\??\\C:\\Steam\\steamapps\\common\\ProjectZomboid\\jre64\\bin\\server\\JVM.DLL", buf );
    wow_base = 0x1000000000ull;    /* a 32-bit process maps it: ignored */
    ios_x64_note_image( (void *)0x1000400000ull, &u );
    wow_base = 0;
    assert( !plain( CACHE, 0x4000 ) );
    ios_x64_note_image( (void *)0x7600000000ull, &u );
    ios_x64_note_image( (void *)0x7600000000ull, &u );   /* twice: one slot */
    assert( ios_x64_rwx_plain_pebs[0] == P1 && !ios_x64_rwx_plain_pebs[1] );
    assert( plain( CACHE + 0x4000, 0x4000 ) && (cache->ios_flags & IOS_VIEW_X64_PLAIN) );
    assert( plain( CACHE + 0xeffc000, 0x4000 ) );
    puts( "after JVM.DLL: code cache plain and marked" );

    cur_peb = P2;
    assert( plain( CACHE + 0x8000, 0x4000 ) );
    assert( !plain( 0x7500000000ull, 0x4000 ) && !other->ios_flags );
    cur_peb = NULL;
    assert( plain( CACHE, 0x4000 ) );
    puts( "marked view stays plain from another process; that process's own memory does not" );

    cur_peb = P1;
    assert( !plain( 0x7100000000ull, 0x4000 ) );
    assert( !plain( 0x7200000000ull, 0x4000 ) );
    assert( !plain( 0x7300000000ull, 0x4000 ) );
    assert( !plain( 0x7400000000ull, 0x4000 ) );
    ios_alloc_ec_code = 1; assert( !plain( 0x7500000000ull, 0x4000 ) ); ios_alloc_ec_code = 0;
    alias_lo = 0x7500000000ull; alias_hi = alias_lo + 0x4000;
    assert( !plain( 0x7500000000ull, 0x4000 ) && !other->ios_flags );
    alias_lo = alias_hi = 0;
    struct file_view *pool = add( 0x200000000ull, 0x100000, VPROT_READ | VPROT_WRITE );
    assert( !plain( 0x200000000ull, 0x4000 ) && !pool->ios_flags );
    puts( "excluded: <64 KB, ARM64EC, image, file, EC_CODE, alias, pool" );

    struct file_view *next = add( CACHE + 0xf000000, 0x100000, VPROT_READ | VPROT_WRITE );
    assert( !plain( CACHE + 0xeffc000, 0x8000 ) && !next->ios_flags );
    puts( "a range over a marked and an unmarked view: pool, nothing marked" );

    assert( plain( 0x7500000000ull, 0x4000 ) && other->ios_flags );
    puts( "another anonymous view in the JVM process: plain" );

    ios_x64_rwx_plain_forget( P1 );
    assert( !ios_x64_rwx_plain_pebs[0] );
    assert( !plain( CACHE + 0xf000000, 0x4000 ) && !next->ios_flags );
    assert( plain( CACHE, 0x4000 ) );
    puts( "exit: the process is forgotten, its marked views stay plain" );
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='madeira-x64-rwx-') as tmp:
    c, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
    c.write_text(code)
    built = subprocess.run([CC, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                            '-Wno-unused-variable', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            str(c), '-o', str(exe)], capture_output=True, text=True)
    require(built.returncode == 0, 'the decision compiles verbatim' + ('' if built.returncode == 0 else '\n' + built.stderr))
    if built.returncode == 0:
        for mode, env in (('auto', None), ('off', '0'), ('all', '1')):
            e = dict(os.environ)
            e.pop('MADEIRA_X64_RWX_PLAIN', None)
            if env is not None:
                e['MADEIRA_X64_RWX_PLAIN'] = env
            run = subprocess.run([str(exe), mode], capture_output=True, text=True, env=e)
            sys.stdout.write(run.stdout)
            require(run.returncode == 0, f'{mode}: every case passed, no sanitizer report'
                    + ('' if run.returncode == 0 else '\n' + run.stderr))

print('PASS' if not failures else f'FAIL ({failures})')
sys.exit(1 if failures else 0)
