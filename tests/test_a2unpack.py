"""a2unpack.py on a synthetic packed file: no game files needed."""

import struct
import sys

import pytest

import a2unpack as u


def lzw_encode(data):
    """The stream a2unpack.lzw decodes to data (codes of 9 to 12 bits, LSB first, clear when full)."""
    out, acc, nbits = bytearray(), 0, 0
    width, table, next_code = 9, {}, 0x102

    def emit(code):
        nonlocal acc, nbits
        acc |= code << nbits
        nbits += width
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8

    emit(0x100)
    word = b""
    for b in data:
        longer = word + bytes([b])
        if len(longer) == 1 or longer in table:
            word = longer
            continue
        emit(table[word] if len(word) > 1 else word[0])
        if next_code < 0x1000:
            table[longer] = next_code
            next_code += 1
            if next_code - 1 == 1 << width and width < 12:
                width += 1
        else:  # table full: start again
            emit(0x100)
            width, table, next_code = 9, {}, 0x102
        word = bytes([b])
    if word:
        emit(table[word] if len(word) > 1 else word[0])
    emit(0x101)
    if nbits:
        out.append(acc & 0xFF)
    return bytes(out)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"a",
        b"abababababababab",
        bytes(range(256)) * 40,
        b"\x90" * 5000,
        bytes((i * 7919) & 0xFF for i in range(20000)),
    ],
)
def test_lzw_roundtrip(data):
    assert u.lzw(lzw_encode(data), len(data) + 10) == data


def test_lzw_stops_at_the_limit():
    data = bytes(range(200)) * 10
    assert u.lzw(lzw_encode(data), 100) == data[:100]


def rdata_with_imports():
    """.rdata with two import descriptors at IMPORTS (KERNEL32: 2 functions, USER32: 1)."""
    base, size = u.SECTIONS[1][1], u.SECTIONS[1][2]
    rdata = bytearray(size)
    names = 0x100  # hint/name entries and DLL names at base + 0x100
    lookup = 0x80  # lookup and address tables at base + 0x80 / base + 0x0

    def name(text):
        nonlocal names
        at = names
        rdata[at : at + len(text) + 1] = text + b"\0"
        names += len(text) + 2
        return base + at

    entries = [(name(b"KERNEL32.dll"), [b"\0\0GetVersion", b"\0\0ExitProcess"]), (name(b"USER32.dll"), [b"\0\0Beep"])]
    slot = 0
    for i, (dll, functions) in enumerate(entries):
        first = slot
        for f in functions:
            rva = name(f)
            struct.pack_into("<I", rdata, slot * 4, rva)
            struct.pack_into("<I", rdata, lookup + slot * 4, rva)
            slot += 1
        slot += 1  # terminator
        struct.pack_into(
            "<5I", rdata, u.IMPORTS - base + 20 * i, base + lookup + first * 4, 0, 0, dll, base + first * 4
        )
    return bytes(rdata), slot * 4


def packed_file():
    """A file laid out like the packed run.exe: headers, the three streams, a loader section."""
    out = bytearray(u.HEADERS)
    out[:2] = b"MZ"
    struct.pack_into("<I", out, 0x3C, 0x80)
    out[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", out, 0x84, 0x14C, 4)  # i386, 4 sections
    struct.pack_into("<H", out, 0x94, 0xE0)  # size of the optional header
    opt = 0x98
    struct.pack_into("<H", out, opt, 0x10B)
    struct.pack_into("<II", out, opt + 96 + 8, 0x8B7076, 0x7D)  # loader's imports
    rdata, iat_size = rdata_with_imports()
    text = bytes((i * 31) & 0xFF for i in range(u.SECTIONS[0][2]))
    data = bytes(i & 0x3F for i in range(0x52C00))  # the stream ends before the zeros
    bodies = [text, rdata, data]
    for (name, rva, vsize, raw, rsize, add, flags), body in zip(u.SECTIONS, bodies):
        stream = lzw_encode(bytes((b + add) & 0xFF for b in body))
        assert len(stream) <= rsize
        out += bytes(raw - len(out)) + stream + bytes(rsize - len(stream))
    out += b"loader" * 100
    return bytes(out), bodies, iat_size


def test_unpack():
    packed, bodies, iat_size = packed_file()
    result = u.unpack(packed)
    pe = struct.unpack_from("<I", result, 0x3C)[0]
    opt = pe + 24
    table = opt + struct.unpack_from("<H", result, pe + 20)[0]
    assert struct.unpack_from("<H", result, pe + 6)[0] == 3
    assert struct.unpack_from("<I", result, opt + 16)[0] == u.ENTRY
    assert struct.unpack_from("<I", result, opt + 56)[0] == u.LOADER_RVA
    assert struct.unpack_from("<II", result, opt + 96 + 8) == (u.IMPORTS, 3 * 20)
    assert struct.unpack_from("<II", result, opt + 96 + 12 * 8) == (u.SECTIONS[1][1], iat_size)
    assert struct.unpack_from("<II", result, opt + 96 + 2 * 8) == (0, 0)
    assert result[table + 3 * 40 : table + 4 * 40] == bytes(40)  # loader section gone
    for i, ((name, rva, vsize, _, _, _, flags), body) in enumerate(zip(u.SECTIONS, bodies)):
        sname, svsize, srva, rsize, raw, *_, sflags = struct.unpack_from("<8sIIIIIIHHI", result, table + 40 * i)
        assert (sname.rstrip(b"\0"), svsize, srva, sflags) == (name, vsize, rva, flags)
        assert raw % u.FILE_ALIGN == 0 and rsize % u.FILE_ALIGN == 0 and rsize >= len(body)
        assert result[raw : raw + len(body)] == body
    assert len(result) == raw + rsize


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2unpack.py", *args])
    u.main()


def test_main(tmp_path, monkeypatch, capsys):
    packed, _, _ = packed_file()
    exe = tmp_path / "run.exe"
    exe.write_bytes(packed)
    monkeypatch.setattr(u, "PACKED", u.sha(packed))
    monkeypatch.setattr(u, "RESULT", u.sha(u.unpack(packed)))
    run_main(monkeypatch, str(exe))
    assert u.sha(exe.read_bytes()) == u.RESULT
    assert (tmp_path / "run.exe.vor-entpacken").read_bytes() == packed
    assert "unpacked" in capsys.readouterr().out
    run_main(monkeypatch, str(exe))
    assert "already unpacked" in capsys.readouterr().out
    exe.write_bytes(exe.read_bytes() + b"patched later")  # e.g. by a2patch.py: the backup vouches for it
    run_main(monkeypatch, str(exe))
    assert "already unpacked" in capsys.readouterr().out


def test_main_unknown_file(tmp_path, monkeypatch):
    exe = tmp_path / "run.exe"
    exe.write_bytes(b"MZ something else")
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, str(exe))
    assert e.value.code == 1 and exe.read_bytes() == b"MZ something else"
    assert not (tmp_path / "run.exe.vor-entpacken").exists()


def test_main_unexpected_result(tmp_path, monkeypatch):
    packed, _, _ = packed_file()
    exe = tmp_path / "run.exe"
    exe.write_bytes(packed)
    monkeypatch.setattr(u, "PACKED", u.sha(packed))
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, str(exe))
    assert e.value.code == 1 and exe.read_bytes() == packed


def test_main_usage(monkeypatch):
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch)
    assert "a2unpack.py" in str(e.value.code)
