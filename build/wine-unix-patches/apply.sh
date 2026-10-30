#!/bin/bash
# Applies this repository's unix-side wine patches to the wine submodule.
#
# A patch here changes only dlls/ntdll/unix/*.c, which build/ntdll-unix/build.sh
# compiles into the app's libntdll_unix.a. Nothing else compiles those files: the
# 32-bit (i386) Windows DLL farm and the PE modules never see them. Keeping such
# patches apart from build/wine-patches keeps the farm's CI cache key (which
# hashes build/wine-patches/**) unchanged, so a unix-only fix does not cost the
# hours-long i386 farm rebuild (.github/workflows/build-ios.yml, job i386-key).
#
# They apply on top of build/wine-patches (run that apply.sh first) and follow
# the same once-only rule: a patch already in the tree is skipped. A patch that
# touches anything outside dlls/ntdll/unix/ belongs in build/wine-patches.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for p in "$R"/build/wine-unix-patches/*.patch; do
    [ -e "$p" ] || continue
    if grep -E '^(\+\+\+|---) [ab]/' "$p" | grep -v -E '^(\+\+\+|---) [ab]/dlls/ntdll/unix/' >/dev/null; then
        echo "== wine unix patch touches files outside dlls/ntdll/unix, move it to build/wine-patches: $(basename "$p") ==" >&2
        exit 1
    fi
    if git -C "$R/wine" apply --reverse --check "$p" 2>/dev/null; then
        echo "== wine unix patch already applied: $(basename "$p") =="
    else
        git -C "$R/wine" apply "$p"
        echo "== wine unix patch applied: $(basename "$p") =="
    fi
done
