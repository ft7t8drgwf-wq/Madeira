#!/usr/bin/env python3
"""A server reply for memory in a split pool's hole is not sent to the RW alias.

Grounded (build 51, 2026-10-30 19:32) stopped before its window opened: with
pool-split the JIT pool span was RX [0x148000000,0x17ff8c000) with hole
[0x25000000,0x25f8c000) (the main thread's stack and placeholders), the
Maine-Win64-Shipping.exe child thread's host stack was at 0x16de6e06c, inside
that hole, and ios_reply_rw_alias (build/ntdll-unix/server_ios.c) sent a reply
for it to RW 0x7025e6e06c, which is not mapped: memmove crashed in
ios_read_reply_paged. Compiles ios_jit_pool_hole_va (virtual_ios.c) and
ios_reply_rw_alias with the build 51 numbers and checks that a hole address
gets no alias, pool addresses on both sides keep theirs, the second hole
(pool-mid) counts too, an unsplit pool is unchanged, and an address outside
the span falls through to the anonymous-RWX lookup.
Needs python3 and a C compiler.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
virt = (root / 'build/ntdll-unix/virtual_ios.c').read_text()
srv = (root / 'build/ntdll-unix/server_ios.c').read_text()


def function(src, signature):
    start = src.index(signature + '\n{')
    return src[start:src.index('\n}\n', start) + 3]


macro = virt[virt.index('#define IOS_POOL_IN_HOLE(o)'):]
macro = macro[:macro.index('\n\n')] + '\n'
code = (macro + function(virt, 'int ios_jit_pool_hole_va(uintptr_t va)') +
        function(srv, 'static uintptr_t ios_reply_rw_alias( uintptr_t addr )'))

harness = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
static void *ios_jit_rx_base_global, *ios_jit_rw_base_global;
static size_t ios_jit_pool_size_global;
static size_t ios_jit_hole_off, ios_jit_hole_end, ios_jit_hole2_off, ios_jit_hole2_end;
static uintptr_t ios_jit_anon_alias_lookup( uintptr_t addr ) { return addr == 0x123450000 ? 0x7777000000 : 0; }
''' + code + r'''
static int fails;
#define EXPECT(addr, want) do { uintptr_t got = ios_reply_rw_alias( addr ); if (got != (uintptr_t)(want)) { \
    printf("FAIL: %#lx -> %#lx, want %#lx\n", (unsigned long)(addr), (unsigned long)got, (unsigned long)(want)); fails++; } } while (0)
int main(void)
{
    ios_jit_rx_base_global = (void *)0x148000000; ios_jit_rw_base_global = (void *)0x7000000000;
    ios_jit_pool_size_global = 0x37f8c000;
    EXPECT( 0x16de6e06c, 0x7025e6e06c );          /* no split yet: the old answer */
    ios_jit_hole_off = 0x25000000; ios_jit_hole_end = 0x25f8c000;
    EXPECT( 0x16de6e06c, 0 );                     /* the build 51 crash: host stack in the hole */
    EXPECT( 0x16d000000, 0 );                     /* first byte of the hole */
    EXPECT( 0x16df8bfff, 0 );                     /* last byte of the hole */
    EXPECT( 0x16cffffff, 0x7024ffffff );          /* region A just below */
    EXPECT( 0x16df8c000, 0x7025f8c000 );          /* region B just above */
    EXPECT( 0x148004000, 0x7000004000 );
    ios_jit_hole2_off = 0x30000000; ios_jit_hole2_end = 0x30100000;
    EXPECT( 0x178050000, 0 );                     /* pool-mid's second hole */
    EXPECT( 0x17ff8bfff, 0x7037f8bfff );          /* last pool byte */
    EXPECT( 0x123450000, 0x7777000000 );          /* outside the span: anonymous-RWX lookup */
    EXPECT( 0x17ff8c000, 0 );
    if (fails) return 1;
    printf("ok\n");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as d:
    c = Path(d) / 't.c'
    exe = Path(d) / 't'
    c.write_text(harness)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-o', str(exe), str(c)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    print(out.stdout, end='')
    assert out.returncode == 0, 'ios_reply_rw_alias checks failed'
assert 'extern int ios_jit_pool_hole_va( uintptr_t va );' in srv
print('check-reply-pool-hole: ok')
