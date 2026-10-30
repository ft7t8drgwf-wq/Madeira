#!/bin/bash
# Configure and build the FEXCore static libraries the app links
# (FEX/build-ios/FEXCore/Source/*.a and External/*). Options mirror the
# development build's CMakeCache.
set -eu
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
B="$R/FEX/build-ios"
# The CPUID switch MADEIRA_FEX_AVX=2 (build/fex-patches/0007, from 125hz's vulkan-stack-1028): the
# app's FEXCore copy and the hand-built xtajit64.dll/xtajit.dll read the variable the same way.
# Idempotent like build/wine-patches/apply.sh: a patch already in the tree is skipped. The other
# fex-patches are for the Windows modules only (build/fex-patches/README.md).
for p in "$R"/build/fex-patches/0007-*.patch; do
    [ -e "$p" ] || continue
    if git -C "$R/FEX" apply --reverse --check "$p" 2>/dev/null; then
        echo "== fex patch already applied: $(basename "$p") =="
    else
        git -C "$R/FEX" apply "$p"
        echo "== fex patch applied: $(basename "$p") =="
    fi
done
cmake -S "$R/FEX" -B "$B" -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_SYSTEM_PROCESSOR=arm64 -DCMAKE_OSX_ARCHITECTURES=arm64 \
    -DCMAKE_OSX_SYSROOT=iphoneos -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0 -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_DISABLE_FIND_PACKAGE_fmt=ON -DCMAKE_DISABLE_FIND_PACKAGE_range-v3=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_unordered_dense=ON \
    -DBUILD_TESTING=OFF -DBUILD_THUNKS=OFF -DBUILD_FEXCONFIG=OFF -DBUILD_FEX_LINUX_TESTS=OFF \
    -DENABLE_FEX_ALLOCATOR=OFF -DENABLE_ASSERTIONS=OFF -DENABLE_CLANG_THUNKS=ON -DENABLE_CCACHE=ON \
    -DTUNE_CPU=cortex-a78
cmake --build "$B" --target FEXCore FEXCore_Base JemallocLibs fmt cephes_128bit softfloat_3e xxhash
ls "$B/FEXCore/Source/"*.a
