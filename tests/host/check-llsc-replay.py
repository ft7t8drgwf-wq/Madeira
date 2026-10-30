#!/usr/bin/env python3
"""An LDXR/LDAXR ... STXR/STLXR pair whose step between cannot be undone is
replayed forward instead of refused (ml1290); no Wine runs.

Grounded (Steam 962130, Unreal 4) ended on build 47 (log 2026-10-29 19:07):
its main thread ran ntdll's atomic bit clear
    ldaxr w11, [x8]; and w11, w11, w10; stlxr w12, w11, [x8]
on a 64 KB HEAP_CREATE_ENABLE_EXECUTE heap that lives behind a JIT-pool alias.
ml1284 only undid ADD/SUB immediates, so the STLXR was refused, redelivered
2,000 times, and ml461 terminated the process. build/ntdll-unix/
signal_arm64_ios.c's ios_llsc_sim now replays the step. Compiles it (with
ios_llsc_reg, ios_llsc_shift and ios_llsc_bitmask, from the source) against a
fake thread state, and checks with encodings from the AArch64 assembler:
  - the crash's own AND clears the bit, at W width;
  - logical immediate (ORR, AND X, ANDS), logical shifted register (BIC, EOR
    ROR, ORN), ADD/SUB immediate and shifted register, MOVZ/MOVK and MOV WZR
    give what the hardware gives;
  - MADD, an ADD from SP, a step writing another register and a W step under
    an X load are refused;
and textually that the STLXR branch replays only when ml1284 cannot undo,
compares the replay of the current value with the stored one, and skips the
swap (Ws = 1) when they differ.
Needs python3 and a C compiler.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
src = (root / 'build/ntdll-unix/signal_arm64_ios.c').read_text()


def function(signature):
    start = src.index(signature + '\n{')
    return src[start:src.index('\n}\n', start) + 3]


code = (function('static int ios_llsc_reg( const arm_thread_state64_t *st, int r, int ld_rt, uint64_t v, uint64_t *out )') +
        function('static uint64_t ios_llsc_shift( uint64_t x, unsigned type, unsigned amt, int is64 )') +
        function('static int ios_llsc_bitmask( unsigned n, unsigned immr, unsigned imms, int is64, uint64_t *out )') +
        function('static int ios_llsc_sim( uint32_t op, int ld_rt, int is64, const arm_thread_state64_t *st, uint64_t *v )'))

harness = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint64_t __x[29], __fp, __lr, __sp, __pc; uint32_t __cpsr, __pad; } arm_thread_state64_t;
''' + code + r'''
static arm_thread_state64_t st;
static int fails;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL: " __VA_ARGS__); printf("\n"); fails++; } } while (0)

static void expect(uint32_t op, int ld_rt, int is64, uint64_t in, uint64_t want, const char *what)
{
    uint64_t v = in;
    int ok = ios_llsc_sim(op, ld_rt, is64, &st, &v);
    CHECK(ok && v == want, "%s: ok=%d got %#llx want %#llx", what, ok, (unsigned long long)v, (unsigned long long)want);
}

static void refuse(uint32_t op, int ld_rt, int is64, const char *what)
{
    uint64_t v = 0x1234;
    CHECK(!ios_llsc_sim(op, ld_rt, is64, &st, &v) && v == 0x1234, "%s was not refused", what);
}

int main(void)
{
    memset(&st, 0, sizeof st);

    /* the crash: and w11, w11, w10 with w10 = ~(1 << 5), upper half of x11 ignored */
    st.__x[10] = 0xffffffff00000000ull | (uint32_t)~(1u << 5);
    expect(0x0a0a016b, 11, 0, 0xffffffff000000ffull, 0xdf, "and w11, w11, w10");

    expect(0x32000129, 9, 0, 0x10, 0x11, "orr w9, w9, #1");
    expect(0x927ff929, 9, 1, 0x8000000000000003ull, 0x8000000000000002ull, "and x9, x9, #~1");
    expect(0x72089d29, 9, 0, 0x12345678, 0x12005600, "ands w9, w9, #0xff00ff00");

    st.__x[10] = 0x3;
    expect(0x0a2a0d29, 9, 0, 0xff, 0xe7, "bic w9, w9, w10, lsl #3");
    st.__x[10] = 0xf0;
    expect(0xcaca1129, 9, 1, 0x1, 0x000000000000000full ^ 0x1, "eor x9, x9, x10, ror #4");
    st.__x[10] = 0x0f;
    expect(0x2a290149, 9, 0, 0xffff00ff, 0x0000ff0f, "orn w9, w10, w9");

    expect(0x11000529, 9, 0, 0xffffffff, 0x0, "add w9, w9, #1 (wraps at W)");
    expect(0xd1400529, 9, 1, 0x1000, 0x0, "sub x9, x9, #1, lsl #12");
    st.__x[10] = 0x4;
    expect(0x0b0a0929, 9, 0, 0x1, 0x11, "add w9, w9, w10, lsl #2");
    st.__x[10] = 0x100;
    expect(0xcb890549, 9, 1, 0xfffffffffffffff0ull, 0x108, "sub x9, x10, x9, asr #1");

    expect(0x528000e9, 9, 0, 0xdead, 0x7, "mov w9, #7");
    expect(0xf2b7dde9, 9, 1, 0x1111222233334444ull, 0x11112222beef4444ull, "movk x9, #0xbeef, lsl #16");
    expect(0x2a1f03e9, 9, 0, 0xdead, 0x0, "mov w9, wzr");

    refuse(0x1b0a2d29, 9, 0, "madd w9, w9, w10, w11");
    refuse(0x910043e9, 9, 1, "add x9, sp, #16");
    refuse(0x0a0a016b, 9, 0, "a step writing w11 when x9 was loaded");
    refuse(0x0a0a016b, 11, 1, "a W step under an X load");

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
    assert out.returncode == 0, 'ios_llsc_sim checks failed'

# the STLXR branch: replay only what ml1284 cannot undo, and never swap a stale value
branch = src[src.index('else if ((insn & 0x3fe07c00) == 0x08007c00)'):]
branch = branch[:branch.index('ml626: SWP')]
assert 'ios_llsc_sim( prev, ld_rt, size == 3, &state, &probe )' in branch, 'steps are not probed'
assert branch.index('delta += ') < branch.index('ios_llsc_sim( prev'), 'ADD/SUB undo must stay the first choice'
assert 'stale = (v & mask) != val;' in branch, 'the replay is not compared with the stored value'
assert 'if (!stale) switch (size)' in branch, 'a stale value is still swapped'
assert 'state.__x[rs] = ok ? 0 : 1;' in branch, 'Ws is no longer set from the swap'
print('check-llsc-replay: ok')
