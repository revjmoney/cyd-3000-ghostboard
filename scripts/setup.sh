#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
#
# CYD-3000 GHOSTBOARD setup: from nothing to an emulated Cheap Yellow Display on a Linux x86_64 desktop.
#   1. downloads PICSimLab 0.9.3 (official release, sha256 checked) and unpacks it (no FUSE needed)
#   2. fetches lcgamboa's ESP32 QEMU at the pinned commit and applies GHOSTBOARD's patches
#   3. builds libqemu-xtensa.so (about 8 minutes on an i5-2400) and puts it into PICSimLab
#   4. fixes PICSimLab's mirrored ILI9341 (one checked byte)
# Every step is skipped when its result is already there, so running it again is safe.
#
# usage: scripts/setup.sh [--prefix DIR]      (default ~/.ghostboard; the run scripts use the same default)
set -euo pipefail

PREFIX="${GHOSTBOARD_HOME:-$HOME/.ghostboard}"
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        -h|--help) sed -n '4,12p' "$0"; exit 0 ;;
        *) echo "unknown option $1"; exit 1 ;;
    esac
done
REPO="$(cd "$(dirname "$0")/.." && pwd)"

APPIMAGE_URL="https://github.com/lcgamboa/picsimlab/releases/download/v0.9.3/PICSimLab-0.9.3_260920_Ubuntu_22.04.5_LTS_x86_64.AppImage"
APPIMAGE_SHA="fe403bb783fd46cb9d172d5895649b83dd2d2a9e0cd1b6542eb5ebc0ed17b467"
QEMU_URL="https://github.com/lcgamboa/qemu"
QEMU_BRANCH="picsimlab-esp32"
QEMU_COMMIT="5bd15ce0b339b57e5b3943f021a8424bac876381"

say() { printf '\n== %s\n' "$*"; }
mkdir -p "$PREFIX/src"

say "checking tools"
missing=()
for t in git gcc make ninja python3 perl flex bison pkg-config curl sha256sum; do
    command -v "$t" >/dev/null || missing+=("$t")
done
for m in glib-2.0 pixman-1 slirp libgcrypt; do
    pkg-config --exists "$m" 2>/dev/null || missing+=("$m (dev headers)")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "missing: ${missing[*]}"
    echo "on Ubuntu/Debian:  sudo apt install git build-essential ninja-build python3 python3-venv perl flex bison" \
         "pkg-config curl libglib2.0-dev libpixman-1-dev libslirp-dev libgcrypt20-dev"
    exit 1
fi
echo "all there"

say "PICSimLab 0.9.3"
AI="$PREFIX/PICSimLab-0.9.3.AppImage"
if [ -x "$PREFIX/picsimlab/AppRun" ]; then
    echo "already unpacked in $PREFIX/picsimlab"
else
    if [ ! -f "$AI" ] || [ "$(sha256sum "$AI" | cut -d' ' -f1)" != "$APPIMAGE_SHA" ]; then
        curl -fL --progress-bar -o "$AI.part" "$APPIMAGE_URL"
        mv "$AI.part" "$AI"
    fi
    got="$(sha256sum "$AI" | cut -d' ' -f1)"
    [ "$got" = "$APPIMAGE_SHA" ] || { echo "download does not match the 0.9.3 release (sha256 $got)"; exit 1; }
    chmod +x "$AI"
    rm -rf "$PREFIX/squashfs-root"
    (cd "$PREFIX" && "$AI" --appimage-extract >/dev/null)
    mv "$PREFIX/squashfs-root" "$PREFIX/picsimlab"
    echo "unpacked into $PREFIX/picsimlab"
fi

say "ESP32 QEMU (lcgamboa/qemu $QEMU_BRANCH @ ${QEMU_COMMIT:0:7}) + GHOSTBOARD patches"
Q="$PREFIX/src/qemu"
if [ ! -d "$Q/.git" ]; then
    git clone --branch "$QEMU_BRANCH" "$QEMU_URL" "$Q"
fi
(
    cd "$Q"
    if [ "$(git rev-parse HEAD)" != "$QEMU_COMMIT" ]; then
        [ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "$Q has local changes; not touching it"; exit 1; }
        git fetch -q origin "$QEMU_BRANCH" && git checkout -q "$QEMU_COMMIT"
    fi
    for p in "$REPO"/patches/qemu/*.patch; do
        if git apply --reverse --check "$p" 2>/dev/null; then
            echo "already applied: $(basename "$p")"
        elif git apply --check "$p"; then
            git apply "$p" && echo "applied: $(basename "$p")"
        else
            echo "does not apply: $(basename "$p")"; exit 1
        fi
    done
)

say "building libqemu-xtensa.so"
LIB="$Q/build/libqemu-xtensa.so"
STAMP="$Q/build/.ghostboard-patches"
BUILD_FLAGS="no-debug,file-prefix-map"   # (part of the stamp: changing how it builds rebuilds it)
want="$( { cat "$REPO"/patches/qemu/*.patch; echo "$BUILD_FLAGS"; } | sha256sum | cut -d' ' -f1)"
if [ -f "$LIB" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$want" ]; then
    echo "already built with these patches"
else
    # the fork's own build script, without its debug build (an optimized library runs much faster), and with
    # source paths written as /qemu/... (the library keeps file names for its error messages; this keeps the
    # builder's home folder out of it)
    sed -e 's/--enable-debug --enable-debug-info/--disable-debug-info/' \
        -e "s|--extra-cflags=-fPIC |--extra-cflags='-fPIC -ffile-prefix-map=$Q=/qemu' |" \
        "$Q/build_libqemu-esp32.sh" > "$Q/build-ghostboard.sh"
    grep -q -- '--disable-debug-info' "$Q/build-ghostboard.sh" && grep -q -- '-ffile-prefix-map' "$Q/build-ghostboard.sh" \
        || { echo "the fork's build script changed; check build-ghostboard.sh"; exit 1; }
    (cd "$Q" && sh ./build-ghostboard.sh) > "$PREFIX/qemu-build.log" 2>&1 \
        || { echo "build failed: see $PREFIX/qemu-build.log"; tail -20 "$PREFIX/qemu-build.log"; exit 1; }
    [ -f "$LIB" ] || { echo "build finished but $LIB is missing: see $PREFIX/qemu-build.log"; exit 1; }
    echo "$want" > "$STAMP"
    echo "built"
fi

say "installing the library into PICSimLab"
DEST="$PREFIX/picsimlab/usr/lib/picsimlab/qemu/libqemu-xtensa.so"
[ -f "$DEST.orig" ] || cp "$DEST" "$DEST.orig"
if cmp -s "$LIB" "$DEST"; then echo "already installed"; else cp "$LIB" "$DEST" && echo "installed (stock kept as .orig)"; fi

say "LCD mirror fix"
python3 "$REPO/patches/picsimlab/mirror-fix.py" "$PREFIX/picsimlab/usr/bin/picsimlab"

say "done"
echo "GHOSTBOARD is set up in $PREFIX. Next: scripts/flash-firmware, then scripts/ghostboard (see README)."
