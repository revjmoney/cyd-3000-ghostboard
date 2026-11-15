# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
# Shared by ghostboard and ghostboard-stop (sourced, not run).

GH="${GHOSTBOARD_HOME:-$HOME/.ghostboard}"
PS="$GH/picsimlab"                       # unpacked PICSimLab with the patched QEMU (scripts/setup.sh)
WSROOT="$GH/workspace"                   # the board: zipped into $PZW at every start
WS="$WSROOT/picsimlab_workspace"
PZW="$GH/ghostboard.pzw"
FLASH="$WS/mdump_ESP32_DevKitC_ESP32.bin"
MONITOR_PORT=4555

# PICSimLab processes started from this install (the bracket keeps pgrep from matching its own command line)
gb_pids() { pgrep -f "^$PS/usr/bin/[p]icsimlab" || true; }

# The flash the running board is writing: every start unpacks the workspace into a fresh /tmp/picsimlab-XXXXXX,
# so what the firmware saved (settings, Wi-Fi, users) only lives there until it is copied back.
gb_live_flash() {
    local d
    d=$(ls -td /tmp/picsimlab-*/ 2>/dev/null | head -1)
    [ -n "$d" ] && [ -s "${d}picsimlab_workspace/mdump_ESP32_DevKitC_ESP32.bin" ] \
        && echo "${d}picsimlab_workspace/mdump_ESP32_DevKitC_ESP32.bin"
}

gb_save_live() {
    local live
    [ -n "$(gb_pids)" ] || return 0
    live=$(gb_live_flash) || true
    if [ -n "$live" ]; then
        cp "$live" "$FLASH" && echo "saved the running board's flash"
    fi
}

gb_kill() {
    local p
    for p in $(gb_pids); do kill -9 "$p"; done
}

gb_pack() {
    (cd "$WSROOT" && rm -f "$PZW" && zip -qr "$PZW" picsimlab_workspace)
}
