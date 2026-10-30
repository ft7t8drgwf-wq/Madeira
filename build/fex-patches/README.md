# FEX patches

Patches on the FEX submodule that the hand-built Windows modules carry
(app/Madeira/arm64ec-windows/xtajit64.dll and app/Madeira/aarch64-windows/xtajit.dll
ship as committed; build-ios.yml does not rebuild them). Nothing in the workflow
applies them except build/fex-ios/build.sh, which applies 0007 to the app's own
FEXCore copy. Rebuild recipe: build/fex-arm64ec/build.sh and build/fex-wow64/build.sh
on a tree with the set below applied (`git apply`), llvm-mingw 20260421.

| patch | xtajit64.dll (ARM64EC, FEX pin 18d891e) | xtajit.dll (WOW64, FEX 35e8f36 + 18d891e's x87 fix) |
|---|---|---|
| 0001 fexcore-log-cpu-probes | in the pin | applied |
| 0002 fexcore-ios-wow64-cpu-name-and-no-hypervisor | in the pin | applied |
| 0003 wow64-ios-smc-traps-per-16k-host-page | - (WOW64 only) | applied; needs 35e8f36, so the WOW64 module stays on that base |
| 0004 fexcore-ios-mono-backpatch-miss-without-lock | applied | applied |
| 0005 arm64ec-ios-smc-traps-per-16k-host-page | applied | - (ARM64EC only) |
| 0006 wow64-ios-hot-smc-pages (125hz 9d2c04e) | - (WOW64 only) | NOT applied: needs InvalidationTracker::EnableHotSMCPages (FEX 68bb21c), newer than 35e8f36 |
| 0007 cpuid-madeira-fex-avx-2 (125hz 82750c0) | applied | applied |

External/rpmalloc for both modules: willfaust/rpmalloc f7f3e0b (125hz f23fca2 + 693cbc5:
4 MB spans, a sleeping waiter on the allocator lock); the pin's own submodule points at 812c2b9.
The app-side FEXCore (build/fex-ios) does not build rpmalloc (Apple platforms disable it).
