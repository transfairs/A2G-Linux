"""mkwide.py: double-width bitmap font from a synthetic FNT 2.0 font."""

import struct

import mkwide

HEIGHT = 2
# char: (width, rows as bit strings)
GLYPHS = {65: (3, ["101", "010"]), 66: (9, ["100000001", "011111110"]), 67: (0, ["", ""])}


def fnt():
    """FNT 2.0 with characters 65..66 and the sentinel 67, as in a .fon file."""
    first, last = 65, 66
    hdr = bytearray(118)
    struct.pack_into("<H", hdr, 0, 0x200)
    struct.pack_into("<H", hdr, 74, 2)  # ascent
    struct.pack_into("<H", hdr, 83, 400)  # weight
    hdr[85] = 0  # charset
    struct.pack_into("<H", hdr, 88, HEIGHT)
    struct.pack_into("<H", hdr, 91, 5)  # average width
    hdr[95], hdr[96], hdr[97] = first, last, 1
    table, bits = bytearray(), bytearray()
    bits_off = 118 + 4 * len(GLYPHS)
    for ch in range(first, last + 2):
        w, rows = GLYPHS[ch]
        cols = (w + 7) // 8
        table += struct.pack("<HH", w, bits_off + len(bits))
        values = [int(r.ljust(cols * 8, "0"), 2) if cols else 0 for r in rows]
        for c in range(cols):
            for v in values:
                bits.append((v >> (8 * (cols - 1 - c))) & 0xFF)
    return bytes(hdr) + bytes(table) + bytes(bits)


def test_widen_doubles_each_pixel():
    assert mkwide.widen(0b101, 3, 3) == 0b110011
    assert mkwide.widen(0b1000_0000, 8, 2) == 0b1100


def test_parse_fnt():
    fn = mkwide.parse_fnt(fnt())
    assert (fn["ver"], fn["height"], fn["weight"], fn["ascent"], fn["default"]) == (0x200, HEIGHT, 400, 2, 66)
    assert fn["glyphs"][65] == (3, [(0b10100000, 8), (0b01000000, 8)])
    assert fn["glyphs"][66][0] == 9


def test_build_fnt_has_double_width_characters():
    raw = fnt()
    out = mkwide.build_fnt(raw, mkwide.parse_fnt(raw))
    wide = mkwide.parse_fnt(out)
    assert struct.unpack_from("<I", out, 2)[0] == len(out)
    assert out[struct.unpack_from("<I", out, 105)[0] :] == mkwide.FACE.encode("ascii") + b"\0"
    assert struct.unpack_from("<HH", out, 91) == (10, 18)  # average and maximum width
    for ch, (w, rows) in GLYPHS.items():
        w2, wide_rows = wide["glyphs"][ch]
        assert w2 == 2 * w
        for row, (bits, nbits) in zip(rows, wide_rows):
            expect = "".join(c * 2 for c in row)
            assert format(bits, f"0{nbits}b")[: 2 * w] == expect
