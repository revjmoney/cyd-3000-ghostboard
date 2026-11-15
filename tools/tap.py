#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
"""Tap the GHOSTBOARD's screen at the firmware's own screen coordinates (320x240 landscape).

  tap.py X Y [HOLD_SECONDS]

Sends button events straight to PICSimLab's parts window (XSendEvent), because faked pointer input does not
reach X windows on a GNOME Wayland desktop. Needs python3-xlib, and the board started by `ghostboard`
(it sets GDK_CORE_DEVICE_EVENTS=1 so GTK takes these events).
Known issue: the emulated touch controller does not report taps to firmware yet (see README).
"""
import sys
import time

try:
    from Xlib import X, display, protocol
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
        sys.exit(__doc__.strip().splitlines()[2].strip())
    x, y = int(sys.argv[1]), int(sys.argv[2])
    hold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6
    d = display.Display()
    root = d.screen().root
    win = find(root)
    if not win:
        sys.exit("no GHOSTBOARD parts window found (is it running?)")
    wx, wy = LCD_X + x, LCD_Y + y
    r = win.translate_coords(root, 0, 0)
    rx, ry = -r.x + wx, -r.y + wy

    def ev(cls, detail, state):
        return cls(time=X.CurrentTime, root=root, window=win, same_screen=1, child=X.NONE,
                   root_x=rx, root_y=ry, event_x=wx, event_y=wy, state=state, detail=detail)

    win.send_event(ev(protocol.event.MotionNotify, 0, 0), event_mask=X.PointerMotionMask)
    win.send_event(ev(protocol.event.ButtonPress, 1, 0), event_mask=X.ButtonPressMask)
    d.sync()
    time.sleep(hold)
    win.send_event(ev(protocol.event.ButtonRelease, 1, X.Button1Mask), event_mask=X.ButtonReleaseMask)
    d.sync()
    print(f"tapped {x},{y}")


if __name__ == "__main__":
    main()
