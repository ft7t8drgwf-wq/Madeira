#!/bin/bash
# Applies this repository's patches to the madeira-dock submodule before a build.
# Each patch is applied once: one that is already in the tree is skipped, so
# every build script that compiles the Dock can call this.
# A patch belongs upstream in the madeira-dock repository; it lives here until then.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for p in "$R"/build/dock-patches/*.patch; do
    [ -e "$p" ] || continue
    if git -C "$R/madeira-dock" apply --reverse --check "$p" 2>/dev/null; then
        echo "== dock patch already applied: $(basename "$p") =="
    else
        git -C "$R/madeira-dock" apply "$p"
        echo "== dock patch applied: $(basename "$p") =="
    fi
done
