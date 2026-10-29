#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""A full-context resume keeps x16, x17 and x18 (build/ntdll-unix/signal_arm64_ios.c).

The syscall dispatcher's fast return leaves x16 = pc and x17 = sp. Every other
return took the SIGUSR2 slowpath, and on device x16 did not survive it: Project
Zomboid's Java main thread resumed in ucrtbase's memmove after FEX handled a
store into a protected code page, its loop counter came back as the pc, and the
792-byte copy ran 145KB through the code cache. The slowpath now traps with
`brk #0xf0c1` (frame in x0, a magic in x1) and the Mach exception thread writes
the frame into the thread with thread_set_state.

Compiles ios_full_context_return_brk verbatim against stand-ins for the Mach
calls, under AddressSanitizer and UBSan, and checks:
  * every general register, x16/x17/x18 included, fp, lr, sp and pc come from the frame;
  * only NZCV is taken from the frame's cpsr;
  * NEON state is written only when the frame asks for it;
  * any other brk, or a wrong magic, is not taken as a resume;
and that the dispatcher passes sp as the frame and trap_handler steps over the brk.
Synthetic register values only: no Wine, iOS or device.
"""
from pathlib import Path
import os, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / 'build/ntdll-unix/signal_arm64_ios.c').read_text().replace('\r\n', '\n')
CC = os.environ.get('CC') or shutil.which('cc') or 'cc'
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


def function(head):
    start = src.index(head)
    return src[start:src.index('\n}\n', start) + 3]


frame = src[src.index('struct syscall_frame\n{'):src.index('};', src.index('struct syscall_frame\n{')) + 2]
defines = ''.join(line + '\n' for line in src.split('\n')
                  if line.startswith('#define IOS_FULL_RETURN_'))
helper = function('static int ios_full_context_return_brk( thread_t thread )')
slowpath = function('void syscall_dispatcher_return_slowpath( struct syscall_frame *frame )')

require('"mov x0, sp\\n\\t"' in src[src.index('take slowpath if unequal'):src.index('take slowpath if unequal') + 300],
        'the dispatcher hands its frame (sp) to the slowpath')
require('brk #0xf0c1' in slowpath and 'raise( SIGUSR2 );' in slowpath
        and slowpath.index('brk #0xf0c1') < slowpath.index('raise( SIGUSR2 );'),
        'the slowpath traps to the exception thread before falling back to SIGUSR2')
require('ios_full_context_return_brk( thread )' in src and 'goto ios_exc_reply;' in src
        and 'ios_exc_reply: ;' in src, 'the exception thread takes the brk and replies')
trap = function('static void trap_handler( int signal, siginfo_t *siginfo, void *sigcontext )')
require('== IOS_FULL_RETURN_BRK' in trap, 'trap_handler steps over a brk the exception thread declined')

code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
typedef uint64_t ULONG64;
typedef uint32_t ULONG;
typedef struct { uint64_t Low; int64_t High; } NEON128;
typedef unsigned thread_t, mach_msg_type_number_t;
typedef int kern_return_t;
typedef void *thread_state_t;
typedef uintptr_t vm_address_t;
typedef size_t vm_size_t;
typedef struct { uint64_t __x[29], __fp, __lr, __sp, __pc; uint32_t __cpsr, __pad; } arm_thread_state64_t;
typedef struct { __uint128_t __v[32]; uint32_t __fpsr, __fpcr; } arm_neon_state64_t;
enum { KERN_SUCCESS = 0, ARM_THREAD_STATE64 = 6, ARM_NEON_STATE64 = 17,
       ARM_THREAD_STATE64_COUNT = sizeof(arm_thread_state64_t) / 4,
       ARM_NEON_STATE64_COUNT = sizeof(arm_neon_state64_t) / 4 };
#define arm_thread_state64_get_pc(s) ((s).__pc)
#define __darwin_arm_thread_state64_set_pc_fptr(s, p) ((s).__pc = (uint64_t)(uintptr_t)(p))
static unsigned mach_task_self(void) { return 1; }
static arm_thread_state64_t thr;
static arm_neon_state64_t neon;
static int thr_sets, neon_sets;
static kern_return_t thread_get_state(thread_t t, int f, thread_state_t s, mach_msg_type_number_t *n)
{
    (void)t;
    if (f == ARM_THREAD_STATE64) { memcpy(s, &thr, sizeof(thr)); *n = ARM_THREAD_STATE64_COUNT; }
    else { memcpy(s, &neon, sizeof(neon)); *n = ARM_NEON_STATE64_COUNT; }
    return KERN_SUCCESS;
}
static kern_return_t thread_set_state(thread_t t, int f, thread_state_t s, mach_msg_type_number_t n)
{
    (void)t; (void)n;
    if (f == ARM_THREAD_STATE64) { memcpy(&thr, s, sizeof(thr)); thr_sets++; }
    else { memcpy(&neon, s, sizeof(neon)); neon_sets++; }
    return KERN_SUCCESS;
}
static kern_return_t vm_read_overwrite(unsigned task, vm_address_t a, vm_size_t n, vm_address_t out, vm_size_t *got)
{
    (void)task;
    memcpy((void *)out, (const void *)a, n); *got = n;
    return KERN_SUCCESS;
}
''' + frame + '\n' + defines + helper + r'''
static uint32_t code_words[4] __attribute__((aligned(16)));

static void at_brk(struct syscall_frame *f, uint64_t magic)
{
    memset(&thr, 0, sizeof(thr));
    for (int i = 0; i < 29; i++) thr.__x[i] = 0xdead0000 + i;
    thr.__x[0] = (uint64_t)(uintptr_t)f;
    thr.__x[1] = magic;
    thr.__pc = (uint64_t)(uintptr_t)&code_words[1];
    thr.__cpsr = 0x60001000u;   /* Z and C set, plus a non-flag bit */
    thr_sets = neon_sets = 0;
}

int main(void)
{
    static struct syscall_frame f;
    memset(&neon, 0x11, sizeof(neon));
    for (int i = 0; i < 29; i++) f.x[i] = 0x1000 + i;
    f.x[16] = 0x3c;               /* memmove's loop counter */
    f.x[17] = 0x7041d91460;
    f.x[18] = 0x71ffe40000;       /* TEB */
    f.fp = 0x703a80c8f0; f.lr = 0x1520acd54; f.sp = 0x703a80c850; f.pc = 0x15207eb68;
    f.cpsr = 0x80000000u;         /* N */
    f.restore_flags = 0x400002;   /* CONTEXT_INTEGER only */
    f.fpcr = 0x1234; f.fpsr = 0x10;
    memset(f.v, 0x22, sizeof(f.v));

    code_words[1] = IOS_FULL_RETURN_BRK;
    at_brk(&f, IOS_FULL_RETURN_MAGIC);
    assert(ios_full_context_return_brk(1) == 1 && thr_sets == 1 && neon_sets == 0);
    for (int i = 0; i < 29; i++) assert(thr.__x[i] == f.x[i]);
    assert(thr.__x[16] == 0x3c && thr.__x[17] == 0x7041d91460 && thr.__x[18] == 0x71ffe40000);
    assert(thr.__fp == f.fp && thr.__lr == f.lr && thr.__sp == f.sp && thr.__pc == f.pc);
    assert(thr.__cpsr == 0x80001000u);
    assert(((unsigned char *)neon.__v)[0] == 0x11);
    puts("resume: every register from the frame, x16/x17/x18 included; NZCV only");

    f.restore_flags = 0x400006;   /* + CONTEXT_FLOATING_POINT */
    at_brk(&f, IOS_FULL_RETURN_MAGIC);
    assert(ios_full_context_return_brk(1) == 1 && neon_sets == 1);
    assert(((unsigned char *)neon.__v)[0] == 0x22 && ((unsigned char *)neon.__v)[511] == 0x22);
    assert(neon.__fpcr == 0x1234 && neon.__fpsr == 0x10);
    puts("resume: NEON, FPCR and FPSR when the frame carries them");

    code_words[1] = 0xd4395fc0;   /* FEX's brk #0xCAFE */
    at_brk(&f, IOS_FULL_RETURN_MAGIC);
    assert(ios_full_context_return_brk(1) == 0 && thr_sets == 0);
    puts("other brk: declined, state untouched");

    code_words[1] = IOS_FULL_RETURN_BRK;
    at_brk(&f, 0x1234);
    uint64_t pc = thr.__pc;
    assert(ios_full_context_return_brk(1) == 1 && thr.__pc == pc + 4 && thr.__x[16] == 0xdead0010);
    puts("wrong magic: stepped over, no frame restored");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='madeira-full-return-') as tmp:
    c, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
    c.write_text(code)
    built = subprocess.run([CC, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            str(c), '-o', str(exe)], capture_output=True, text=True)
    require(built.returncode == 0, 'the helper compiles verbatim' + ('' if built.returncode == 0 else '\n' + built.stderr))
    if built.returncode == 0:
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(run.stdout)
        require(run.returncode == 0, 'every case passed, no sanitizer report' + ('' if run.returncode == 0 else '\n' + run.stderr))

print('PASS' if not failures else f'FAIL ({failures})')
sys.exit(1 if failures else 0)
