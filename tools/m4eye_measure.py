#!/usr/bin/env python3
"""Measure the M4 eye on the board over the serial console: fps (`lcd prof`,
`eyes`), heap, render-only bench, for each table/texture placement.
Opening the port resets the board. Leaves the eyes on style m4 (not saved).

  ~/.platformio/penv/bin/python tools/m4eye_measure.py [/dev/cu.usbserial-10]
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-10"


def main():
    s = serial.Serial(PORT, 115200, timeout=0.2)
    t0 = time.time()

    def read_for(sec):
        end = time.time() + sec
        out = b""
        while time.time() < end:
            out += s.read(4096)
        text = out.decode(errors="replace")
        for line in text.splitlines():
            if line.strip():
                print(f"[{time.time() - t0:6.1f}] {line}")
        return text

    def cmd(c, wait=1.0):
        print(f"\n>>> {c}")
        s.write((c + "\n").encode())
        return read_for(wait)

    read_for(14)  # boot, WiFi join
    cmd("heap")
    cmd("config")
    for style in ("fire", "default"):
        cmd(f"art {style}", 3)
        cmd("lcd prof", 4)
        cmd("lcd prof")
        cmd("eyes")
    cmd("art m4", 3)
    for tables, tex in (("int", "psram"), ("psram", "psram"), ("int", "flash"), ("psram", "flash"), ("int", "psram")):
        cmd(f"m4 mem tables {tables} tex {tex}", 3)
        cmd("lcd prof", 5)
        cmd("lcd prof")
        cmd("eyes")
        cmd("heap")
        cmd("m4 bench 30", 6)
    cmd('m4 set {"slitPupilRadius":36}', 3)
    cmd("lcd prof", 5)
    cmd("lcd prof")
    cmd("m4 set {\"slitPupilRadius\":0}", 2)
    # Phase 2: every eye set on LittleFS, plus runtime parameter changes.
    cmd("m4 list")
    for eye in ("snake_green", "doom-red", "doom-spiral", "skull", "hazel"):
        cmd(f"m4 eye {eye}", 4)
        cmd("lcd prof", 5)
        cmd("lcd prof")
        cmd("heap")
    cmd('m4 set {"irisTint":[255,120,120],"lids":"hazel-symmetrical","irisRadius":50,"blinkRate":20}', 4)
    cmd("lcd prof", 5)
    cmd("lcd prof")
    cmd("m4 reset", 3)
    cmd("m4")
    cmd("config")
    cmd("heap")


if __name__ == "__main__":
    main()
