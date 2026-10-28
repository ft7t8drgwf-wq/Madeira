#!/bin/bash
# Applies this repository's patches to the FEX submodule before a build.
# Each patch is applied once: one that is already in the tree is skipped, so
# every build script that compiles FEX sources can call this.
# A patch belongs upstream in the FEX fork; it lives here until then.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for p in "$R"/build/fex-patches/*.patch; do
    [ -e "$p" ] || continue
    if git -C "$R/FEX" apply --reverse --check "$p" 2>/dev/null; then
        echo "== FEX patch already applied: $(basename "$p") =="
    else
        git -C "$R/FEX" apply "$p"
        echo "== FEX patch applied: $(basename "$p") =="
    fi
done
