#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
"""Fix PICSimLab 0.9.3's ILI9341 drawing everything mirrored left to right.

The emulated ILI9341 flips a pixel's row (ly = 319 - ly) when MADCTL bit 7 (MY) is CLEAR instead of when it is
set (lcd_ili9341.cc, pixel write). In the 0.9.3 Linux x86_64 binary that is one `cmovns` at file offset
0x1f5483; making it `cmovs` (opcode byte 0x49 -> 0x48 at 0x1f5485) flips the test. The upstream source fix is
`if (lcd->mac & 0x80)` instead of `if (!(lcd->mac & 0x80))`.

Only the exact 0.9.3 binary is touched (checked by sha256); anything else is refused, so a newer PICSimLab
never gets a byte written into the wrong place.

usage: mirror-fix.py PATH/TO/usr/bin/picsimlab
exit: 0 patched or already patched, 2 unknown binary, 1 error
"""
import hashlib
import os
import shutil
import sys

UNPATCHED = "6ad7ee41e7ce359e30d84d8f267745d8f270980faa56c0f537de62499e5918a2"
PATCHED = "7c567468e6d67a5f5685c44bda791d9c949995a5e2e58c29cb33949c6a5c7a29"
OFFSET, OLD, NEW = 0x1F5485, 0x49, 0x48


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-3])
        return 1
    path = sys.argv[1]
    digest = sha256(path)
    if digest == PATCHED:
        print("mirror fix: already patched")
        return 0
    if digest != UNPATCHED:
        print(f"mirror fix: {path} is not the PICSimLab 0.9.3 binary this fix is for (sha256 {digest[:16]}...); "
              "left alone")
        return 2
    data = bytearray(open(path, "rb").read())
    if data[OFFSET] != OLD:
        print("mirror fix: unexpected byte at the patch spot; left alone")
        return 2
    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    data[OFFSET] = NEW
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    if sha256(path) != PATCHED:
        shutil.copy2(backup, path)
        print("mirror fix: result did not check out; original restored")
        return 1
    print("mirror fix: applied (original kept as picsimlab.orig)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
