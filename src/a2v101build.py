#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Assembles src/a2v101.S (program changes of patch 1.01) into src/a2v101.json.

    a2v101build.py [--check]

a2patch.py --v101 puts the code into a new section of run.exe, whose address depends on the
run.exe. So that installing needs no GNU binutils, the code is assembled here once, at BASE, and
stored with the places that depend on its address:

- "absolute": 32-bit addresses inside the code itself (they move with it)
- "relative": rel32 operands of calls and jumps into the game (fixed targets; they move against it)
- "symbols":  offsets of the entry points the hooks of a2patch.py jump to

These places are found by assembling at BASE and at BASE + DELTA and comparing; the result is
checked against a third address. Needs GNU binutils (as, ld, objcopy, nm). Run it after every change
of a2v101.S; --check only compares src/a2v101.json with a fresh build (exit code 1 if it differs).
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "a2v101.S")
OUTPUT = os.path.join(HERE, "a2v101.json")
BASE = 0x10000000
DELTA = 0x10000
CHECK_AT = 0x1234000  # third address, with carries into the upper bytes
LINE = 32  # bytes per line of "code"


def assemble(source, address):
    """(code, {symbol: address}) of the source linked at address, with GNU as/ld."""
    for tool in ("as", "ld", "objcopy", "nm"):
        if not shutil.which(tool):
            sys.exit(f"{tool} (GNU binutils) is missing, please install it with your package manager")
    with tempfile.TemporaryDirectory() as tmp:
        obj, elf, raw = (os.path.join(tmp, n) for n in ("a.o", "a.elf", "a.bin"))
        subprocess.run(["as", "--32", "-o", obj, source], check=True)
        subprocess.run(["ld", "-m", "elf_i386", "-Ttext", hex(address), "-e", "_start", "-o", elf, obj], check=True)
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", elf, raw], check=True)
        out = subprocess.run(["nm", elf], check=True, capture_output=True, text=True).stdout
        symbols = {
            name: int(value, 16) for value, kind, name in (line.split() for line in out.splitlines()) if kind in "Tt"
        }
        with open(raw, "rb") as f:
            return f.read(), symbols


def relocate(prebuilt, address):
    """(code, {symbol: address}) of a prebuilt dict (see build) moved to address."""
    code = bytearray(bytes.fromhex("".join(prebuilt["code"])))
    delta = address - prebuilt["base"]
    for offsets, sign in ((prebuilt["absolute"], 1), (prebuilt["relative"], -1)):
        for at in offsets:
            value = struct.unpack_from("<I", code, at)[0]
            struct.pack_into("<I", code, at, (value + sign * delta) & 0xFFFFFFFF)
    symbols = {name: address + offset for name, offset in prebuilt["symbols"].items()}
    return bytes(code), symbols


def build(source=SOURCE):
    """The prebuilt dict of source (see the module docstring)."""
    code, symbols = assemble(source, BASE)
    moved, moved_symbols = assemble(source, BASE + DELTA)
    if len(moved) != len(code) or any(moved_symbols[k] - v != DELTA for k, v in symbols.items()):
        sys.exit("a2v101.S: the code changes its size or layout with its address")
    absolute, relative = [], []
    at = 0
    while at <= len(code) - 4:
        diff = (struct.unpack_from("<I", moved, at)[0] - struct.unpack_from("<I", code, at)[0]) & 0xFFFFFFFF
        if diff in (DELTA, -DELTA & 0xFFFFFFFF):
            (absolute if diff == DELTA else relative).append(at)
            at += 4
        else:
            at += 1
    prebuilt = {
        "base": BASE,
        "absolute": absolute,
        "relative": relative,
        "symbols": {name: value - BASE for name, value in sorted(symbols.items())},
        "code": [code[i : i + LINE].hex() for i in range(0, len(code), LINE)],
    }
    if relocate(prebuilt, CHECK_AT) != assemble(source, CHECK_AT):
        sys.exit("a2v101.S: relocating the code does not give what as/ld give")
    return prebuilt


def dumps(prebuilt):
    return json.dumps(prebuilt, indent=1) + "\n"


def main():
    check = sys.argv[1:] == ["--check"]
    if sys.argv[1:] and not check:
        sys.exit(__doc__)
    text = dumps(build())
    if check:
        with open(OUTPUT) as f:
            if f.read() != text:
                sys.exit(f"{OUTPUT} is out of date, run src/a2v101build.py")
        print(f"{OUTPUT} is up to date")
        return
    with open(OUTPUT, "w") as f:
        f.write(text)
    print(f"{OUTPUT} written")


if __name__ == "__main__":
    main()
