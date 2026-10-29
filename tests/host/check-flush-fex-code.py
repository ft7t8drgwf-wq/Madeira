#!/usr/bin/env python3
"""Flushes of FEX's own code buffers are not handed back to FEX; no Wine runs.

FEX flushes each block, link and unlink by its RX address. The ARM64EC wrapper
turns every flush that returns STATUS_SUCCESS into BTCpu64FlushInstructionCache,
which re-enters FEX's invalidation; an unlink issued inside an invalidation
then waits on CodeBufferListLock on its own thread (Project Zomboid, JIT on).

Compiles the production ios_flush_is_fex_code from build/ntdll-unix/virtual_ios.c
against a stub pool and carve table, and checks:
  - a range inside the pool tail (EC_CODE carves only) is FEX code;
  - a range in the head, straddling the tail edge or outside the pool is not;
  - region C counts only inside a live carve, and a contended carve lock
    counts as not FEX code (the old behaviour);
  - MADEIRA_FLUSH_NOTIFY_FEX_CODE=1 turns it off;
  - NtFlushInstructionCache still invalidates the icache first and returns
    STATUS_ALREADY_COMPLETE (not 0) only for FEX code.
Needs python3 and a C compiler (AddressSanitizer/UBSan when available).
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
native = (root / 'build/ntdll-unix/virtual_ios.c').read_text()

start = native.index('static int ios_flush_is_fex_code( const void *addr, SIZE_T size )')
helper = native[start:native.index('#endif', start)]

flush = native[native.index('NTSTATUS WINAPI NtFlushInstructionCache( HANDLE handle'):]
flush = flush[:flush.index('\n}\n')]
ios = flush[flush.index('#elif defined(WINE_IOS)'):flush.index('#elif defined(HAVE___CLEAR_CACHE)')]
assert ios.index('sys_icache_invalidate( (void *)addr, size );') < ios.index('if (ios_flush_is_fex_code( addr, size ))'), \
    'the icache is invalidated before the notification is skipped'
assert 'return STATUS_ALREADY_COMPLETE;' in ios
assert flush.rstrip().endswith('return STATUS_SUCCESS;'), 'everything else still returns STATUS_SUCCESS'
assert native.index('int ios_tail_carve_lookup_trylock(') < start and native.index('int ios_jit_low_contains(') < start

code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef size_t SIZE_T;
static void *ios_jit_rx_base_global;
static size_t ios_jit_pool_size_global;
static volatile size_t ios_jit_tail_reserved;
static int lock_busy;
static int ios_jit_low_contains( uintptr_t a ) { return a >= 0x100000000ull && a < 0x108000000ull; }
/* one live C carve at 0x101000000 (1 MB), one freed at 0x102000000 */
static int ios_tail_carve_lookup_trylock( unsigned long long rx_addr, unsigned *idx_out,
                                          unsigned long long *base_out, unsigned long long *size_out,
                                          int *free_out )
{
    (void)idx_out;
    if (lock_busy) return -1;
    if (rx_addr >= 0x101000000ull && rx_addr < 0x101100000ull)
    { *base_out = 0x101000000ull; *size_out = 0x100000; *free_out = 0; return 1; }
    if (rx_addr >= 0x102000000ull && rx_addr < 0x102100000ull)
    { *base_out = 0x102000000ull; *size_out = 0x100000; *free_out = 1; return 1; }
    return 0;
}
'''
code += helper
code += r'''
#define F(a, s) ios_flush_is_fex_code( (const void *)(uintptr_t)(a), (s) )
int main( int argc, char **argv )
{
    const int off = argc > 1 && !strcmp( argv[1], "off" );
    ios_jit_rx_base_global = (void *)(uintptr_t)0x148000000ull;
    ios_jit_pool_size_global = 0x24000000;                 /* pool ends at 0x16c000000 */
    ios_jit_tail_reserved = 0x2008000;                     /* tail from 0x169ff8000 */
    if (off)
    {
        assert( !F( 0x16acdb000ull, 4 ) && !F( 0x101000040ull, 4 ) );
        puts( "off: every flush notifies FEX" );
        return 0;
    }
    assert( F( 0x16acdb000ull, 4 ) );                      /* the PZ unlink */
    assert( F( 0x169ff8000ull, 644 ) && F( 0x16bfff000ull, 0x1000 ) );
    assert( !F( 0x169ff7ffcull, 8 ) );                     /* straddles the tail edge */
    assert( !F( 0x16bfffffcull, 8 ) );                     /* runs past the pool */
    assert( !F( 0x153b44e55ull, 16 ) );                    /* head: image copies */
    assert( !F( 0x71f3743e55ull, 16 ) && !F( 0x400000ull, 5 ) );
    assert( !F( 0x16acdb000ull, 0 ) && !F( 0, 4 ) );
    assert( F( 0x101000040ull, 4 ) );                      /* live C carve */
    assert( !F( 0x1010ffffcull, 8 ) );                     /* past its end */
    assert( !F( 0x102000040ull, 4 ) );                     /* freed C carve */
    assert( !F( 0x103000000ull, 4 ) );                     /* C, no carve */
    lock_busy = 1;
    assert( !F( 0x101000040ull, 4 ) );                     /* contended: notify as before */
    assert( F( 0x16acdb000ull, 4 ) );                      /* the tail needs no lock */
    lock_busy = 0;
    ios_jit_tail_reserved = 0;
    assert( !F( 0x16bfff000ull, 4 ) );                     /* no tail yet */
    ios_jit_rx_base_global = NULL;
    assert( !F( 0x16acdb000ull, 4 ) );                     /* no pool */
    puts( "FEX code buffer flushes stay quiet; everything else notifies" );
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='madeira-flush-fex-code-') as directory:
    folder = Path(directory)
    src = folder / 'check.c'
    src.write_text(code)
    exe = folder / 'check'
    cc = os.environ.get('CC', 'cc')
    flags = [cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter',
             '-g', str(src), '-o', str(exe)]
    sanitize = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    if subprocess.run(flags[:1] + sanitize + flags[1:], capture_output=True).returncode == 0:
        print('built with AddressSanitizer/UBSan')
    else:
        r = subprocess.run(flags, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        print('built without sanitizers')
    for value, mode in [(None, 'on'), ('0', 'on'), ('1', 'off')]:
        env = dict(os.environ)
        env.pop('MADEIRA_FLUSH_NOTIFY_FEX_CODE', None)
        if value is not None:
            env['MADEIRA_FLUSH_NOTIFY_FEX_CODE'] = value
        r = subprocess.run([str(exe), mode], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        print(f'MADEIRA_FLUSH_NOTIFY_FEX_CODE={value!r}: {r.stdout.strip()}')
print('PASS: flushes of FEX code buffers are not handed back to FEX')
