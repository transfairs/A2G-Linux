"""mkwide.py: double-width bitmap font from a synthetic FNT 2.0 font."""

import os
import runpy
import struct
import sys

import pytest

import mkwide

HEIGHT = 2
# char: (width, rows as bit strings)
GLYPHS = {65: (3, ["101", "010"]), 66: (9, ["100000001", "011111110"]), 67: (0, ["", ""])}


def fnt(height=HEIGHT, weight=400):
    """FNT 2.0 with characters 65..66 and the sentinel 67, as in a .fon file."""
    first, last = 65, 66
    hdr = bytearray(118)
    struct.pack_into("<H", hdr, 0, 0x200)
    struct.pack_into("<H", hdr, 74, 2)  # ascent
    struct.pack_into("<H", hdr, 83, weight)
    hdr[85] = 0  # charset
    struct.pack_into("<H", hdr, 88, height)
    struct.pack_into("<H", hdr, 91, 5)  # average width
    hdr[95], hdr[96], hdr[97] = first, last, 1
    table, bits = bytearray(), bytearray()
    bits_off = 118 + 4 * len(GLYPHS)
    for ch in range(first, last + 2):
        w, rows = GLYPHS[ch]
        cols = (w + 7) // 8
        table += struct.pack("<HH", w, bits_off + len(bits))
        # taller fonts repeat the two pattern rows
        values = [int(rows[y % HEIGHT].ljust(cols * 8, "0"), 2) if cols else 0 for y in range(height)]
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


def fnt3():
    """FNT 3.0 with characters 254..255: the sentinel would be 256, which does not exist."""
    first, last = 254, 255
    hdr = bytearray(148)
    struct.pack_into("<H", hdr, 0, 0x300)
    struct.pack_into("<H", hdr, 83, 400)
    struct.pack_into("<H", hdr, 88, 1)
    hdr[95], hdr[96], hdr[97] = first, last, 0
    bits_off = 148 + 6 * 2
    table = struct.pack("<HI", 8, bits_off) + struct.pack("<HI", 4, bits_off + 1)
    return bytes(hdr) + table + bytes([0b10000001, 0b11110000])


def fon(path, resources, shift=4):
    """NE file (.fon) with the given (type, data) resources, terminated by type 0."""
    ne = 0x40
    rt = ne + 0x40
    table = struct.pack("<H", shift)
    data_off = rt + 2 + 20 * len(resources) + 8
    data_off = -(-data_off >> shift) << shift
    blobs = bytearray()
    for typ, blob in resources:
        padded = blob + bytes(-len(blob) % (1 << shift))
        off = (data_off + len(blobs)) >> shift
        table += struct.pack("<HHI", typ, 1, 0) + struct.pack("<HHHHI", off, len(padded) >> shift, 0, 0, 0)
        blobs += padded
    table += bytes(8)  # type 0 ends the table
    head = bytearray(rt)
    struct.pack_into("<I", head, 0x3C, ne)
    struct.pack_into("<H", head, ne + 0x24, rt - ne)
    out = bytes(head) + table
    out += bytes(data_off - len(out)) + bytes(blobs)
    path.write_bytes(out)
    return str(path)


def test_fnt_resources_yields_only_fonts(tmp_path):
    fonts = [fnt(), fnt(height=3)]
    resources = [(0x8007, b"fontdir"), (0x8008, fonts[0]), (0x8008, fonts[1])]
    data = open(fon(tmp_path / "x.fon", resources), "rb").read()
    found = list(mkwide.fnt_resources(data))
    assert len(found) == 2
    for raw, expect in zip(found, fonts):
        # the resources are padded to the alignment of the file
        assert raw[: len(expect)] == expect
        assert not raw[len(expect) :].strip(b"\0")


def test_parse_fnt_version_3_stops_at_character_255():
    fn = mkwide.parse_fnt(fnt3())
    assert fn["ver"] == 0x300
    assert sorted(fn["glyphs"]) == [254, 255]
    assert fn["glyphs"][254] == (8, [(0b10000001, 8)])
    assert fn["glyphs"][255] == (4, [(0b11110000, 8)])


def test_build_fnt_too_large():
    rows = [(0, 1000)] * 300
    fn = dict(height=300, glyphs={65: (1000, rows)})
    with pytest.raises(SystemExit, match="font too large for FNT 2.0"):
        mkwide.build_fnt(bytes(118), fn)


def test_main_writes_the_regular_20_and_24_px_fonts(tmp_path, capsys):
    resources = [(0x8008, fnt(height=h, weight=w)) for h, w in ((13, 400), (20, 700), (20, 400), (24, 400))]
    src = fon(tmp_path / "sserife.fon", resources)
    mkwide.main(src, str(tmp_path / "wide"))
    names = [str(tmp_path / "wide20.fnt"), str(tmp_path / "wide24.fnt")]
    assert capsys.readouterr().out.split() == names
    assert sorted(os.listdir(tmp_path)) == ["sserife.fon", "wide20.fnt", "wide24.fnt"]
    for name, h in zip(names, (20, 24)):
        wide = mkwide.parse_fnt(open(name, "rb").read())
        assert (wide["height"], wide["weight"]) == (h, 400)
        assert wide["glyphs"][65][0] == 6


def test_main_without_matching_sizes(tmp_path):
    src = fon(tmp_path / "sserife.fon", [(0x8008, fnt(height=13)), (0x8008, fnt(height=20, weight=700))])
    with pytest.raises(SystemExit, match="no matching sizes found"):
        mkwide.main(src, str(tmp_path / "wide"))
    assert os.listdir(tmp_path) == ["sserife.fon"]


def test_script_entry_point(tmp_path, monkeypatch, capsys):
    src = fon(tmp_path / "sserife.fon", [(0x8008, fnt(height=20))])
    monkeypatch.setattr(sys, "argv", ["mkwide.py", src, str(tmp_path / "w")])
    runpy.run_path(mkwide.__file__, run_name="__main__")
    assert capsys.readouterr().out.strip() == str(tmp_path / "w20.fnt")
