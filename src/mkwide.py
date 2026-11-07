#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Builds a bitmap font with double-width characters from MS Sans Serif (sserife.fon).

Windows scales bitmap fonts by integer factors only. When Anstoss 2 requests 20 px height
with 12 px width for the club names, Windows doubles the characters horizontally. Wine
only widens the gaps instead. This font already contains double-width characters, so
Wine draws it at natural size exactly as Windows does.

  mkwide.py sserife.fon <prefix>   creates <prefix>20.fnt and <prefix>24.fnt
"""

import struct
import sys

FACE = "A2 Sans Serif Wide"
HEIGHTS = (20, 24)


def fnt_resources(data):
    ne = struct.unpack_from("<I", data, 0x3C)[0]
    rt = ne + struct.unpack_from("<H", data, ne + 0x24)[0]
    shift = struct.unpack_from("<H", data, rt)[0]
    p = rt + 2
    while True:
        typ, cnt = struct.unpack_from("<HH", data, p)
        p += 8
        if typ == 0:
            return
        for _ in range(cnt):
            off, ln = struct.unpack_from("<HH", data, p)
            p += 12
            if typ == 0x8008:
                yield data[off << shift : (off << shift) + (ln << shift)]


def parse_fnt(f):
    ver = struct.unpack_from("<H", f, 0)[0]
    (ascent,) = struct.unpack_from("<H", f, 74)
    (weight,) = struct.unpack_from("<H", f, 83)
    charset = f[85]
    (height,) = struct.unpack_from("<H", f, 88)
    first, last, default = f[95], f[96], f[97]
    glyphs = {}
    tbl, esz = (148, 6) if ver == 0x300 else (118, 4)
    for i, ch in enumerate(range(first, last + 2)):
        if ch > 255:
            break
        if ver == 0x300:
            w, off = struct.unpack_from("<HI", f, tbl + i * esz)
        else:
            w, off = struct.unpack_from("<HH", f, tbl + i * esz)
        cols = (w + 7) // 8
        rows = []
        for y in range(height):
            bits = 0
            for c in range(cols):
                bits = (bits << 8) | f[off + c * height + y]
            rows.append((bits, cols * 8))
        glyphs[ch] = (w, rows)
    return dict(
        ver=ver, ascent=ascent, weight=weight, charset=charset, height=height, default=first + default, glyphs=glyphs
    )


def widen(bits, nbits, w):
    out = 0
    for x in range(w):
        b = (bits >> (nbits - 1 - x)) & 1
        out = (out << 2) | (b * 3)
    return out  # 2*w bits


def build_fnt(raw, fn):
    """FNT version 2 with double-width characters, header taken from the original."""
    h = fn["height"]
    hdr = bytearray(raw[:118])
    struct.pack_into("<H", hdr, 0, 0x200)
    chars = sorted(fn["glyphs"].items())
    face = FACE.encode("ascii") + b"\0"
    tbl_len = 4 * len(chars)
    bits_off = 118 + tbl_len
    table = bytearray()
    bits = bytearray()
    maxw = 0
    for ch, (w, rows) in chars:
        w2 = 2 * w
        cols = (w2 + 7) // 8
        maxw = max(maxw, w2)
        table += struct.pack("<HH", w2, bits_off + len(bits))
        mat = [(widen(b, nb, w) << (cols * 8 - w2)) for b, nb in rows]
        for c in range(cols):
            for y in range(h):
                bits.append((mat[y] >> (8 * (cols - 1 - c))) & 0xFF)
    face_off = bits_off + len(bits)
    total = face_off + len(face)
    if total > 0xFFFF:
        sys.exit("font too large for FNT 2.0")
    struct.pack_into("<I", hdr, 2, total)
    struct.pack_into("<H", hdr, 86, 0)  # dfPixWidth: proportional
    avg = struct.unpack_from("<H", raw, 91)[0]
    struct.pack_into("<HH", hdr, 91, avg * 2, maxw)  # dfAvgWidth, dfMaxWidth
    struct.pack_into("<H", hdr, 99, 0)  # dfWidthBytes (v1 raster fonts only)
    struct.pack_into("<I", hdr, 105, face_off)  # dfFace
    struct.pack_into("<I", hdr, 113, bits_off)  # dfBitsOffset
    return bytes(hdr) + bytes(table) + bytes(bits) + face


def main(src, dst):
    out = []
    for raw in fnt_resources(open(src, "rb").read()):
        fn = parse_fnt(raw)
        if fn["height"] in HEIGHTS and fn["weight"] < 600:
            name = f"{dst}{fn['height']}.fnt"
            open(name, "wb").write(build_fnt(raw, fn))
            out.append(name)
    if not out:
        sys.exit("no matching sizes found")
    print(" ".join(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
