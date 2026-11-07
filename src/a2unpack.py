#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Takes run.exe of the 2007 CD release out of its PECRYPT32 shell, without running it.

    a2unpack.py <path to run.exe>

The 2007 CD release by Kalypso (Inno Setup ANSTOSS_2_GOLD/Setup.exe on the "ANSTOSS 2007" DVD) ships
run.exe in a PECRYPT32 shell: the three sections of the program are compressed, a loader appended
as a fourth section unpacks them in memory, fills in the imports and jumps to the program. GOG's
run.exe is the same program, taken out of that shell by GOG. This script does the same from the
file on disk, with own code and without running anything:

- The sections are LZW streams (codes of 9 to 12 bits, least significant bit first, 0x100 clears
  the table, 0x101 ends the stream). Before compression, 0x78 was added to every byte of .text and
  .data (not of .rdata); the loader subtracts it again.
- The program's own import table (RVA 0x2aa740 in .rdata) is unchanged inside the stream, so the
  result gets a normal import directory instead of the loader's three imports.
- The result has the three sections at their addresses, the original entry point 0x65cf50 and no
  loader. Code and data are byte for byte what the loader leaves in memory before it jumps to the
  program (checked in an x86 emulator), except that the import slots hold the import names, as in
  any program on disk, instead of resolved addresses.

The program inside is not changed; the CD and integrity checks of the 2007 release stay as they are
(src/a2patch.py --disc-check and its integrity values deal with them afterwards). Input and result
are checked against their SHA-256; on a mismatch nothing is written and the exit code is 1. The
original is kept as run.exe.vor-entpacken.
"""

import hashlib
import os
import shutil
import struct
import sys

BACKUP_SUFFIX = ".vor-entpacken"
# fmt: off
PACKED = "836aef556e83ad61421e9b7c545ecbc151412645843002ebf6067464e26bf7f7"   # 2007 CD release
RESULT = "414f3ea2f77e042d96b561e927fa5477af6c7d2aa34d4910eeef4960ba045f9f"   # this script
# Sections of the program: name, RVA, size in memory, offset and size of the stream in the packed
# file, value added to each byte before compression, characteristics
SECTIONS = (
    (b".text", 0x1000, 0x27AD6A, 0x400, 0x1B6A00, 0x78, 0xE0000020),
    (b".rdata", 0x27C000, 0x30A1C, 0x1B6E00, 0x11A00, 0x00, 0xC0000040),
    (b".data", 0x2AD000, 0x607ABC, 0x1C8800, 0x10A00, 0x78, 0xC0000040),
)
# fmt: on
ENTRY = 0x25CF50  # RVA of the program's entry point
IMPORTS = 0x2AA740  # RVA of the program's import descriptors
LOADER_RVA = 0x8B5000  # where the loader section starts; the image ends there without it
FILE_ALIGN, HEADERS = 0x200, 0x400


def sha(data):
    return hashlib.sha256(data).hexdigest()


def lzw(stream, limit):
    """The bytes the LZW stream decodes to (at most limit)."""
    clear, end = 0x100, 0x101
    prefix, suffix = [0] * 0x1000, list(range(256)) + [0] * (0x1000 - 256)
    out = bytearray()
    data = stream + b"\0\0\0"
    bits, width, next_code, old = 0, 9, 0x102, None
    while len(out) < limit:
        at = bits >> 3
        code = ((data[at] | data[at + 1] << 8 | data[at + 2] << 16) >> (bits & 7)) & ((1 << width) - 1)
        bits += width
        if bits > len(stream) * 8 or code == end:
            break
        if code == clear:
            width, next_code, old = 9, 0x102, None
            continue
        if old is None:
            out.append(code)
            old = code
            continue
        c = code if code < next_code else old
        chunk = bytearray()
        while c > 0xFF:
            chunk.append(suffix[c])
            c = prefix[c]
        chunk.append(c)
        chunk.reverse()
        if code >= next_code:  # the code being defined: old string + its own first byte
            chunk.append(chunk[0])
        out += chunk
        if next_code < 0x1000:
            prefix[next_code], suffix[next_code] = old, chunk[0]
            next_code += 1
            if next_code == 1 << width and width < 12:
                width += 1
        old = code
    return bytes(out[:limit])


def import_extent(rdata):
    """(size of the import directory, (RVA, size) of the import address tables) from .rdata."""
    base = SECTIONS[1][1]
    count, first, last = 0, None, 0
    while True:
        lookup, _, _, name, thunks = struct.unpack_from("<5I", rdata, IMPORTS - base + 20 * count)
        if not (lookup or name or thunks):
            break
        count += 1
        end = thunks
        while struct.unpack_from("<I", rdata, end - base)[0]:
            end += 4
        first = thunks if first is None else min(first, thunks)
        last = max(last, end + 4)
    return 20 * (count + 1), (first, last - first)


def align(n, to):
    return (n + to - 1) // to * to


def unpack(packed):
    """The unpacked program as a PE file."""
    bodies = []
    for name, rva, vsize, raw, rsize, add, _ in SECTIONS:
        data = lzw(packed[raw : raw + rsize], vsize)
        if add:
            data = bytes((b - add) & 0xFF for b in data)
        bodies.append(data)  # .data: the stream ends before the zeros at its end, those stay virtual
    out = bytearray(packed[:HEADERS])
    pe = struct.unpack_from("<I", out, 0x3C)[0]
    opt = pe + 24
    table = opt + struct.unpack_from("<H", out, pe + 20)[0]
    nsec = struct.unpack_from("<H", out, pe + 6)[0]
    out[table : table + 40 * nsec] = bytes(40 * nsec)
    offset = HEADERS
    raw_sizes = []
    for i, ((name, rva, vsize, _, _, _, flags), body) in enumerate(zip(SECTIONS, bodies)):
        size = align(len(body), FILE_ALIGN)
        struct.pack_into("<8sIIIIIIHHI", out, table + 40 * i, name, vsize, rva, size, offset, 0, 0, 0, 0, flags)
        raw_sizes.append(size)
        offset += size
    struct.pack_into("<H", out, pe + 6, len(SECTIONS))
    struct.pack_into("<III", out, opt + 4, raw_sizes[0], raw_sizes[1] + raw_sizes[2], 0)  # sizes of code/data
    struct.pack_into("<I", out, opt + 16, ENTRY)
    struct.pack_into("<I", out, opt + 56, LOADER_RVA)  # SizeOfImage
    struct.pack_into("<I", out, opt + 64, 0)  # checksum
    directory_size, iat = import_extent(bodies[1])
    dirs = opt + 96
    out[dirs : dirs + 16 * 8] = bytes(16 * 8)
    struct.pack_into("<II", out, dirs + 1 * 8, IMPORTS, directory_size)
    struct.pack_into("<II", out, dirs + 12 * 8, *iat)
    for body, size in zip(bodies, raw_sizes):
        out += body + bytes(size - len(body))
    return bytes(out)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    exe = sys.argv[1]
    with open(exe, "rb") as f:
        data = f.read()
    digest = sha(data)
    backup = exe + BACKUP_SUFFIX
    if digest == RESULT or (digest != PACKED and os.path.exists(backup) and sha(open(backup, "rb").read()) == PACKED):
        print(f"{exe}: already unpacked")
        return
    if digest != PACKED:
        print(f"{exe}: not the run.exe of the 2007 CD release (SHA-256 {digest}), nothing changed", file=sys.stderr)
        sys.exit(1)
    result = unpack(data)
    if sha(result) != RESULT:
        print(f"{exe}: unexpected result (SHA-256 {sha(result)}), nothing changed", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(backup):
        shutil.copy2(exe, backup)
    tmp = exe + ".tmp"
    with open(tmp, "wb") as f:
        f.write(result)
    shutil.copymode(exe, tmp)
    os.replace(tmp, exe)
    print(f"{exe}: unpacked, original kept as {os.path.basename(backup)}")


if __name__ == "__main__":
    main()
