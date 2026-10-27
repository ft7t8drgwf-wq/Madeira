#!/bin/bash
# Applies this repository's patches to the dxmt submodule before a build.
# Each patch is applied once: one that is already in the tree is skipped, so
# both DXMT builds (build/wine-i386 and build/dxmt-ios) can call this.
# A patch belongs upstream in the dxmt repository; it lives here until then.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for p in "$R"/build/dxmt-patches/*.patch; do
    [ -e "$p" ] || continue
    if git -C "$R/dxmt" apply --reverse --check "$p" 2>/dev/null; then
        echo "== dxmt patch already applied: $(basename "$p") =="
    else
        git -C "$R/dxmt" apply "$p"
        echo "== dxmt patch applied: $(basename "$p") =="
    fi
done
