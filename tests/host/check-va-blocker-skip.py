#!/usr/bin/env python3
"""[va-blocker] placement past kernel regions of maximum protection none (virtual_ios.c); no Wine runs.

Compiles the production ios_va_find_blocker, ios_va_limits_past_blocker and ios_va_blocker_skip
against a simulated 32-bit window: Wine's free-range table knows only its own views, while the
stubbed kernel also holds "0/0" regions that refuse any MAP_FIXED over them with ENOMEM. Checks
that a refused request is placed past the blockers bottom-up and top-down (a small DLL behind a
row of leftovers, a 369 MB request with a 256 KB region inside it), that adjacent blockers count
as one, that alignment holds, that an unexplained refusal and a full window still fail, and that
the walk stops after IOS_VA_BLOCKER_STEPS moves.
"""
from pathlib import Path
import os, subprocess, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / "build/ntdll-unix/virtual_ios.c").read_text()
a = src.index("va-blocker-test:begin")
a = src.index("*/", a) + 2
b = src.index("#endif /* WINE_IOS */", a)
code = src[a:b]

harness = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
typedef uintptr_t ULONG_PTR;
typedef int kern_return_t; typedef unsigned int mach_msg_type_number_t; typedef int task_t;
typedef uint64_t mach_vm_address_t, mach_vm_size_t; typedef int mach_port_t; typedef int *vm_region_info_t;
typedef struct { int protection, max_protection; } vm_region_basic_info_data_64_t;
#define KERN_SUCCESS 0
#define VM_REGION_BASIC_INFO_64 9
#define VM_REGION_BASIC_INFO_COUNT_64 1
#define MACH_PORT_NULL 0
#define MAP_FAILED ((void *)-1)
#define dprintf(fd, ...) fprintf( stderr, __VA_ARGS__ )

/* the window and what is in it */
#define W  0x400000000ULL
#define G4 0x100000000ULL
#define MAXR 256
static ULONG_PTR blk_lo[MAXR], blk_hi[MAXR]; static int nblk;      /* kernel 0/0 regions, sorted */
static ULONG_PTR view_lo[MAXR], view_hi[MAXR]; static int nview;   /* Wine's views */
static int mmap_calls, query_calls, fail_other;

static void add_blk( ULONG_PTR lo, ULONG_PTR hi ) { blk_lo[nblk] = lo; blk_hi[nblk] = hi; nblk++; }
static void add_view( ULONG_PTR lo, ULONG_PTR hi ) { view_lo[nview] = lo; view_hi[nview] = hi; nview++; }
static int overlaps( ULONG_PTR lo, ULONG_PTR hi, const ULONG_PTR *l, const ULONG_PTR *h, int n )
{
    int i;
    for (i = 0; i < n; i++) if (lo < h[i] && l[i] < hi) return 1;
    return 0;
}

/* the kernel: a blocker, or our PROT_NONE reservation (max rwx) up to the next blocker */
static task_t mach_task_self( void ) { return 1; }
static kern_return_t mach_vm_region( task_t t, mach_vm_address_t *addr, mach_vm_size_t *size, int f,
                                     vm_region_info_t info, mach_msg_type_number_t *c, mach_port_t *o )
{
    vm_region_basic_info_data_64_t *bi = (vm_region_basic_info_data_64_t *)info;
    ULONG_PTR x = *addr, next = W + G4;
    int i;
    (void)t; (void)f; (void)c; (void)o;
    query_calls++;
    if (x >= W + G4) return 1;
    for (i = 0; i < nblk; i++)
    {
        if (x >= blk_lo[i] && x < blk_hi[i])
        { *addr = blk_lo[i]; *size = blk_hi[i] - blk_lo[i]; bi->protection = bi->max_protection = 0; return 0; }
        if (blk_lo[i] > x && blk_lo[i] < next) next = blk_lo[i];
    }
    *addr = x; *size = next - x; bi->protection = 0; bi->max_protection = 7; return 0;
}

static void *anon_mmap_fixed( void *start, size_t size, int prot, int flags )
{
    ULONG_PTR lo = (ULONG_PTR)start;
    (void)prot; (void)flags;
    mmap_calls++;
    if (fail_other) { errno = EINVAL; return MAP_FAILED; }
    if (overlaps( lo, lo + size, blk_lo, blk_hi, nblk )) { errno = ENOMEM; return MAP_FAILED; }
    add_view( lo, lo + size );
    return start;
}

/* Wine's search: the first (last) aligned fit in [low, high) clear of its own views only */
static void *find_reserved_area_range( void *limit_low, void *limit_high, size_t size, int top_down, size_t align_mask )
{
    ULONG_PTR low = (ULONG_PTR)limit_low, high = (ULONG_PTR)limit_high, s;
    ULONG_PTR step = align_mask + 1;
    if (low < W) low = W;
    if (high > W + G4) high = W + G4;
    if (high <= low || high - low < size) return NULL;
    if (!top_down)
    {
        for (s = (low + align_mask) & ~(ULONG_PTR)align_mask; s + size <= high; s += step)
            if (!overlaps( s, s + size, view_lo, view_hi, nview )) return (void *)s;
    }
    else
    {
        for (s = (high - size) & ~(ULONG_PTR)align_mask; s >= low; s -= step)
        {
            if (!overlaps( s, s + size, view_lo, view_hi, nview )) return (void *)s;
            if (s < step) break;
        }
    }
    return NULL;
}
""" + code + r"""

/* the placement request map_reserved_area_find scans with (the production struct's first four fields) */
struct ios_reserved_ctx { size_t size; int top_down; int unix_prot; size_t align_mask; };
static void *map_reserved_area_find( void *limit_low, void *limit_high, struct ios_reserved_ctx *ctx )
{
    return find_reserved_area_range( limit_low, limit_high, ctx->size, ctx->top_down, ctx->align_mask );
}
static struct ios_reserved_ctx ctx16 = { 0x10000, 0, 3, 0xffff };

/* what map_reserved_area_inner does: one search, one MAP_FIXED, the skip after an ENOMEM */
static void *place( size_t size, int top_down, size_t align_mask )
{
    struct ios_reserved_ctx ctx = { size, top_down, 3, align_mask };
    void *ptr = find_reserved_area_range( (void *)W, (void *)(W + G4), size, top_down, align_mask );
    if (ptr && anon_mmap_fixed( ptr, size, 3, 0 ) != ptr)
    {
        if (errno == ENOMEM) return ios_va_blocker_skip( ptr, (void *)W, (void *)(W + G4), size, top_down, 3, align_mask, &ctx );
        ptr = NULL;
    }
    return ptr;
}

static void reset( void ) { nblk = nview = mmap_calls = query_calls = fail_other = 0; }

int main( int argc, char **argv )
{
    const char *t = argv[1];
    ULONG_PTR lo, hi;
    void *p;
    int i;

    reset();
    if (!strcmp( t, "scan" ))
    {
        /* the run may start below the range, adjacent 0/0 regions are one, a gap ends it */
        add_blk( W + 0x10000, W + 0x20000 ); add_blk( W + 0x20000, W + 0x34000 ); add_blk( W + 0x40000, W + 0x44000 );
        i = ios_va_find_blocker( W + 0x18000, 0x4000, ios_va_region_query, &lo, &hi );
        printf( "%d %llx %llx\n", i, (unsigned long long)(lo - W), (unsigned long long)(hi - W) );
        i = ios_va_find_blocker( W + 0x34000, 0xc000, ios_va_region_query, &lo, &hi );   /* ends where one begins */
        printf( "%d\n", i );
        i = ios_va_find_blocker( W + 0x34000, 0xc001, ios_va_region_query, &lo, &hi );
        printf( "%d %llx %llx\n", i, (unsigned long long)(lo - W), (unsigned long long)(hi - W) );
        return 0;
    }
    if (!strcmp( t, "bottom-up" ))
    {
        /* a DLL's leftover at the bottom of the window: the next fit after it */
        add_blk( W, W + 0x90000 );
        p = place( 0x11000 + 0x3000, 0, 0xffff );   /* 0x14000 bytes, 64 KB aligned */
    }
    else if (!strcmp( t, "top-down" ))
    {
        add_blk( W + G4 - 0x2b0000, W + G4 - 0x4000 );
        p = place( 0x200000, 1, 0xffff );
    }
    else if (!strcmp( t, "row" ))
    {
        /* Hotline Miami 2: 13 freed d3dcompiler/wined3d pairs, 2.7 MB each, small gaps between */
        for (i = 0; i < 13; i++) add_blk( W + 0x10000000 + i * 0x2c0000, W + 0x10000000 + i * 0x2c0000 + 0x2b0000 );
        add_view( W, W + 0x10000000 );
        p = place( 0x2b0000, 0, 0xffff );
    }
    else if (!strcmp( t, "inside" ))
    {
        /* Metro: a 256 KB region inside a 369 MB request */
        add_view( W, W + 0x20000000 );
        add_blk( W + 0x28000000, W + 0x28040000 );
        p = place( 0x17100000, 0, 0xffff );
    }
    else if (!strcmp( t, "adjacent" ))
    {
        add_blk( W, W + 0x10000 ); add_blk( W + 0x10000, W + 0x24000 );
        p = place( 0x10000, 0, 0xffff );
    }
    else if (!strcmp( t, "unexplained" ))
    {
        /* ENOMEM with no blocker in the range (simulated by a blocker the stubbed kernel hides): no step, NULL */
        add_blk( W, W + 0x10000 );
        {
            void *ptr = find_reserved_area_range( (void *)W, (void *)(W + G4), 0x10000, 0, 0xffff );
            nblk = 0;   /* the kernel shows nothing there */
            errno = ENOMEM;
            p = ios_va_blocker_skip( ptr, (void *)W, (void *)(W + G4), 0x10000, 0, 3, 0xffff, &ctx16 );
        }
    }
    else if (!strcmp( t, "full" ))
    {
        add_view( W, W + G4 - 0x100000 );
        add_blk( W + G4 - 0x100000, W + G4 - 0x80000 );
        p = place( 0x90000, 0, 0xffff );
    }
    else if (!strcmp( t, "other-error" ))
    {
        add_blk( W, W + 0x10000 );
        {
            void *ptr = find_reserved_area_range( (void *)W, (void *)(W + G4), 0x10000, 0, 0xffff );
            fail_other = 1;
            p = ios_va_blocker_skip( ptr, (void *)W, (void *)(W + G4), 0x10000, 0, 3, 0xffff, &ctx16 );
        }
    }
    else if (!strcmp( t, "cap" ))
    {
        /* more blockers than the walk may pass, each gap too small */
        for (i = 0; i < 100; i++) add_blk( W + i * 0x20000, W + i * 0x20000 + 0x14000 );
        p = place( 0x10000, 0, 0xffff );
    }
    else return 2;
    printf( "%llx %d\n", p ? (unsigned long long)((ULONG_PTR)p - W) : 0xffffffffffffffffULL, mmap_calls );
    if (p && overlaps( (ULONG_PTR)p, (ULONG_PTR)p + 1, blk_lo, blk_hi, nblk )) printf( "PLACED ON A BLOCKER\n" );
    return 0;
}
"""

with tempfile.TemporaryDirectory() as d:
    c = os.path.join( d, "t.c" ); exe = os.path.join( d, "t" )
    Path( c ).write_text( harness )
    subprocess.run( ["cc", "-std=gnu11", "-Wall", "-Werror", "-Wno-unused-function", "-o", exe, c], check=True )

    def run( name ):
        r = subprocess.run( [exe, name], capture_output=True, text=True, check=True )
        return r.stdout.split( "\n" )[0] if name != "scan" else r.stdout, r.stdout, r.stderr

    failures = []
    def expect( name, want ):
        got, full, err = run( name )
        if got.strip() != want or "PLACED ON A BLOCKER" in full:
            failures.append( f"{name}: got {full.strip()!r}, want {want!r}\n{err}" )

    expect( "scan", "1 10000 34000\n0\n1 40000 44000" )
    expect( "bottom-up", "90000 2" )                 # refused at 0, placed at the blocker's end
    expect( "top-down", f"{(0x100000000 - 0x2b0000 - 0x200000) & ~0xffff:x} 2" )   # placed below the blocker
    expect( "row", f"{0x10000000 + 13 * 0x2c0000 - 0x10000:x} 14" )  # 13 refusals (one per leftover), then placed
    expect( "inside", f"{0x28040000:x} 2" )
    expect( "adjacent", "30000 2" )                  # both regions skipped at once, 64 KB aligned
    expect( "unexplained", "ffffffffffffffff 0" )
    expect( "full", "ffffffffffffffff 1" )
    expect( "other-error", "ffffffffffffffff 1" )
    expect( "cap", "ffffffffffffffff 65" )           # the first try plus 64 steps, then stop

    if failures:
        print( "FAIL\n" + "\n".join( failures ) )
        raise SystemExit( 1 )
    print( "ok: va-blocker skip (scan, bottom-up, top-down, a row of leftovers, a blocker inside a big request, "
           "adjacent regions, alignment, unexplained refusal, full window, other errors, step cap)" )
