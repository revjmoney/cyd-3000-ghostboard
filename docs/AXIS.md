# Running AXIS Micro BBS on the GHOSTBOARD

GHOSTBOARD was built for [AXIS Micro BBS](https://github.com/revjmoney/axis-bbs). This is the path that's been
walked end to end.

## 1. Flash an AXIS build

Build AXIS for the `cyd` environment (PlatformIO), or take the images from an AXIS release, then:

```bash
B=path/to/axis-bbs/.pio/build/cyd
scripts/flash-firmware --bootloader $B/bootloader.bin --partitions $B/partitions.bin \
                       --otadata ~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin \
                       --app $B/firmware.bin
```

## 2. Wi-Fi

The emulated network is an open one named `PICSimLabWifi`. On first boot AXIS shows its Wi-Fi picker: click
`PICSimLabWifi` and it joins and remembers it.

To skip that (scripts, or a board nobody is watching), preload it: AXIS keeps its saved networks in NVS
(namespace `net`, key `s0`).

```bash
tools/nvs_wifi.py                    # defaults: --ssid PICSimLabWifi --namespace net --key s0
scripts/ghostboard --fresh
tail -f ~/.ghostboard/serial.log     # axis: joining PICSimLabWifi ... axis: wifi PICSimLabWifi ip 192.168.4.15
```

## 3. First-boot setup over telnet

A fresh AXIS asks for its sysop setup. Click "OVER TELNET" on the board's screen, note the 6-digit PIN it shows,
then `telnet localhost 2323` and type the PIN when asked.

For scripted setups with nobody at the screen, the PIN is also in the board's memory. Read it through the QEMU
monitor (the address of `setupPin` comes from your build's `firmware.elf`; the PIN is kept inline in the Arduino
String):

```bash
NM=~/.platformio/packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-nm
A=$($NM $B/firmware.elf | awk '/ setupPin$/ {print $1}')
printf 'x /8xb 0x%s\nquit\n' "$A" | nc -q1 127.0.0.1 4555 | tr -d '\r' | grep -A1 "^$A"
```

Then answer the wizard: sysop handle and password, BBS name, board name (callers dial `<name>.local`), and the
rest can stay at their defaults. One thing: AXIS 0.52 and older take CR LF as two Enters, so if your telnet
sends CR LF for Enter, a blank second answer can slip in (0.53 fixed this). `telnet` on Linux sends CR NUL by
default, which is fine.

## 4. Themes and menus on the SD card

```bash
scripts/ghostboard-stop
tools/sd_fill.py path/to/your-card-folder    # e.g. a folder holding themes/ and menus/ from axis-bbs
scripts/ghostboard
```

## 5. Join an AXIS BBS as a node

The GHOSTBOARD can be one more node of a real AXIS BBS (a cluster of CYD boards sharing callers, users and
files). Two things make it work behind the emulator's private network:

- `ghostboard` forwards the host's UDP port 2325 to the board, so the main board's announcements reach it. They
  carry the main's address, and the board dials the main's TCP port 2324 out through the emulator's NAT.
- The board needs the cluster key every board of that BBS shares. On a real board you type `@CLUSTERKEY` on the
  serial console; here, write it into NVS (namespace `clu`, key `key`) from a file, so it never shows:

```bash
scripts/ghostboard-stop
tools/nvs_wifi.py --set clu key @path/to/cluster-key.txt
scripts/ghostboard --fresh
```

Run it **without an SD card** (delete the `SD Card` line from `~/.ghostboard/workspace/picsimlab_workspace/parts_ESP32_DevKitC.pcf`):
a board with a card can win the main role, and you want your real main to stay the main. A cardless node pulls
its screens from the main, like any cardless AXIS node. Its own announcements never leave the emulator's NAT, so
the real boards never mistake it for a main.

When it joins, the main copies its users over; with the cache fix that takes seconds (it used to take minutes and
the node kept dropping out).

## 6. Radio calls through an LFD3K-SM modem

Plug an [LRA FLOWTRON DATAMASTER 3000 SERIAL MODEM - LFD3K-SM](https://github.com/revjmoney/lfd3k-sm) into the
same PC and run:

```bash
tools/lfd3k_bridge.py --port /dev/ttyUSB0 --bbs 127.0.0.1:2323
```

It answers `RING` with `ATA`, connects the caller to the board's telnet port on `CONNECT`, and hangs up on
`NO CARRIER`. It changes no modem settings. Like the modem does on a Wi-Fi forward, it tells AXIS the call
came over the radio (telnet option 90, LFD3K-LINK, with the tier and speed from the `CONNECT` line), so the
board shows `RADIO SF9` for the caller and gives slow tiers its lighter screens; `--no-link` turns that off. On Linux, opening a CP2102 port pulses DTR/RTS; the bridge leaves
both raised so the modem doesn't reset.

<p align="center"><a href="https://buymeacoffee.com/revjmoney"><img src="img/buy-me-a-coffee.svg" alt="Buy me a coffee" width="300"></a></p>
