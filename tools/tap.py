#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
"""Tap the GHOSTBOARD's screen at the firmware's own screen coordinates (320x240 landscape), for scripts and tests.

  tap.py X Y [HOLD_SECONDS]        (default hold 0.6 s)

Moves the desktop pointer onto the emulated LCD and clicks it with XTest (real input, as a mouse would), so the
board must be visible on the desktop. Needs python3-xlib. For people, just click the screen with the mouse.
The emulated firmware polls touch in its main loop; if it is busy (a redraw, a Wi-Fi scan), hold a little longer.
"""
import sys
import time

try:
    from Xlib import X, display
    from Xlib.ext import xtest
except ImportError:
    sys.exit("python3-xlib is needed (sudo apt install python3-xlib)")

LCD_X, LCD_Y = 137, 100   # the LCD's top-left inside the parts window: part at (20,20), screen at (117,55), menu 25


def find(win):
    name, cls = win.get_wm_name(), win.get_wm_class()
    if name and "Spare parts" in name and cls and "qemu" in cls[0]:
        return win
    for child in win.query_tree().children:
        hit = find(child)
        if hit:
            return hit
    return None


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: tap.py X Y [HOLD_SECONDS]")
    x, y = int(sys.argv[1]), int(sys.argv[2])
    if not (0 <= x < 320 and 0 <= y < 240):
        sys.exit("X must be 0-319 and Y 0-239 (the CYD's landscape screen)")
    hold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6
    d = display.Display()
    root = d.screen().root
    win = find(root)
    if not win:
        sys.exit("no GHOSTBOARD parts window found (is it running?)")
    r = win.translate_coords(root, 0, 0)
    sx, sy = -r.x + LCD_X + x, -r.y + LCD_Y + y
    xtest.fake_input(d, X.MotionNotify, x=sx, y=sy)
    d.sync()
    time.sleep(0.2)
    xtest.fake_input(d, X.ButtonPress, 1)
    d.sync()
    time.sleep(hold)
    xtest.fake_input(d, X.ButtonRelease, 1)
    d.sync()
    print(f"tapped {x},{y}")


if __name__ == "__main__":
    main()
