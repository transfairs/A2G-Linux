"""a2patch.py on synthetic images: no game files needed."""

import struct
import sys
import zlib

import pytest

import a2patch as p

# --- helpers -------------------------------------------------------------------------------


def filler(n):
    """Bytes that match none of the patterns."""
    return bytes([0xCC]) * n


def goal_image(register=0, short=False, patched=False, home=p.JLE, away=p.JLE):
    if short:
        assert register == 0
        original = p.limit_originals(0)[1]
    else:
        original = p.limit_originals(register)[0]
    limit = p.limit_patched(register, len(original)) if patched else original
    return (
        filler(16)
        + p.LIMIT_PATTERN
        + bytes([0xC0 + register])
        + limit
        + filler(16)
        + p.HOME_BRAKE_PATTERN
        + bytes([home])
        + filler(16)
        + p.AWAY_BRAKE_PATTERN
        + bytes([away])
        + filler(16)
    )


def sound_block(pointer=0x6000, patched=False, guid_delta=p.GUID_BEFORE_POINTER, pointer2=None):
    guid = p.SOUND_PATCHED if patched else bytes([0x68]) + struct.pack("<i", pointer - guid_delta)
    return (
        bytes([0x56, 0x68])
        + struct.pack("<i", pointer)
        + guid
        + bytes([0xE8, 1, 2, 3, 4, 0x85, 0xC0, 0x74, 0x15, 0xE8, 1, 2, 3, 4, 0x89, 0x35])
        + struct.pack("<i", pointer if pointer2 is None else pointer2)
    )


def disc_image(count=p.DISC_CHECKS, patched=0, target=0x100, sub=False):
    """count calls of one routine at target, alternating the eax and the "mov r32,eax" form;
    unpatched places hold GOG's NOPs or, with sub, the subtraction of the 2007 CD."""
    image = bytearray(filler(0x200))
    modrms = [None, 0xF0, 0xD8, 0xF8]
    for i in range(count):
        at = len(image)
        modrm = modrms[i % len(modrms)]
        call = bytes([0xE8]) + struct.pack("<i", target - (at + 5))
        mov = bytes([0x8B, modrm]) if modrm else b""
        register, length = (p.MOV_FROM_EAX[modrm], 6) if modrm else (0, 5)
        if i < patched:
            rest = bytes([0x31, 0xC0 + register * 9]) + bytes([p.NOP] * (length - 2))
        elif sub:  # sub r32,0x2ad37160 / sub eax,0x2ad37160
            rest = (bytes([0x81, 0xE8 + register]) if modrm else bytes([0x2D])) + struct.pack("<I", 0x2AD37160)
        else:
            rest = bytes([p.NOP] * length)
        image += call + mov + p.ADD_ESP_4 + rest + filler(8)
    return bytes(image)


TEXT_RAW = 0x400
TEXT_VA = 0x1000
TEXT_SIZE = 0x1D0000  # covers all V101_HOOKS addresses


def pe_image(hooks=True, stubs=0):
    """A minimal PE file with one section that holds the V101_HOOKS places and code self-checks."""
    image = bytearray(TEXT_RAW + TEXT_SIZE)
    pe, optsize = 0x80, 0xE0
    struct.pack_into("<I", image, 0x3C, pe)
    image[pe : pe + 4] = b"PE\0\0"
    struct.pack_into("<H", image, pe + 6, 1)
    struct.pack_into("<H", image, pe + 20, optsize)
    struct.pack_into("<I", image, pe + 24 + 56, TEXT_VA + TEXT_SIZE)  # SizeOfImage
    struct.pack_into("<8sIIII", image, pe + 24 + optsize, b".text\0\0\0", TEXT_SIZE, TEXT_VA, TEXT_SIZE, TEXT_RAW)
    if hooks:
        for va, original, _, _ in p.V101_HOOKS:
            at = TEXT_RAW + va - 0x400000 - TEXT_VA
            want = bytes.fromhex(original.replace(" ", ""))
            image[at : at + len(want)] = want
    for i in range(stubs):
        desc = TEXT_RAW + 0x1000 + i * 0x200
        struct.pack_into("<III", image, desc, 0xDEADBEEF, 0, 0x40)
        image[desc + 0xC : desc + 0xC + len(p.SELF_CHECK_STUB)] = p.SELF_CHECK_STUB
    return image


# --- find_all / after ------------------------------------------------------------------------


def test_find_all_wildcards_and_overlaps():
    assert p.find_all(b"\x01\x02\x01\x02\x01", [0x01, None, 0x01]) == [0, 2]
    assert p.find_all(b"\x0a\x2e", [0x0A, 0x2E]) == [0]  # regex specials are escaped
    assert p.find_all(b"abc", [0x7A]) == []


def test_after_needs_exactly_one_occurrence():
    assert p.after(b"xxABxx", b"AB") == 4
    assert p.after(b"ABAB", b"AB") is None
    assert p.after(b"xx", b"AB") is None


# --- goal limits ---------------------------------------------------------------------------


@pytest.mark.parametrize("register", [0, 1, 2, 3])
def test_goal_sites_original_and_patched(register):
    sites = p.goal_sites(goal_image(register))
    assert sites is not None and len(sites) == 3
    assert not any(s[3] for s in sites)
    image = bytearray(goal_image(register))
    for at, _, patched, _ in sites:
        image[at : at + len(patched)] = patched
    again = p.goal_sites(bytes(image))
    assert all(s[3] for s in again)
    assert bytes(image) == goal_image(register, patched=True, home=p.JMP, away=p.JMP)
    limit_at = again[0][0]
    assert image[limit_at] == 0xB8 + register and struct.unpack_from("<i", image, limit_at + 1)[0] == p.MAX_GOALS


def test_goal_sites_short_form_with_eax():
    sites = p.goal_sites(goal_image(0, short=True))
    assert sites[0][1] == bytes([0x48, 0x24, 0xFC, 0x83, 0xC0, 0x0A])
    assert len(sites[0][2]) == len(sites[0][1])


def test_goal_sites_unknown_exe():
    assert p.goal_sites(filler(100)) is None
    image = goal_image()
    assert p.goal_sites(image + image) is None  # every pattern twice
    bad_register = image.replace(p.LIMIT_PATTERN + b"\xc0", p.LIMIT_PATTERN + b"\xc4")
    assert p.goal_sites(bad_register) is None
    assert p.goal_sites(goal_image(home=0x90)) is None
    broken = image.replace(p.limit_originals(0)[0], b"\x90" * 7)
    assert p.goal_sites(broken) is None


def test_goal_sites_pattern_at_the_end():
    assert p.goal_sites(filler(4) + p.LIMIT_PATTERN + b"\xc0") is None
    image = goal_image()
    cut = image[: image.index(p.AWAY_BRAKE_PATTERN) + len(p.AWAY_BRAKE_PATTERN)]
    assert p.goal_sites(cut) is None


# --- sound ---------------------------------------------------------------------------------


def test_sound_sites_original_and_patched():
    image = filler(10) + sound_block() + filler(10)
    sites = p.sound_sites(image)
    assert sites == [(10 + p.GUID_AT, bytes([0x68]) + struct.pack("<i", 0x6000 - 0x18), p.SOUND_PATCHED, False)]
    patched = bytearray(image)
    at, _, new, _ = sites[0]
    patched[at : at + len(new)] = new
    assert bytes(patched) == filler(10) + sound_block(patched=True) + filler(10)
    assert p.sound_sites(bytes(patched))[0][3] is True


def test_sound_sites_unknown_exe():
    assert p.sound_sites(filler(50)) is None
    assert p.sound_sites(sound_block() + sound_block()) is None
    assert p.sound_sites(sound_block(pointer2=0x7000)) is None
    assert p.sound_sites(sound_block(guid_delta=0x20)) is None


# --- CD checks -----------------------------------------------------------------------------


def test_disc_check_sites():
    sites = p.disc_check_sites(disc_image())
    assert len(sites) == p.DISC_CHECKS and not any(s[3] for s in sites)
    for at, original, patched, _ in sites:
        assert len(original) == len(patched)
        assert patched[0] == 0x31 and patched[1] in (0xC0, 0xF6, 0xDB, 0xFF)  # xor eax|esi|ebx|edi
    partly = p.disc_check_sites(disc_image(patched=3))
    assert [s[3] for s in partly] == [True] * 3 + [False] * 8


def test_disc_check_sites_2007_cd():
    image = disc_image(sub=True)
    sites = p.disc_check_sites(image)
    assert len(sites) == p.DISC_CHECKS and not any(s[3] for s in sites)
    for at, original, patched, _ in sites:
        assert image[at : at + len(original)] == original and original[0] in (0x81, 0x2D)
    partly = p.disc_check_sites(disc_image(patched=5, sub=True))
    assert [s[3] for s in partly] == [True] * 5 + [False] * 6


def test_disc_check_sites_other_instruction():
    image = bytearray(disc_image(sub=True))
    at = p.disc_check_sites(bytes(image))[0][0]
    image[at] = 0x05  # add eax,imm32: not one of the checks
    assert p.disc_check_sites(bytes(image)) is None


def test_disc_check_sites_wrong_count():
    assert p.disc_check_sites(disc_image(count=10)) is None
    assert p.disc_check_sites(disc_image(count=12)) is None
    assert p.disc_check_sites(filler(100)) is None


# --- PE layout and 1.01 ----------------------------------------------------------------------


def test_pe_layout_and_va_offset():
    image = bytes(pe_image(hooks=False))
    pe, nsec, opt, table, sections = p.pe_layout(image)
    assert (pe, nsec, opt, table) == (0x80, 1, 0x98, 0x178)
    assert p.va_offset(sections, 0x400000 + TEXT_VA) == TEXT_RAW
    assert p.va_offset(sections, 0x400000 + TEXT_VA + TEXT_SIZE) is None
    assert p.va_offset(sections, 0x400000) is None


def test_v101_state():
    assert p.v101_state(bytes(pe_image())) == "original"
    assert p.v101_state(bytes(pe_image(hooks=False))) is None


def test_apply_v101():
    image = pe_image()
    size_before = struct.unpack_from("<I", image, 0x98 + 56)[0]
    out = p.apply_v101(bytearray(image))
    assert p.v101_state(bytes(out)) == "patched"
    _, nsec, opt, _, sections = p.pe_layout(bytes(out))
    name, vsize, vaddr, rsize, raw = sections[-1]
    assert nsec == 2 and name == p.V101_SECTION and vaddr == size_before
    assert raw == len(image) and rsize % 0x200 == 0 and len(out) == raw + rsize
    assert struct.unpack_from("<I", out, opt + 56)[0] == size_before + ((vsize + 0xFFF) & ~0xFFF)
    start, end = 0x400000 + vaddr, 0x400000 + vaddr + vsize
    for va, original, symbol, new in p.V101_HOOKS:
        at = p.va_offset(sections, va)
        length = len(bytes.fromhex(original.replace(" ", "")))
        if symbol:
            assert out[at] == p.JMP_REL32
            target = va + 5 + struct.unpack_from("<i", out, at + 1)[0]
            assert start <= target < end
            assert out[at + 5 : at + length] == bytes([p.NOP] * (length - 5))
        else:
            assert out[at : at + length] == bytes.fromhex(new)


def test_apply_v101_drops_the_signature():
    image = pe_image()
    sec_dir = 0x98 + 96 + 32
    struct.pack_into("<II", image, sec_dir, len(image), 0x100)
    image += bytes(0x100)
    out = p.apply_v101(image)
    assert struct.unpack_from("<II", out, sec_dir) == (0, 0)


def test_apply_v101_without_room():
    image = pe_image()
    struct.pack_into("<I", image, 0x178 + 20, 0x178 + 40)  # section data right after its header
    with pytest.raises(SystemExit):
        p.apply_v101(image)


# --- integrity --------------------------------------------------------------------------------


def test_crc32_raw():
    assert p.crc32_raw(b"") == 0xFFFFFFFF
    assert p.crc32_raw(b"123456789") == 0xCBF43926 ^ 0xFFFFFFFF


def test_fix_integrity():
    image = pe_image(hooks=False, stubs=p.SELF_CHECKS)
    sites = p.integrity_sites(bytes(image))
    assert sites == [TEXT_RAW + 0x1000 + i * 0x200 for i in range(p.SELF_CHECKS)]
    out = p.fix_integrity(image)
    for desc in sites:
        assert struct.unpack_from("<I", out, desc)[0] == p.crc32_raw(bytes(out[desc + 0xC : desc + 0xC + 0x40]))
    assert struct.unpack_from("<I", out, p.FILE_CRC_AT)[0] == zlib.crc32(bytes(out[0x80:]))


def test_integrity_sites_wrong_count():
    assert p.integrity_sites(bytes(pe_image(hooks=False, stubs=4))) is None


# --- command line ---------------------------------------------------------------------------


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2patch.py", *map(str, args)])
    p.main()


def test_main_goals_writes_backup_once(tmp_path, monkeypatch, capsys):
    exe = tmp_path / "anstoss2.exe"
    exe.write_bytes(goal_image())
    run_main(monkeypatch, "--goals", exe)
    assert exe.read_bytes() == goal_image(patched=True, home=p.JMP, away=p.JMP)
    backup = tmp_path / ("anstoss2.exe" + p.BACKUP_SUFFIX)
    assert backup.read_bytes() == goal_image()
    run_main(monkeypatch, "--goals", exe)
    assert "already patched" in capsys.readouterr().out
    assert backup.read_bytes() == goal_image()


def test_main_sound(tmp_path, monkeypatch):
    exe = tmp_path / "anstoss2.exe"
    exe.write_bytes(sound_block())
    run_main(monkeypatch, "--sound", exe)
    assert exe.read_bytes() == sound_block(patched=True)


def test_main_unknown_exe(tmp_path, monkeypatch):
    exe = tmp_path / "anstoss2.exe"
    exe.write_bytes(filler(64))
    with pytest.raises(SystemExit, match="unknown version"):
        run_main(monkeypatch, "--goals", exe)
    assert exe.read_bytes() == filler(64)
    assert not (tmp_path / ("anstoss2.exe" + p.BACKUP_SUFFIX)).exists()


def test_main_needs_a_patch(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        run_main(monkeypatch, tmp_path / "x.exe")


def test_main_v101_unknown(tmp_path, monkeypatch):
    exe = tmp_path / "run.exe"
    exe.write_bytes(pe_image(hooks=False))
    with pytest.raises(SystemExit, match="unknown version"):
        run_main(monkeypatch, "--v101", exe)


def gog_image():
    """A GOG-like run.exe: 1.01 places, CD checks and code self-checks."""
    image = pe_image(stubs=p.SELF_CHECKS)
    checks = disc_image()
    at = TEXT_RAW + 0x10000
    image[at : at + len(checks)] = checks
    return image


def test_main_gog(tmp_path, monkeypatch, capsys):
    exe = tmp_path / "run.exe"
    exe.write_bytes(gog_image())
    run_main(monkeypatch, "--disc-check", "--v101", exe)
    out = exe.read_bytes()
    assert p.v101_state(out) == "patched"
    assert all(s[3] for s in p.disc_check_sites(out))
    assert struct.unpack_from("<I", out, p.FILE_CRC_AT)[0] == zlib.crc32(out[0x80:])
    assert "integrity values updated" in capsys.readouterr().out
    run_main(monkeypatch, "--disc-check", "--v101", exe)
    assert exe.read_bytes() == out
    assert "already patched" in capsys.readouterr().out
