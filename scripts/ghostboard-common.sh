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

# PICSimLab processes started from THIS install: argv[0] is exactly $PS/usr/bin/picsimlab (compared as text, so
# a home folder with spaces or regex characters in it is fine, and other PICSimLab sessions never match)
gb_pids() {
    local d exe
    for d in /proc/[0-9]*; do
        exe="$(tr '\0' '\n' < "$d/cmdline" 2>/dev/null | head -1)" || continue
        [ "$exe" = "$PS/usr/bin/picsimlab" ] && echo "${d#/proc/}"
    done
    return 0
}

# The flash a running board is writing. Every start unpacks the workspace into a fresh /tmp/picsimlab-XXXXXX,
# so what the firmware saves (settings, Wi-Fi, users) lives only there until it is copied back. Found through the
# process's own open files: QEMU keeps the flash file open, so this is that board's flash, never another
# PICSimLab session's.
gb_live_flash() {
    local p f t
    for p in $(gb_pids); do
        for f in /proc/"$p"/fd/*; do
            t="$(readlink "$f" 2>/dev/null)" || continue
            case "$t" in
                /*/picsimlab-*/picsimlab_workspace/mdump_ESP32_DevKitC_ESP32.bin) echo "$t"; return 0 ;;
            esac
        done
    done
    return 1
}

gb_kill() {
    local p
    for p in $(gb_pids); do kill -9 "$p" 2>/dev/null; done
    for _ in 1 2 3 4 5 6 7 8 9 10; do [ -z "$(gb_pids)" ] && return 0; sleep 0.2; done
}

# Stop the running board. With "save", what the firmware wrote goes back into the workspace: the process is
# stopped first (no copy of a file QEMU is still writing), then its flash is copied, then its temp folder goes.
gb_stop() {
    local live tmpdir
    [ -n "$(gb_pids)" ] || return 0
    live="$(gb_live_flash)" || live=""
    gb_kill
    if [ -n "$live" ] && [ -s "$live" ]; then
        tmpdir="${live%/picsimlab_workspace/*}"
        if [ "${1:-}" = "save" ]; then
            cp "$live" "$FLASH.tmp" && mv "$FLASH.tmp" "$FLASH" && echo "saved the running board's flash"
        fi
        case "$tmpdir" in /*/picsimlab-*) rm -rf "$tmpdir" ;; esac
    elif [ "${1:-}" = "save" ]; then
        echo "could not find the running board's flash: nothing saved"
    fi
}

gb_pack() {
    (cd "$WSROOT" && rm -f "$PZW" && zip -qr "$PZW" picsimlab_workspace)
}
