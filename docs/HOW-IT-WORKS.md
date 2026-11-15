# How the GHOSTBOARD works, and what it took

## The pieces

- **PICSimLab 0.9.3** (Luis Claudio Gamboa Lopes) draws the board and its parts: the ILI9341 LCD with an XPT2046
  touch controller, an SD card, a serial terminal. It loads QEMU as a library and trades pin and bus traffic with
  it.
- **lcgamboa's QEMU fork** (branch `picsimlab-esp32`) carries Espressif's ESP32 machine: two Xtensa LX6 cores,
  the flash behind a SPI controller and a cache, the interrupt matrix, timers, and an emulated Wi-Fi (QEMU user
  networking, 192.168.4.0/24) that real ESP-IDF Wi-Fi drivers talk to.
- **The board file** (`board/cyd/`) wires the parts to the CYD's pins, turns on serial and Wi-Fi, turns off the
  hardware watchdog (an emulator is not real time), and opens a QEMU monitor on 127.0.0.1:4555, which
  `ghostboard` uses to add port forwards.

## The four fixes

### 1. Boot loop at do_core_init (GigaDevice quad enable)

`assert failed: do_core_init startup.c:328 (flash_ret == ESP_OK)` on every boot. The ESP32 machine picks a
GigaDevice gd25q32 for a 4 MB flash. Firmware built for QIO (quad I/O, the default for many CYD builds) sets the
flash's quad-enable bit and reads it back. QEMU's flash model only tracked that bit for Winbond parts, so the
read-back said 0 and startup gave up. GigaDevice uses the same status register layout as Winbond, so it now gets
the same handling. (`patches/qemu/0001`)

### 2. NVS wiped at every boot (SPI dummy cycles)

Saved Wi-Fi disappeared on every restart, and LittleFS could neither mount nor format. Tracing the flash
commands showed ESP-IDF reading the NVS page headers and then erasing the page it had just read. A one-off print
in the SPI controller model showed the bytes reaching the CPU were shifted: the flash model expected address,
mode byte and 4 dummy cycles before the data, but the controller never sent the dummy cycles, so the first data
bytes were eaten as dummies. Sending ESP-IDF's own dummy count was also wrong, by 3 bytes: it includes extra
cycles real hardware needs for signal delay at speed. The model now sends the flash's own count for the reads
that have dummies. (`patches/qemu/0002`)

### 3. Flash calls taking 11 ms (cache toggles rebuilding the memory map)

An AXIS cluster node joined its main, started copying users into internal flash, froze for 12 to 150 seconds,
missed the main's heartbeat and dropped out, over and over. The emulator managed about 250 flash operations a
second. Changing how QEMU switches between the two cores did nothing, and neither did removing PICSimLab's
parts. Host stack samples (gdb attached to the running emulator) showed the core doing the flash work inside
`esp32_cache_state_update`, which called `memory_region_set_enabled()` and so rebuilt QEMU's entire memory map on
every cache toggle, while the other core waited on QEMU's big lock. ESP-IDF turns the cache off and back on around
every flash call, on both cores. The cache regions now stay mapped once the guest has turned them on (correct
code never reads cached flash while the cache is off), and still re-sync from flash when it turns them back on.
Result: 6.4 times the flash throughput, and the node stays joined. (`patches/qemu/0003`)

### 4. Mirrored screen (ILI9341 row flip)

PICSimLab's ILI9341 flips a pixel's row when MADCTL's MY bit is clear instead of when it's set, so firmware that
sets MADCTL correctly (LovyanGFX, TFT_eSPI) shows a mirror image. In the 0.9.3 Linux binary that's one
conditional move; `patches/picsimlab/mirror-fix.py` flips it, and only touches the exact 0.9.3 binary.

## Also tuned

- **PICSimLab's step rate** (`ESP32_DevKitC_clock` = 0.2 in the board file): PICSimLab steps its parts once per
  step of that clock, every 100 ms, holding QEMU's big lock. 1.0 meant 100,000 steps per 100 ms; 0.2 gave about
  35% more flash throughput, and the serial terminal still decodes 115200 baud.

## Tools used to find these

- QEMU traces with timestamps in the board file's extra arguments:
  `-msg timestamp=on -d trace:m25p80_command_decoded -D /tmp/m25.log`
- The QEMU monitor (`cpu N`, `info registers`, `x /16xb ADDR`) to sample the guest's program counters and read
  its RAM, mapped back to functions with the firmware's ELF and `xtensa-esp32-elf-addr2line`.
- Host stacks: Ubuntu blocks gdb from attaching to a process it didn't start (Yama), so the emulator ran with a
  tiny LD_PRELOAD library calling `prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY)`, then
  `gdb -p PID -batch -ex "thread apply all bt 14"` a few dozen times during a stall.

<p align="center"><a href="https://buymeacoffee.com/revjmoney"><img src="img/buy-me-a-coffee.svg" alt="Buy me a coffee" width="300"></a></p>
