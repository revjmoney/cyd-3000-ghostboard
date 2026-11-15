#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
"""Write a string into the emulated board's NVS (ESP-IDF's settings store), offline, in the chip's own format.

Main use: preload the emulator's Wi-Fi so firmware joins it without anyone touching the screen. The emulated
network is open and named PICSimLabWifi. Defaults match AXIS Micro BBS (namespace "net", key "s0"); other
firmware keeps its Wi-Fi under its own names (Arduino's WiFi.begin() stores none: such firmware joins by itself).

  nvs_wifi.py [--flash FILE] [--ssid PICSimLabWifi] [--namespace net] [--key s0]
              [--password P --password-key p0]
  nvs_wifi.py --set NAMESPACE KEY VALUE     (any string; value may be @FILE: its first line, never printed)

The board must be stopped (ghostboard-stop), then started with `ghostboard --fresh`.
NVS is found from the partition table at 0x8000 (type data, subtype nvs).
"""
import argparse
import os
import struct
import sys
import zlib

PAGE = 4096
ENTRIES = 126
ACTIVE, FULL, EMPTY = b"\xfe\xff\xff\xff", b"\xfc\xff\xff\xff", b"\xff\xff\xff\xff"


def find_nvs(flash):
    for i in range(0x8000, 0x8000 + 0xC00, 32):
        e = flash[i:i + 32]
        if e[:2] != b"\xaa\x50":
            break
        typ, sub, off, size = e[2], e[3], struct.unpack_from("<I", e, 4)[0], struct.unpack_from("<I", e, 8)[0]
        if typ == 1 and sub == 2:
            return off, size
    raise SystemExit("no nvs partition in the partition table at 0x8000 (flash the firmware first)")


def crc_entry(e):
    return zlib.crc32(bytes(e[8:32]), zlib.crc32(bytes(e[0:4]), 0xFFFFFFFF)) & 0xFFFFFFFF


def entry(ns, typ, span, chunk, key, data8):
    e = bytearray(b"\xff" * 32)
    e[0], e[1], e[2], e[3] = ns, typ, span, chunk
    k = key.encode()[:15]
    e[8:24] = k + b"\x00" * (16 - len(k))
    e[24:32] = data8
    e[4:8] = struct.pack("<I", crc_entry(e))
    return e


class Nvs:
    def __init__(self, flash, off, size):
        self.f, self.off, self.size = flash, off, size

    def state(self, p, i):
        return (self.f[p + 32 + i // 4] >> ((i % 4) * 2)) & 3

    def set_written(self, p, i):
        o, sh = p + 32 + i // 4, (i % 4) * 2
        self.f[o] = (self.f[o] & ~(3 << sh) & 0xFF) | (2 << sh)

    def pages(self):
        return range(self.off, self.off + self.size, PAGE)

    def active_page(self):
        for p in self.pages():
            if self.f[p:p + 4] == ACTIVE:
                return p
        if any(self.f[p:p + 4] == FULL for p in self.pages()):
            raise SystemExit("NVS has full pages but no active one: start the firmware once, then try again")
        p = self.off                       # a blank NVS: page 0 becomes the active page, seq 0, version 2
        if self.f[p:p + PAGE] != b"\xff" * PAGE:
            raise SystemExit("NVS page 0 is neither in use nor blank: refusing to touch it")
        hdr = bytearray(b"\xff" * 32)
        hdr[0:4] = ACTIVE
        hdr[4:8] = struct.pack("<I", 0)
        hdr[8] = 0xFE
        hdr[28:32] = struct.pack("<I", zlib.crc32(bytes(hdr[4:28]), 0xFFFFFFFF) & 0xFFFFFFFF)
        self.f[p:p + 32] = hdr
        return p

    def namespaces(self):
        found = {}
        for p in self.pages():
            if self.f[p:p + 4] not in (ACTIVE, FULL):
                continue
            i = 0
            while i < ENTRIES:              # walk item headers by span (blob data entries are not headers)
                if self.state(p, i) != 2:
                    i += 1
                    continue
                e = self.f[p + 64 + i * 32: p + 96 + i * 32]
                if e[0] == 0 and e[1] == 0x01:
                    found[bytes(e[8:24]).split(b"\x00")[0].decode("ascii", "replace")] = e[24]
                i += max(1, e[2])
        return found

    def has_key(self, idx, key):
        for p in self.pages():
            if self.f[p:p + 4] not in (ACTIVE, FULL):
                continue
            i = 0
            while i < ENTRIES:
                if self.state(p, i) != 2:
                    i += 1
                    continue
                e = self.f[p + 64 + i * 32: p + 96 + i * 32]
                if e[0] == idx and bytes(e[8:24]).split(b"\x00")[0] == key.encode():
                    return True
                i += max(1, e[2])
        return False

    def put_string(self, ns_name, key, value):
        page = self.active_page()
        names = self.namespaces()
        blob = b""
        if ns_name in names:
            idx = names[ns_name]
            if self.has_key(idx, key):
                raise SystemExit(f"{ns_name}/{key} is already set: change it from the firmware, or start from a "
                                 "fresh flash")
        else:
            idx = next(n for n in range(1, 255) if n not in names.values())
            blob += entry(0, 0x01, 1, 0xFF, ns_name, bytes([idx]) + b"\xff" * 7)
        val = value.encode() + b"\x00"
        data = bytearray(b"\xff" * (32 * ((len(val) + 31) // 32)))
        data[:len(val)] = val
        blob += entry(idx, 0x21, 1 + len(data) // 32, 0xFF, key,
                      struct.pack("<HH", len(val), 0xFFFF) + struct.pack("<I", zlib.crc32(val, 0xFFFFFFFF) & 0xFFFFFFFF))
        blob += data
        n = len(blob) // 32
        first = next((i for i in range(ENTRIES) if self.state(page, i) == 3), None)
        if first is None or first + n > ENTRIES or any(self.state(page, first + j) != 3 for j in range(n)):
            raise SystemExit("no room on the active NVS page")
        self.f[page + 64 + first * 32: page + 64 + (first + n) * 32] = blob
        for j in range(n):
            self.set_written(page, first + j)


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
    ap.add_argument("--flash", default=os.path.join(home, "workspace", "picsimlab_workspace",
                                                    "mdump_ESP32_DevKitC_ESP32.bin"))
    ap.add_argument("--ssid", default="PICSimLabWifi")
    ap.add_argument("--namespace", default="net")
    ap.add_argument("--key", default="s0")
    ap.add_argument("--password")
    ap.add_argument("--password-key", default="p0")
    ap.add_argument("--set", nargs=3, metavar=("NAMESPACE", "KEY", "VALUE"))
    a = ap.parse_args()
    if board_running(home):
        sys.exit("the GHOSTBOARD is running: stop it first (scripts/ghostboard-stop), or the next start would copy the running board's flash back over this")

    flash = bytearray(open(a.flash, "rb").read())
    off, size = find_nvs(flash)
    nvs = Nvs(flash, off, size)
    if a.set:
        ns, key, value = a.set
        if value.startswith("@"):
            value = open(value[1:], encoding="utf-8").read().splitlines()[0].strip()
        nvs.put_string(ns, key, value)
        print(f"set {ns}/{key} ({len(value)} characters) in NVS at {off:#x}")
    else:
        nvs.put_string(a.namespace, a.key, a.ssid)
        if a.password:
            nvs.put_string(a.namespace, a.password_key, a.password)
        print(f"Wi-Fi {a.ssid!r} saved as {a.namespace}/{a.key} in NVS at {off:#x}")
    tmp = a.flash + ".tmp"
    open(tmp, "wb").write(flash)
    os.replace(tmp, a.flash)


if __name__ == "__main__":
    main()
