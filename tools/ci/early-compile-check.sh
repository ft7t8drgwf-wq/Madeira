#!/bin/bash
# The app's plain C and Objective-C files checked against the iOS SDK, in
# seconds, so a compile error stops a build before the long native steps
# instead of at "Build app". A file that needs a header later steps generate
# ("file not found") is skipped here and compiled by the app build as usual.
# Needs Xcode (macOS). Used by build-ios.yml and app-compile-check.yml.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
bad=0; skipped=0; checked=0
while IFS= read -r f; do
    case "$f" in *.m) lang=(-x objective-c -fobjc-arc) ;; *) lang=(-x c) ;; esac
    if ! out="$(xcrun --sdk iphoneos clang -fsyntax-only "${lang[@]}" -target arm64-apple-ios17.0 \
            -isysroot "$SDK" -I app/Madeira -I app/Madeira/Winios -DDEBUG=1 \
            -Werror=implicit-function-declaration "$f" 2>&1)"; then
        if grep -q "file not found" <<< "$out"; then
            echo "skipped (generated header): $f"; skipped=$((skipped + 1)); continue
        fi
        echo "::error file=$f::does not compile for iOS"
        grep -E "error:" <<< "$out" | head -20
        bad=$((bad + 1))
    fi
    checked=$((checked + 1))
done < <(find app/Madeira \( -name '*.c' -o -name '*.m' \) -not -path '*/Packages/*' | sort)
echo "checked $checked, skipped $skipped, failed $bad"
[ "$bad" -eq 0 ]
