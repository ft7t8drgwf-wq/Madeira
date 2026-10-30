# Unix-only wine patches

Patches here change only `dlls/ntdll/unix/*.c` of the wine submodule, the files
`build/ntdll-unix/build.sh` compiles into the app's `libntdll_unix.a`. Nothing
else compiles them: the 32-bit (i386) Windows DLL farm and the PE modules never
see the unix side.

They are kept apart from `build/wine-patches` for one reason: the i386 farm's CI
cache key hashes `build/wine-patches/**` (`.github/workflows/build-ios.yml`, job
`i386-key`), so a patch there costs an hours-long farm rebuild on a macOS runner,
even when it cannot change a single farm DLL. A unix-only fix in this folder
leaves that key, and the cached farm, alone.

`apply.sh` applies them after `build/wine-patches/apply.sh` (it is called from
`build/ntdll-unix/build.sh`), skips a patch already in the tree, and refuses a
patch that touches anything outside `dlls/ntdll/unix/` (that one belongs in
`build/wine-patches`). The patches are plain `git diff` output against the tree
with `build/wine-patches` applied.

| Patch | What it does |
| --- | --- |
| 0001-ntdll-pipe-trace-any-pipe-both-directions | `[pipe-trace]` (`MADEIRA_PIPE_TRACE=1`) takes the pipe name to follow from `MADEIRA_PIPE_TRACE_MATCH` (default `rgsc_`), traces reads too with `MADEIRA_PIPE_TRACE_READS=1` and shows up to 65536 bytes a line (`MADEIRA_PIPE_TRACE_BYTES`). Written to capture what Steam's client service hands the Steam client during Black Ops's CEG step (anonymous pipes `Win32.Pipes.<pid>.<n>`). Host test: `tests/host/check-pipe-trace.py`. |
