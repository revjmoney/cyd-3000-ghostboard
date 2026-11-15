#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
"""Copy a folder tree onto the GHOSTBOARD's SD card image (FAT, long names kept), no mounting or root needed.

  sd_fill.py SRC_DIR [--image $GHOSTBOARD_HOME/sd.img]

Every folder in SRC_DIR lands at the card's root (SRC_DIR/themes -> /themes); files already there are replaced.
Stop the board first (ghostboard-stop): it holds the image open.
Needs pyfatfs (pip install pyfatfs==1.1.0). Afterwards runs `fsck.fat -a` when present: pyfatfs leaves FAT32's
free-space hint stale, and some firmware reads it.
"""
import argparse
import os
import shutil
import subprocess
import sys
import types

# fs 2.4 (pulled in by pyfatfs) imports pkg_resources, which setuptools 81+ no longer ships; only two calls
# are made and neither matters when an image is opened directly.
try:
    import pkg_resources  # noqa: F401
except ImportError:
    stub = types.ModuleType("pkg_resources")
    stub.declare_namespace = lambda name: None
    stub.iter_entry_points = lambda group, name=None: iter(())
    sys.modules["pkg_resources"] = stub

try:
    from pyfatfs.PyFatFS import PyFatFS
except ImportError:
    sys.exit("pyfatfs is needed: python3 -m pip install --user pyfatfs==1.1.0  (or in a venv)")


def board_running(home):
    """True while this install's GHOSTBOARD runs (its PICSimLab is argv[0] of some process)."""
    exe = os.path.join(home, "picsimlab", "usr", "bin", "picsimlab")
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not pid.isdigit():
            continue
        try:
            argv0 = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode(errors="replace")
        except OSError:
            continue
        if argv0 == exe:
            return True
    return False


def main():
    home = os.environ.get("GHOSTBOARD_HOME", os.path.expanduser("~/.ghostboard"))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--image", default=os.path.join(home, "sd.img"))
    a = ap.parse_args()
    if board_running(home):
        sys.exit("the GHOSTBOARD is running: stop it first (scripts/ghostboard-stop); the emulator has the SD image open")
    if not os.path.isdir(a.src):
        sys.exit(f"{a.src} is not a folder")
    fs = PyFatFS(a.image)
    n = 0
    for root, _dirs, files in os.walk(a.src):
        rel = os.path.relpath(root, a.src).replace(os.sep, "/")
        dest = "/" if rel == "." else "/" + rel
        if not fs.exists(dest):
            fs.makedirs(dest)
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                fs.writebytes(dest.rstrip("/") + "/" + f, fh.read())
            n += 1
    for top in sorted(fs.listdir("/")):
        print(f"/{top}")
    fs.close()
    print(f"{n} files written to {a.image}")
    fsck = shutil.which("fsck.fat") or ("/usr/sbin/fsck.fat" if os.path.exists("/usr/sbin/fsck.fat") else None)
    if fsck:
        subprocess.run([fsck, "-a", a.image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
