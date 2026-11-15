#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
"""Answer radio calls on the LFD3K-SM modem's USB port and hand them to a telnet BBS.

usage: lfd3k_bridge.py [--port /dev/ttyUSB0] [--bbs 127.0.0.1:2323]

The modem is the LRA FLOWTRON DATAMASTER 3000 SERIAL MODEM - LFD3K-SM (https://github.com/revjmoney/lfd3k-sm)
on USB; the BBS is the GHOSTBOARD's telnet forward. Needs pyserial.

The modem stays in its own settings (S0=0, nothing saved): on RING this sends ATA, on CONNECT it opens
a TCP connection to the BBS and copies bytes both ways. The BBS's telnet option requests are refused
politely (a radio caller has a plain terminal), and IAC bytes are taken out of what goes over the air.

An AXIS BBS is also told this is a radio call, the way the modem itself does when it forwards a call over
Wi-Fi: after the BBS's opening negotiation the bridge offers telnet option 90 (LFD3K-LINK), and once the
BBS says DO 90 it sends a report (`v=1 modem=<name> kind=radio caller=- tier=SF12 bps=1172`, from the
CONNECT line) at the start and every 10 s. AXIS then shows the call as RADIO SF12 and gives slow tiers its
lighter screens. Signal values are left out (the modem prints none on the answering side). --no-link
turns this off.
The call ends on NO CARRIER from the modem, or when the BBS closes (then +++ with guard time, ATH).
The port is opened with DTR and RTS left raised: clearing them one at a time resets an ESP32 board.
"""
import argparse
import os
import select
import socket
import sys
import time

import serial

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
OPT_LINK = 90          # LFD3K-LINK: link stats for an AXIS BBS
LINK_EVERY = 10.0      # seconds between reports


def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    print(line, flush=True)


def link_payload(modem, connect):
    """The LFD3K-LINK report for a CONNECT line like 'CONNECT LORA SF12 BW500 1172/ARQ/LZ', or None."""
    words = connect.split()
    tier = next((w for w in words if w.startswith('SF') and w[2:].isdigit() and 5 <= int(w[2:]) <= 12), None)
    if not tier:
        return None
    safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in modem)[:24] or '-'
    fields = ['v=1', f'modem={safe}', 'kind=radio', 'caller=-', f'tier={tier}']
    speed = next((w for w in words if w.split('/')[0].isdigit()), '')
    if speed:
        fields.append('bps=' + speed.split('/')[0])
        if '/' in speed and 'LZ' not in speed.split('/')[1:]:
            fields.append('lz=0')
    return ' '.join(fields).encode('ascii')


class Telnet:
    """Strips telnet commands from the BBS stream and answers them with refusals; offers LFD3K-LINK (option 90)
    once after the BBS's opening negotiation when there is a report to send."""

    def __init__(self, report=None):
        self.state = 0
        self.cmd = 0
        self.report = report      # payload bytes, or None: never offer option 90
        self.offered = False
        self.link_on = False
        self.negotiated = False   # the BBS has sent at least one option request
        self.last_sent = 0.0

    def frame(self):
        return bytes([IAC, SB, OPT_LINK]) + self.report + bytes([IAC, SE])

    def after_feed(self, sock):
        """Call after each feed: makes the offer once the opening negotiation has been seen, and sends a report
        when one is due."""
        if self.report is None:
            return
        if self.negotiated and not self.offered:
            self.offered = True
            sock.sendall(bytes([IAC, WILL, OPT_LINK]))
        if self.link_on and time.time() - self.last_sent >= LINK_EVERY:
            self.last_sent = time.time()
            sock.sendall(self.frame())

    def feed(self, data, sock):
        out = bytearray()
        for b in data:
            if self.state == 0:
                if b == IAC:
                    self.state = 1
                else:
                    out.append(b)
            elif self.state == 1:
                if b == IAC:
                    out.append(IAC)
                    self.state = 0
                elif b in (DO, DONT, WILL, WONT):
                    self.cmd = b
                    self.state = 2
                elif b == SB:
                    self.state = 3
                else:
                    self.state = 0
            elif self.state == 2:
                self.negotiated = True
                if b == OPT_LINK and self.offered and self.cmd in (DO, DONT):
                    self.link_on = self.cmd == DO   # the answer to our offer: no reply
                    if self.link_on:
                        self.last_sent = 0.0        # first report right away
                elif self.cmd == DO:
                    sock.sendall(bytes([IAC, WONT, b]))
                elif self.cmd == WILL:
                    sock.sendall(bytes([IAC, DONT, b]))
                self.state = 0
            elif self.state == 3:          # inside a subnegotiation: skip to IAC SE
                if b == IAC:
                    self.state = 4
            elif self.state == 4:
                self.state = 0 if b == SE else 3
        return bytes(out)


def at(ser, cmd, wait=2.0):
    ser.write(cmd.encode() + b'\r')
    end = time.time() + wait
    buf = b''
    while time.time() < end:
        buf += ser.read(256)
        if b'OK' in buf or b'ERROR' in buf:
            break
    return buf


def hang_up(ser, guard):
    time.sleep(guard)
    ser.write(b'+++')
    time.sleep(guard)
    ser.read(4096)
    log('hang up: ' + at(ser, 'ATH', 3).decode('ascii', 'replace').strip().replace('\r\n', ' '))


def call(ser, host, port, guard, report=None):
    try:
        sock = socket.create_connection((host, port), timeout=10)
    except OSError as e:
        log(f'BBS {host}:{port} not reachable ({e}), hanging up')
        hang_up(ser, guard)
        return
    sock.settimeout(10)   # reads only happen after select says data is there; sends may wait, up to 10 s
    tn = Telnet(report)
    tail = b''
    up = down = 0
    log(f'connected to BBS {host}:{port}')
    while True:
        try:
            r, _, _ = select.select([ser.fileno(), sock], [], [], 1.0)
            if sock in r:
                data = sock.recv(4096)
                if data == b'':
                    log(f'BBS closed the connection ({down} bytes to caller, {up} from caller)')
                    sock.close()
                    hang_up(ser, guard)
                    return
                clean = tn.feed(data, sock)
                tn.after_feed(sock)
                if clean:
                    ser.write(clean)
                    down += len(clean)
            if ser.fileno() in r:
                data = ser.read(ser.in_waiting or 1)
                if data:
                    tail = (tail + data)[-32:]
                    if b'NO CARRIER' in tail:
                        log(f'NO CARRIER ({down} bytes to caller, {up} from caller)')
                        sock.close()
                        return
                    sock.sendall(data.replace(bytes([IAC]), bytes([IAC, IAC])))
                    up += len(data)
            if not r:
                tn.after_feed(sock)   # quiet line: keep the reports coming
        except OSError as e:   # the BBS reset or stopped answering: end this call, keep the bridge running
            log(f'BBS connection lost ({e}), hanging up ({down} bytes to caller, {up} from caller)')
            sock.close()
            hang_up(ser, guard)
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='/dev/ttyUSB0')
    ap.add_argument('--bbs', default='127.0.0.1:2323')
    ap.add_argument('--guard', type=float, default=1.2, help='seconds of quiet around +++ (S12=50 is 1 s)')
    ap.add_argument('--no-link', action='store_true', help="don't tell the BBS it's a radio call (option 90)")
    a = ap.parse_args()
    host, port = a.bbs.rsplit(':', 1)
    ser = serial.Serial(a.port, 115200, timeout=0.2)   # DTR/RTS left raised: no reset
    time.sleep(0.5)
    ser.read(65536)
    log(f'lfd3k bridge on {a.port}, BBS {a.bbs}: ' + at(ser, 'AT').decode('ascii', 'replace').strip().replace('\r\n', ' '))
    name = ''
    for ln in at(ser, 'AT&V', 3).decode('ascii', 'replace').splitlines():
        words = ln.split()
        if 'NAME' in words and words.index('NAME') + 1 < len(words):
            name = words[words.index('NAME') + 1]
    log(f'station {name or "unknown"}' + (', no radio reports' if a.no_link else ', radio reports on (option 90)'))
    line = b''
    while True:
        data = ser.read(256)
        if not data:
            continue
        line += data
        while b'\n' in line or b'\r' in line:
            for sep in (b'\r\n', b'\n', b'\r'):
                if sep in line:
                    one, line = line.split(sep, 1)
                    break
            text = one.decode('ascii', 'replace').strip()
            if not text:
                continue
            if text.startswith('RING'):
                log('RING, answering')
                ser.write(b'ATA\r')
            elif text.startswith('CONNECT'):
                log(text)
                line = b''
                call(ser, host, int(port), a.guard, None if a.no_link else link_payload(name, text))
            elif text in ('NO CARRIER', 'NO ANSWER', 'BUSY'):
                log(text)


if __name__ == '__main__':
    main()
