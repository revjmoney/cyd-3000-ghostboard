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

### 5. GPIO32-39 (the touch controller's wires)

A CYD's XPT2046 touch controller is bit-banged on GPIO25 (clock), GPIO32 (MOSI), GPIO33 (CS) and GPIO39
(MISO). Counting pin traffic at the QEMU/PICSimLab boundary showed millions of clock writes and none on MOSI or
CS: the GPIO model ignored `GPIO_OUT1` / `GPIO_ENABLE1`, and only GPIO0-31 were wired to PICSimLab as outputs.
With that fixed, the controller still never answered: PICSimLab only passes a part's output to the firmware on
pins it thinks are inputs, and learns a pin's direction only from output-enable changes. GPIO39 and GPIO36 are
inputs from reset (input-only, in fact), so nothing ever told it. The model now reports every non-output pin as
an input on the first input read, and masks the high enable bits to GPIO32-33 the way the real chip does
(firmware does set GPIO39's bit, harmlessly on hardware). (`patches/qemu/0004`)

### 6. Touch that lands where you click

Then the touch controller answered, and the screen still didn't react. A trace of every byte the firmware read
(decoded the way LovyanGFX does) showed four problems in PICSimLab's XPT2046 model, all fixed on the GPIO side
because PICSimLab is a prebuilt binary here (`patches/qemu/0005`, turned on by the board's `touch` setting):

- **One clock early.** The model changes MISO on the rising clock edge; a real XPT2046 changes it after the
  falling edge, and LovyanGFX samples right after raising the clock. Every reading came back doubled, so a tap in
  the middle of the screen landed above 3968 and was thrown away as noise. MISO changes are held until CLK falls.
- **Mirrored and too wide.** The model spreads 0-4095 across the screen in the opposite direction to a CYD's
  panel, and wider than the CYD's calibration, so taps landed mirrored through the centre and off near the edges.
  The GPIO model follows the control bytes on MOSI and sends each X/Y conversion remapped onto the panel's range.
  A value is only known after its 12 bits, so each conversion carries the previous one's value (the firmware
  takes 7 per touch and uses the median); the first of a new press goes out as "no reading".
- **Never let go.** After release the model keeps answering the last position, so the panel looked held down and
  the firmware (which acts on a new press) never saw another one. While PENIRQ is high, X/Y read 4095, like a
  real idle panel.
- **The right half didn't count.** LovyanGFX's pressure figure is `0x3200 + Y - X + (Z1 - Z2) / 2` on the raw
  words; the model's fixed Z1 = 1000, Z2 = 4095 made it negative wherever Y is small, which on a CYD is the right
  half of the screen. Pressed now answers firm pressure (Z1 2000, Z2 1000).

PICSimLab's remote control (port 5000) turned out handy here: `set part[02].in[01] @WIFIPICK` types a command
into the board's serial console, which opened AXIS's Wi-Fi picker and its on-screen keyboard to test every part
of the screen.

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
