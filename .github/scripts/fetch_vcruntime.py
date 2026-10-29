#!/usr/bin/env python3
"""Extract the twelve x64 VC++ runtime DLLs (tools/fetch-vcruntime.md) from VC_redist.x64.exe.

The redistributable is a WiX Burn bundle. 7-Zip only opens its UX container (theme, licence
text, engine); the MSIs and their cabinets sit in an attached container appended to the exe as
a plain cabinet. So every MSCF cabinet in a PE is carved out by the size in its header, and each
layer is unpacked in turn. The MSI cabinets name their members by MSI file key
(e.g. F_CENTRAL_msvcp140_x64), not by DLL name, so each x64 PE is identified by the
OriginalFilename in its version resource.

usage: fetch_vcruntime.py VC_redist.x64.exe DEST_DIR
Exits non-zero unless all twelve DLLs were found. Files are copied byte for byte.
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

WANT = {n + ".dll" for n in (
    "concrt140 msvcp140 msvcp140_1 msvcp140_2 msvcp140_atomic_wait msvcp140_codecvt_ids "
    "vcamp140 vccorlib140 vcomp140 vcruntime140 vcruntime140_1 vcruntime140_threads").split()}
KEY = "OriginalFilename".encode("utf-16-le")


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def carve_cabinets(path, out):
    """Write every well-formed MSCF cabinet embedded in the file at path to out/cabN.cab."""
    with open(path, "rb") as fh:
        data = fh.read()
    n = 0
    i = data.find(b"MSCF\0\0\0\0", 1)
    while i >= 0:
        size = struct.unpack_from("<I", data, i + 8)[0] if i + 36 <= len(data) else 0
        # CFHEADER: cbCabinet at +8, coffFiles at +16, versionMinor/Major 3/1 at +24
        ok = (36 <= size <= len(data) - i and data[i + 24:i + 26] == b"\x03\x01"
              and struct.unpack_from("<I", data, i + 16)[0] < size)
        if ok:
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, f"cab{n}.cab"), "wb") as fh:
                fh.write(data[i:i + size])
            n += 1
        i = data.find(b"MSCF\0\0\0\0", i + (size if ok else 4))
    return n


def unpack(path, out):
    """Unpack one layer. Returns True if anything was extracted. Exit codes are not trusted:
    7-Zip reports warnings (trailing data, unsupported MSI tables) with a non-zero status."""
    try:
        with open(path, "rb") as fh:
            magic = fh.read(8)
    except OSError:
        return False
    os.makedirs(out, exist_ok=True)
    if magic[:4] == b"MSCF":                     # cabinet (Burn container or MSI media)
        run(["cabextract", "-q", "-d", out, path])
    elif magic == bytes.fromhex("d0cf11e0a1b11ae1"):  # MSI (OLE compound file)
        run(["msiextract", "-C", out, path])
    elif magic[:2] == b"MZ":                     # Burn bundle: attached container is a cabinet
        carve_cabinets(path, out)
    if not os.listdir(out):
        run(["7zz", "x", "-y", path, "-o" + out])
    if not os.listdir(out):
        os.rmdir(out)
        return False
    return True


def original_filename(data):
    """OriginalFilename of an x64 PE image, lower-cased, or None."""
    if data[:2] != b"MZ" or len(data) < 0x40:
        return None
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0" or struct.unpack_from("<H", data, pe + 4)[0] != 0x8664:
        return None
    i = data.find(KEY)
    if i < 0:
        return None
    m = re.match(rb"(?:\x00\x00)*((?:[^\x00]\x00)+)", data[i + len(KEY):])
    return m.group(1).decode("utf-16-le").strip().lower() if m else None


def main(exe, dest):
    work = tempfile.mkdtemp(prefix="vcredist-")
    pending = [(exe, os.path.join(work, "0"))]
    for _ in range(4):  # bundle -> attached cab -> MSI/payload cab -> files
        nxt = []
        for src, out in pending:
            if not unpack(src, out):
                continue
            for root, _, files in os.walk(out):
                for f in files:
                    p = os.path.join(root, f)
                    nxt.append((p, p + ".x"))
        pending = nxt

    found = {}
    for root, _, files in os.walk(work):
        for f in files:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    name = original_filename(fh.read())
            except OSError:
                continue
            if name in WANT and name not in found:
                found[name] = p

    os.makedirs(dest, exist_ok=True)
    for name, p in sorted(found.items()):
        shutil.copyfile(p, os.path.join(dest, name))
        print(f"  {name} <- {os.path.relpath(p, work)}")
    missing = sorted(WANT - found.keys())
    print(f"VC++ runtime DLLs bundled: {len(found)} of {len(WANT)}")
    if missing:
        print("missing: " + " ".join(missing))
        for root, _, files in os.walk(work):
            for f in files[:40]:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    magic = fh.read(8).hex()
                print(f"    {os.path.relpath(p, work)}  {os.path.getsize(p)}  {magic}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
