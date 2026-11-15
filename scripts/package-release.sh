#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
#
# Make the ready-to-run download from a finished setup: PICSimLab with the patched QEMU library and the mirror
# fix, plus this repo's scripts, tools, board and docs, and an install.sh.
#   scripts/package-release.sh [--prefix DIR] [--version 0.1.0] [--out DIR]
set -euo pipefail
PREFIX="${GHOSTBOARD_HOME:-$HOME/.ghostboard}"; VERSION="0.1.0"; OUT="$(pwd)/dist"
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        *) echo "unknown option $1"; exit 1 ;;
    esac
done
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NAME="cyd-3000-ghostboard-$VERSION"
LIB="$PREFIX/picsimlab/usr/lib/picsimlab/qemu/libqemu-xtensa.so"
STAMP="$PREFIX/src/qemu/build/.ghostboard-patches"
BUILD_FLAGS="$(grep -m1 '^BUILD_FLAGS=' "$REPO/scripts/setup.sh" | cut -d'"' -f2)"
want="$( { cat "$REPO"/patches/qemu/*.patch; echo "$BUILD_FLAGS"; } | sha256sum | cut -d' ' -f1)"
[ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$want" ] || { echo "$PREFIX was not built with this repo's patches and flags: run scripts/setup.sh"; exit 1; }
cmp -s "$LIB" "$PREFIX/src/qemu/build/libqemu-xtensa.so" || { echo "the installed library is not the patched build"; exit 1; }
# nothing from the builder's machine in the binaries (home folder, user name)
for f in "$LIB" "$PREFIX/picsimlab/usr/bin/picsimlab"; do
    if strings "$f" | grep -q -e "$HOME" -e "/home/$(id -un)"; then
        echo "$f has paths from this machine in it ($HOME): rebuild with scripts/setup.sh"; exit 1
    fi
done
python3 "$REPO/patches/picsimlab/mirror-fix.py" "$PREFIX/picsimlab/usr/bin/picsimlab" | grep -q "already patched" \
    || { echo "the picsimlab binary is not the mirror-fixed 0.9.3 one"; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
D="$STAGE/$NAME"
mkdir -p "$D"
cp -a "$PREFIX/picsimlab" "$D/picsimlab"
rm -f "$D/picsimlab/usr/bin/picsimlab.orig" "$D/picsimlab/usr/lib/picsimlab/qemu/libqemu-xtensa.so.orig"
# the repo part: committed files only (never local edits, stray files or __pycache__)
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "package from a git checkout of the repo"; exit 1; }
[ -z "$(git -C "$REPO" status --porcelain -- scripts tools board patches docs README.md LICENSE NOTICE)" ] \
    || echo "note: uncommitted changes in the repo are left out (the release is built from HEAD)"
git -C "$REPO" archive HEAD scripts tools board patches docs/AXIS.md docs/HOW-IT-WORKS.md docs/img \
    README.md LICENSE NOTICE | tar -x -C "$D"
rm -f "$D/scripts/check-private.sh" "$D/scripts/package-release.sh"
qcommit="$(git -C "$PREFIX/src/qemu" rev-parse HEAD)"
cat > "$D/SOURCES.txt" <<EOF
CYD-3000 GHOSTBOARD $VERSION: where every binary in this download comes from (GPL-2.0)

picsimlab/   PICSimLab 0.9.3 by Luis Claudio Gamboa Lopes, the official Linux x86_64 AppImage, unpacked:
             https://github.com/lcgamboa/picsimlab/releases/tag/v0.9.3
             source: https://github.com/lcgamboa/picsimlab (tag v0.9.3)
             changed: usr/bin/picsimlab, one byte (patches/picsimlab/mirror-fix.py);
                      usr/lib/picsimlab/qemu/libqemu-xtensa.so, rebuilt as below.

libqemu-xtensa.so   built from https://github.com/lcgamboa/qemu branch picsimlab-esp32, commit $qcommit,
             with patches/qemu/*.patch from this download applied, using that fork's build_libqemu-esp32.sh
             with --enable-debug --enable-debug-info replaced by --disable-debug-info and
             -ffile-prefix-map=<source dir>=/qemu added to --extra-cflags (scripts/setup.sh does exactly this).

everything else: CYD-3000 GHOSTBOARD, https://github.com/revjmoney/cyd-3000-ghostboard (tag v$VERSION)

The complete corresponding source of both binaries is published next to this download on the same release:
  picsimlab-0.9.3-src.tar.xz       PICSimLab at tag v0.9.3
  qemu-${qcommit:0:7}-src.tar.xz        lcgamboa/qemu at $qcommit (apply patches/qemu/*.patch)
EOF
cat > "$D/install.sh" <<'EOF'
#!/bin/bash
# Put this download's PICSimLab (with the patched QEMU) where the GHOSTBOARD scripts look for it.
#   ./install.sh [--prefix DIR]     (default ~/.ghostboard)
set -euo pipefail
PREFIX="${GHOSTBOARD_HOME:-$HOME/.ghostboard}"
[ "${1:-}" = "--prefix" ] && PREFIX="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$PREFIX"
if [ -d "$PREFIX/picsimlab" ]; then
    echo "$PREFIX/picsimlab is already there: replacing it"
    rm -rf "$PREFIX/picsimlab"
fi
cp -a "$HERE/picsimlab" "$PREFIX/picsimlab"
echo "installed into $PREFIX/picsimlab"
[ "$PREFIX" = "$HOME/.ghostboard" ] || echo "use it with: export GHOSTBOARD_HOME=$PREFIX"
echo "next: scripts/flash-firmware ..., then scripts/ghostboard --fresh  (see README.md)"
EOF
chmod +x "$D/install.sh"
# last look before packing: nothing from this machine, nothing on the personal list (if the repo has one)
hits=0
while IFS= read -r -d '' f; do
    if grep -qI -e "$HOME" -e "/home/$(id -un)" "$f" 2>/dev/null \
       || { [ -s "$f" ] && ! grep -qI . "$f" && strings "$f" | grep -q -e "$HOME" -e "/home/$(id -un)"; }; then
        echo "PRIVATE: ${f#$STAGE/} has paths from this machine"; hits=1
    fi
    if [ -f "$REPO/local/private-patterns.txt" ]; then
        while IFS= read -r pat; do
            pat="${pat%$'\r'}"; [ -n "$pat" ] && [ "${pat:0:1}" != "#" ] || continue
            grep -qaiE "$pat" "$f" && { echo "PRIVATE: ${f#$STAGE/} matches a personal pattern"; hits=1; }
        done < "$REPO/local/private-patterns.txt"
    fi
done < <(find "$D" -type f -print0)
[ $hits -eq 0 ] || { echo "not packing: see above"; exit 1; }
echo "privacy scan of the release: clean"

mkdir -p "$OUT"
tar -C "$STAGE" -cJf "$OUT/$NAME-linux-x86_64.tar.xz" "$NAME"
# GPL-2.0: the complete source of both binaries, as release files next to the tarball
git -C "$PREFIX/src/qemu" archive --prefix="qemu-${qcommit:0:7}/" "$qcommit" | xz -T0 > "$OUT/qemu-${qcommit:0:7}-src.tar.xz"
PSRC="$PREFIX/src/picsimlab"
[ -d "$PSRC/.git" ] || git clone -q --depth 1 --branch v0.9.3 https://github.com/lcgamboa/picsimlab "$PSRC"
git -C "$PSRC" archive --prefix=picsimlab-0.9.3/ HEAD | xz -T0 > "$OUT/picsimlab-0.9.3-src.tar.xz"
(cd "$OUT" && sha256sum "$NAME-linux-x86_64.tar.xz" picsimlab-0.9.3-src.tar.xz "qemu-${qcommit:0:7}-src.tar.xz" > SHA256SUMS)
ls -la "$OUT"
