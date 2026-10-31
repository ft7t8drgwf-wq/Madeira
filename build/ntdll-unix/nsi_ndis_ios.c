/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright 2026 125hz
 * Madeira Converter Exception: see LICENSE-EXCEPTION.md
 *
 * iOS-Madeira: Wine's BSD network-interface provider for the in-process NSI.
 *
 * Compiles wine/dlls/nsiproxy.sys/ndis.c unchanged (LGPL-2.1-or-later; its
 * authors' notice is in that file) for the iOS ntdll unix library; see
 * nsi_network_ios.c. The iPhoneOS SDK omits <net/if_arp.h>,
 * <netinet/if_ether.h>, <netinet/ip_var.h> and <netinet/icmp_var.h>, which
 * the macOS config.h announces, so those HAVE_* macros are dropped and
 * ndis.c takes its portable paths. if_nameindex, the interface ioctls and
 * the NET_RT_IFLIST sysctl it uses are all available; the routing-message
 * declarations come from shims/net/route.h. */
#include "config.h"
/* madeira-bcd: CI configures Wine against the iPhoneOS SDK, which has no
 * <net/route.h>, so its config.h leaves HAVE_NET_ROUTE_H undefined and the
 * routing declarations below were never included (RTM_IFINFO, RTA_IFP,
 * RTF_LLINFO undeclared, build 254). shims/net/route.h provides them. */
#ifndef HAVE_NET_ROUTE_H
#define HAVE_NET_ROUTE_H 1
#endif
#undef HAVE_NET_IF_ARP_H
#undef HAVE_NETINET_IF_ETHER_H
#undef HAVE_NETINET_IP_VAR_H
#undef HAVE_NETINET_ICMP_VAR_H

/* madeira-bcd: a MAC address of this device's own (MADEIRA_UNIQUE_MAC).
 *
 * iOS answers every request for an interface's hardware address with the
 * placeholder 02:00:00:00:00:00 (since iOS 7), so Wine's adapters carried that
 * one address on every iPhone, and a program that identifies the machine by it
 * saw one machine behind every Madeira user. Steam's machine id is the case in
 * point: it hashes the adapters' MAC addresses ("FF2"), next to the Windows
 * MachineGuid ("BB3", app/Madeira/WineProcessBridge.m gives each prefix its
 * own) and the disk serial ("3B3", .madeira-volume-serial in dlls/ntdll/unix/
 * file.c). Black Ops's CEG step (2026-10-30) is where this was found; it also
 * matters to any licence or save tied to the machine.
 *
 * ndis.c copies an interface's address with LLADDR(sdl). Here LLADDR returns,
 * for the placeholder or an all-zero 6-byte address, this prefix's own address
 * instead: random, locally administered and unicast (02:xx:xx:xx:xx:xx, never
 * the placeholder), generated once and kept in $WINEPREFIX/.madeira-mac-address
 * so it is the same across relaunches and app updates. A real address passes
 * through unchanged, so a Mac or a device that reports one is not touched.
 * env.MADEIRA_UNIQUE_MAC = 0 keeps the placeholder (the Steam machine identity
 * of earlier builds). Pure C below the include guard, host-tested by
 * tests/host/check-unique-mac.py. */
#include <net/if_dl.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <time.h>

extern const char *config_dir;   /* dlls/ntdll/unix/loader.c: the Wine prefix */

/* begin madeira_unique_mac (host test cut) */
static int ios_mac_is_placeholder( const unsigned char *a, unsigned int len )
{
    unsigned int i;
    if (len != 6) return 0;
    for (i = 1; i < 6; i++) if (a[i]) return 0;
    return a[0] == 0x02 || a[0] == 0x00;
}

/* Reads "02:ab:cd:ef:12:34" from path into mac; 1 when it holds a usable address. */
static int ios_mac_read_file( const char *path, unsigned char *mac )
{
    char buf[64];
    unsigned int v[6], i;
    int fd, len;

    if ((fd = open( path, O_RDONLY )) < 0) return 0;
    len = read( fd, buf, sizeof(buf) - 1 );
    close( fd );
    if (len <= 0) return 0;
    buf[len] = 0;
    if (sscanf( buf, "%2x:%2x:%2x:%2x:%2x:%2x", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5] ) != 6) return 0;
    for (i = 0; i < 6; i++) mac[i] = (unsigned char)v[i];
    return !ios_mac_is_placeholder( mac, 6 );
}

static void ios_mac_random( unsigned char *mac )
{
    int fd, got = 0;

    if ((fd = open( "/dev/urandom", O_RDONLY )) >= 0)
    {
        got = read( fd, mac, 6 ) == 6;
        close( fd );
    }
    if (!got)
    {
        unsigned int i, seed = (unsigned int)getpid() ^ (unsigned int)time( NULL );
        for (i = 0; i < 6; i++) { seed = seed * 1103515245u + 12345u; mac[i] = (unsigned char)(seed >> 16); }
    }
    mac[0] = (mac[0] & 0xfc) | 0x02;   /* locally administered, unicast */
    if (ios_mac_is_placeholder( mac, 6 )) mac[5] = 0x01;
}

/* This prefix's address, read from or created in <dir>/.madeira-mac-address.
 * Returns 1 when mac holds it. Another thread or process creating the file at
 * the same moment wins: its value is read back, so every caller agrees. */
static int ios_mac_for_prefix( const char *dir, unsigned char *mac )
{
    char path[1024], buf[32];
    int fd, len;

    if (!dir || snprintf( path, sizeof(path), "%s/.madeira-mac-address", dir ) >= (int)sizeof(path)) return 0;
    if (ios_mac_read_file( path, mac )) return 1;
    ios_mac_random( mac );
    len = snprintf( buf, sizeof(buf), "%02x:%02x:%02x:%02x:%02x:%02x\n", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5] );
    if ((fd = open( path, O_WRONLY | O_CREAT | O_EXCL, 0600 )) < 0 && errno == EEXIST)
    {
        unsigned char other[6];
        if (ios_mac_read_file( path, other )) { memcpy( mac, other, 6 ); return 1; }   /* a racing creator's value */
        unlink( path );                                   /* the file holds the placeholder or junk: replace it */
        fd = open( path, O_WRONLY | O_CREAT | O_EXCL, 0600 );
    }
    if (fd >= 0)
    {
        if (write( fd, buf, len ) != len) unlink( path );   /* this run keeps its value; the next run makes a new one */
        close( fd );
    }
    return 1;   /* an unwritable prefix still gets an address of its own for this run */
}
/* end madeira_unique_mac (host test cut) */

/* The address ndis.c copies: the interface's own unless iOS gave the placeholder. */
static const unsigned char *ios_lladdr( const struct sockaddr_dl *sdl )
{
    static unsigned char mac[6];
    static int state;   /* 0 unknown, 1 mac holds the prefix's address, -1 off or unavailable */
    const unsigned char *real = (const unsigned char *)sdl->sdl_data + sdl->sdl_nlen;

    if (!ios_mac_is_placeholder( real, sdl->sdl_alen )) return real;
    if (!state)
    {
        const char *e = getenv( "MADEIRA_UNIQUE_MAC" );   /* 0: adapters keep iOS's 02:00:00:00:00:00 */
        const char *dir = config_dir ? config_dir : getenv( "WINEPREFIX" );
        unsigned char m[6];
        int ok = !(e && e[0] == '0') && ios_mac_for_prefix( dir, m );
        if (ok) memcpy( mac, m, 6 );
        __atomic_thread_fence( __ATOMIC_RELEASE );
        state = ok ? 1 : -1;
        dprintf( 2, "[unique-mac] madeira-bcd iOS reports the placeholder MAC for %.*s: %s "
                    "(env.MADEIRA_UNIQUE_MAC=0 keeps the placeholder)\n", (int)sdl->sdl_nlen, sdl->sdl_data,
                 ok ? "using this prefix's own address (.madeira-mac-address)" : "kept" );
    }
    return state > 0 ? mac : real;
}
#undef LLADDR
#define LLADDR(s) ios_lladdr( (const struct sockaddr_dl *)(s) )

#include "../../wine/dlls/nsiproxy.sys/ndis.c"
