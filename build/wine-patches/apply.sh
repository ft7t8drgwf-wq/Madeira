#!/bin/bash
# Applies this repository's patches to the wine submodule before a build.
# Each patch is applied once: one that is already in the tree is skipped, so
# every build script that compiles wine sources can call this.
# A patch belongs upstream in the wine repository; it lives here until then.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for p in "$R"/build/wine-patches/*.patch; do
    [ -e "$p" ] || continue
    if git -C "$R/wine" apply --reverse --check "$p" 2>/dev/null; then
        echo "== wine patch already applied: $(basename "$p") =="
    else
        git -C "$R/wine" apply "$p"
        echo "== wine patch applied: $(basename "$p") =="
    fi
done
