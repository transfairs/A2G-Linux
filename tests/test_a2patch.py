"""a2patch.py on synthetic images: no game files needed."""

import runpy
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
    struct.pack_into("<III", image, pe + 24 + 28, 0x400000, 0x1000, 0x200)  # image base, alignments
    struct.pack_into("<I", image, pe + 24 + 56, TEXT_VA + TEXT_SIZE)  # SizeOfImage
    struct.pack_into("<8sIIII", image, pe + 24 + optsize, b".text\0\0\0", TEXT_SIZE, TEXT_VA, TEXT_SIZE, TEXT_RAW)
    image[pe + 24 + optsize + 40 : pe + 24 + optsize + 80] = bytes(range(1, 41))  # leftovers behind the header
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
    # as A2G-Patch's PeFile.AddSection: behind the file, room for the 40 overwritten header bytes behind the code
    assert raw == len(image) and rsize == (vsize + 40 + 0x1FF) & ~0x1FF and len(out) == raw + rsize
    assert out[raw + vsize : raw + vsize + 40] == bytes(range(1, 41))
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


def with_signature(image):
    """image with a signature (certificate table) at its end, as GOG's run.exe has one."""
    struct.pack_into("<II", image, 0x98 + 96 + 32, len(image), 0x100)
    return image + bytes(range(0x100))


def test_apply_v101_keeps_the_signature():
    image = with_signature(pe_image())
    out = p.apply_v101(bytearray(image))
    assert out[len(image) - 0x100 : len(image)] == bytes(range(0x100))
    assert struct.unpack_from("<II", out, 0x98 + 96 + 32) == (len(image) - 0x100, 0x100)
    assert p.pe_layout(bytes(out))[4][-1][4] == (len(image) + 0x1FF) & ~0x1FF  # the code behind the signature


@pytest.mark.parametrize("signed", [False, True])
def test_remove_v101_restores_the_exe_to_the_byte(signed):
    image = with_signature(pe_image()) if signed else pe_image()
    out = p.remove_v101(p.apply_v101(bytearray(image)))
    assert bytes(out) == bytes(image)
    assert p.v101_state(bytes(out)) == "original"


def test_remove_v101_of_version_0_1():
    """a2patch.py 0.1 dropped the signature and kept no header bytes: the section goes, the header slot is zeros."""
    image = pe_image()
    out = p.apply_v101(bytearray(image))
    raw, vsize = len(image), p.pe_layout(bytes(out))[4][-1][1]
    out[raw + vsize : raw + vsize + 40] = bytes(40)
    restored = p.remove_v101(out)
    assert len(restored) == len(image) and p.v101_state(bytes(restored)) == "original"
    assert restored[0x178 + 40 : 0x178 + 80] == bytes(40)


def test_apply_v101_without_room():
    image = pe_image()
    struct.pack_into("<I", image, 0x178 + 20, 0x178 + 40)  # section data right after its header
    with pytest.raises(SystemExit):
        p.apply_v101(image)


def test_apply_v101_patch_of_wrong_length(monkeypatch):
    hooks = [(va, original, symbol, new + "90" if new else new) for va, original, symbol, new in p.V101_HOOKS]
    monkeypatch.setattr(p, "V101_HOOKS", hooks)
    with pytest.raises(SystemExit, match="patch at 0x501dcf has 3 bytes instead of 2"):
        p.apply_v101(pe_image())


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


def test_main_later_patch_keeps_the_first_backup(tmp_path, monkeypatch):
    exe = tmp_path / "anstoss2.exe"
    original = goal_image() + sound_block()
    exe.write_bytes(original)
    run_main(monkeypatch, "--goals", exe)
    run_main(monkeypatch, "--sound", exe)
    assert exe.read_bytes() == goal_image(patched=True, home=p.JMP, away=p.JMP) + sound_block(patched=True)
    assert (tmp_path / ("anstoss2.exe" + p.BACKUP_SUFFIX)).read_bytes() == original


def test_runs_as_a_script(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["a2patch.py"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(p.__file__, run_name="__main__")
    assert e.value.code == 2 and "usage: a2patch.py" in capsys.readouterr().err


# --- bug fixes from A2G-Patch (--fixes) -------------------------------------------------------
# Expected bytes are written out as in A2G-Patch's Patches.cs, not built from a2patch's constants.

MSG = bytes.fromhex("98edc100")
ARROW_CHECK = bytes.fromhex("8b86f400000085c07529")
ARROW_ORIGINAL = (
    bytes.fromhex("a1")
    + MSG
    + bytes.fromhex("8b4e1c6a006a005051ffd3" "8b86f4000000c786f00000003c000000408986f4000000eb0a")
)
ARROW_PATCHED = (
    bytes.fromhex("c786f400000001000000c786f00000003c000000a1")
    + MSG
    + bytes.fromhex("8b4e1c6a006a005051ffd3909090eb0a")
)


def test_arrow_sites():
    image = filler(8) + ARROW_CHECK + ARROW_ORIGINAL + filler(8)
    sites = p.arrow_sites(image)
    assert sites == [(8 + len(ARROW_CHECK), ARROW_ORIGINAL, ARROW_PATCHED, False)]
    patched = filler(8) + ARROW_CHECK + ARROW_PATCHED + filler(8)
    assert p.arrow_sites(patched) == [(8 + len(ARROW_CHECK), ARROW_ORIGINAL, ARROW_PATCHED, True)]
    assert p.arrow_sites(image + image) is None
    assert p.arrow_sites(filler(64)) is None


VIDEO_PREFIX = bytes.fromhex(
    "85c074218b4d0051e811111111"
    "8d4c2410e822222222"
    "33c05f5e5d5b"
    "81c484000000c20c00"
    "8b078d969884000068"
    "8c000000"
    "5250e833333333"
)
VIDEO_ORIGINAL = bytes.fromhex(
    "8d866480000050c70028000000"
    "8b8ed4840000894804"
    "8b96d8840000895008"
    "66c7400c010066c7400e0800"
    "89581089581489581889581c895820895824"
    "8b0750e844444444"
    "89868c840000"
)


def video_patched_bytes():
    call = struct.unpack("<i", bytes.fromhex("44444444"))[0] + 12  # the call moves 12 bytes up
    jump = 4 - (len(VIDEO_PREFIX) + 64 + 4)  # back to "release" (mov ecx,[ebp]) in the prefix
    return (
        bytes.fromhex("8d866480000050c70028000000" "8b4f408948048b4f44894808" "c7400c01000800")
        + bytes.fromhex("89581089581489581889581c895820895824")
        + bytes.fromhex("ff37e8")
        + struct.pack("<i", call)
        + bytes.fromhex("85c075078907e9")
        + struct.pack("<i", jump)
        + bytes.fromhex("8947f890909090")
    )


def test_video_sites():
    assert len(VIDEO_PREFIX) == len(p.VIDEO_PREFIX) and len(VIDEO_ORIGINAL) == 75
    image = filler(4) + VIDEO_PREFIX + VIDEO_ORIGINAL + filler(4)
    at = 4 + len(VIDEO_PREFIX)
    sites = p.video_sites(image)
    assert sites == [(at, VIDEO_ORIGINAL, video_patched_bytes(), False)]
    patched = filler(4) + VIDEO_PREFIX + video_patched_bytes() + filler(4)
    assert p.video_sites(patched) == [(at, VIDEO_ORIGINAL, video_patched_bytes(), True)]
    # The bytes a2start.exe's palette patch checks and rewrites ("push eax / mov dword [eax],28") stay.
    assert video_patched_bytes()[6:10] == VIDEO_ORIGINAL[6:10] == bytes.fromhex("50c70028")
    assert p.video_sites(image + image) is None
    assert p.video_sites(VIDEO_ORIGINAL) is None


FREEZE = bytes.fromhex("2b857c0100003db80b000089857c0100007d0e")


def test_freeze_sites_two_places_mixed_states():
    patched = FREEZE[:17] + b"\x73" + FREEZE[18:]
    image = filler(4) + FREEZE + filler(4) + patched + filler(4)
    sites = p.freeze_sites(image)
    assert sites == [(4 + 17, b"\x7d", b"\x73", False), (4 + 19 + 4 + 17, b"\x7d", b"\x73", True)]
    assert p.freeze_sites(filler(4) + FREEZE) is None
    assert p.freeze_sites((FREEZE + filler(2)) * 3) is None


DISK = bytes.fromhex("0faf4424103d00701700731b8d4c242468c10a0000")


def test_disk_sites():
    assert p.disk_sites(filler(4) + DISK) == [(14, b"\x73", b"\xeb", False)]
    assert p.disk_sites(filler(4) + DISK[:10] + b"\xeb" + DISK[11:]) == [(14, b"\x73", b"\xeb", True)]
    assert p.disk_sites(DISK + DISK) is None
    assert p.disk_sites(DISK.replace(b"\x68\xc1", b"\x68\xc2")) is None  # another text


SQUAD_ORIGINAL = bytes.fromhex("8b44240450e8a6ffffff83c40433c9663d1e000f9dc18bc1c390909090909090")
SQUAD_PATCHED = bytes.fromhex("8b44240450e8a6ffffff59663d1e007d086683b9e60000001e0f9dc00fb6c0c3")


def test_squad_sites():
    assert len(SQUAD_ORIGINAL) == len(SQUAD_PATCHED) == 32
    assert p.squad_sites(filler(4) + SQUAD_ORIGINAL) == [(4, SQUAD_ORIGINAL, SQUAD_PATCHED, False)]
    assert p.squad_sites(filler(4) + SQUAD_PATCHED) == [(4, SQUAD_ORIGINAL, SQUAD_PATCHED, True)]
    assert p.squad_sites(SQUAD_ORIGINAL + SQUAD_PATCHED) is None


NEW_FIXES = ("events", "crashes", "competence", "grades", "appearances", "fish", "manager")


def fixes_image(patched=False):
    if patched:
        parts = [sound_block(patched=True), ARROW_CHECK + ARROW_PATCHED, VIDEO_PREFIX + video_patched_bytes()]
        parts += [FREEZE[:17] + b"\x73" + FREEZE[18:]] * 2 + [DISK[:10] + b"\xeb" + DISK[11:], SQUAD_PATCHED]
        parts += [invest_patched_bytes(), money_block(week_patched=True, booking_patched=True)]
        parts += [apply_sites(places_image(k), p.PATCHES[k][1](places_image(k))) for k in NEW_FIXES]
    else:
        parts = [
            sound_block(),
            ARROW_CHECK + ARROW_ORIGINAL,
            VIDEO_PREFIX + VIDEO_ORIGINAL,
            FREEZE,
            FREEZE,
            DISK,
            SQUAD_ORIGINAL,
            invest_original_bytes(),
            money_block(),
        ] + [places_image(k) for k in NEW_FIXES]
    return filler(8).join(parts)


def test_main_fixes(tmp_path, monkeypatch, capsys):
    exe = tmp_path / "anstoss2.exe"
    exe.write_bytes(fixes_image())
    run_main(monkeypatch, "--fixes", exe)
    assert exe.read_bytes() == fixes_image(patched=True)
    assert (tmp_path / ("anstoss2.exe" + p.BACKUP_SUFFIX)).read_bytes() == fixes_image()
    assert capsys.readouterr().out.count(": patched") == len(p.FIXES)
    run_main(monkeypatch, "--fixes", exe)
    assert capsys.readouterr().out.count("already patched") == len(p.FIXES)
    assert exe.read_bytes() == fixes_image(patched=True)


def test_main_fixes_needs_every_place(tmp_path, monkeypatch):
    exe = tmp_path / "anstoss2.exe"
    exe.write_bytes(fixes_image().replace(DISK, filler(len(DISK))))
    with pytest.raises(SystemExit, match="unknown version"):
        run_main(monkeypatch, "--fixes", exe)
    assert not (tmp_path / ("anstoss2.exe" + p.BACKUP_SUFFIX)).exists()


# --- investments, negotiation lock, speeches (bytes as in A2G-Patch's Patches.cs) ---------------

LOANS, BOOKINGS = 0x1234, -0x5678


def invest_original_bytes():
    values = LOANS + 0x20 + 13  # "values" lies 0x20 behind "loans", seen from the calls 13 bytes apart
    return (
        bytes.fromhex("568b74240857" "56e8")
        + struct.pack("<i", values)
        + bytes.fromhex("8b3e83c4042bf8" "56e8")
        + struct.pack("<i", LOANS)
        + bytes.fromhex("83c40403f8" "56e8")
        + struct.pack("<i", BOOKINGS)
        + bytes.fromhex("83c40403c75f5ec390909090")
    )


def invest_patched_bytes():
    return (
        bytes.fromhex("568b74240856e8")
        + struct.pack("<i", LOANS + 14)  # the call moves 14 bytes up
        + bytes.fromhex("030683ee806a0659f6463301" "74032b462883c610e2f2" "5e5056e8")
        + struct.pack("<i", BOOKINGS - 5)  # and this one 5 bytes down
        + bytes.fromhex("595903c15ec390")
    )


def test_invest_sites():
    assert len(invest_original_bytes()) == len(invest_patched_bytes()) == 48
    image = filler(4) + invest_original_bytes() + filler(4)
    assert p.invest_sites(image) == [(4, invest_original_bytes(), invest_patched_bytes(), False)]
    patched = filler(4) + invest_patched_bytes() + filler(4)
    assert p.invest_sites(patched) == [(4, invest_original_bytes(), invest_patched_bytes(), True)]
    wrong_values = bytearray(image)
    wrong_values[4 + 8] ^= 1  # "values" not where expected
    assert p.invest_sites(bytes(wrong_values)) is None
    assert p.invest_sites(image + image) is None


NEGOTIATION_ORIGINAL = bytes.fromhex(
    "8a8d7d1000008a857e1000008a9d7f1000008a9580100000d0e9d0e8d0ebd0ea55"
    "888d7d10000088857e100000889d7f100000889580100000"
)
NEGOTIATION_PATCHED = bytes.fromhex(
    "8a8d811000008a85821000008a9d831000008a9584100000d0e9d0e8d0ebd0ea55"
    "888d81100000888582100000889d83100000889584100000"
)


def test_negotiation_sites():
    assert p.negotiation_sites(filler(3) + NEGOTIATION_ORIGINAL) == [
        (3, NEGOTIATION_ORIGINAL, NEGOTIATION_PATCHED, False)
    ]
    assert p.negotiation_sites(filler(3) + NEGOTIATION_PATCHED) == [
        (3, NEGOTIATION_ORIGINAL, NEGOTIATION_PATCHED, True)
    ]
    assert p.negotiation_sites(NEGOTIATION_ORIGINAL * 2) is None


TABLE = 0x6B7D50
ROLL_HEAD = bytes.fromhex("e811223344")
ROLL_TAIL = bytes.fromhex("eb366a04e8")
MARK_HEAD = bytes.fromhex("8d8c24a0060000e855667788")
MARK_TAIL = bytes.fromhex("8d8c2488080000")
MARK_ORIGINAL = bytes.fromhex("85db742485ff74208b8424c0170000c680e4000000018a8d401400008888e500000066c7401c6400")
MARK_PATCHED = bytes.fromhex("4b75258b8424c017000083e8808a8d4014000085ff740cc640640166c7409c6400663df6d9884865")


def table(field):
    return struct.pack("<I", TABLE + field).hex()


APPLY_ORIGINAL = bytes.fromhex(
    "568b742408578a86e500000084c00f848f00000025ff0000008d3c80c1e702f687"
    + table(0x10)
    + "01742266837c2414008b442410740c668b4810663b480e7f65eb0a668b500e663b50107f590fbe8f"
    + table(0x0C)
    + "0fbf461083c1640fafc8b81f85eb51f7e9c1fa058bcab81f85eb51c1e91f03d1668956100fbe8f"
    + table(0x0D)
    + "0fbf561683c1640fafcaf7e9c1fa058bc2c1e81f03d0668956168a87"
    + table(0x0E)
    + "3c6374038846315f5ec390909090909090909090"
)
APPLY_PATCHED = bytes.fromhex(
    "568b74240857530fbe86e5000000998bda33c22bc274608d3c80c1e702f687"
    + table(0x10)
    + "01742266837c2418008b442414740c668b4810663b480e7f3beb0a668b500e663b50107f2f0fbe8f"
    + table(0x0C)
    + "8d4610e8240000000fbe8f"
    + table(0x0D)
    + "8d4616e81500000085db750d8a87"
    + table(0x0E)
    + "3c6374038846315b5f5ec385db740685c97c02f7d9500fbf0083c1640fafc8b81f85eb51f7e9c1fa058bcac1e91f03d158668910c3"
    + "cc" * 11
)


def speech_image(patched=False):
    roll = bytes.fromhex("33db" if patched else "33ff")
    return filler(4).join(
        [
            b"",
            ROLL_HEAD + roll + ROLL_TAIL,
            MARK_HEAD + (MARK_PATCHED if patched else MARK_ORIGINAL) + MARK_TAIL,
            APPLY_PATCHED if patched else APPLY_ORIGINAL,
            b"",
        ]
    )


def test_speech_sites():
    assert len(APPLY_ORIGINAL) == len(APPLY_PATCHED) == 176
    sites = p.speech_sites(speech_image())
    assert [s[1:] for s in sites] == [
        (bytes.fromhex("33ff"), bytes.fromhex("33db"), False),
        (MARK_ORIGINAL, MARK_PATCHED, False),
        (APPLY_ORIGINAL, APPLY_PATCHED, False),
    ]
    patched = bytearray(speech_image())
    for offset, _, new, _ in sites:
        patched[offset : offset + len(new)] = new
    assert bytes(patched) == speech_image(patched=True)
    assert all(s[3] for s in p.speech_sites(bytes(patched)))


def test_speech_sites_unknown():
    assert p.speech_sites(speech_image().replace(ROLL_TAIL, filler(5))) is None
    other_table = APPLY_ORIGINAL.replace(bytes.fromhex(table(0x0E)), struct.pack("<I", 0x123456))
    assert p.speech_sites(speech_image().replace(APPLY_ORIGINAL, other_table)) is None
    assert p.speech_sites(speech_image() + APPLY_ORIGINAL) is None


# --- interview answers (A2G-Trainer's stub) ----------------------------------------------------

BASE = 0x400000
CONTEXT = 0x77F960
ENGINE = CONTEXT - 0xC8
I_TEXT_RAW, I_TEXT_SIZE = 0x400, 0x2000
APPLY_AT, MORALE_AT, APPLY_CALL_AT, MORALE_CALL_AT = 0x100, 0x200, 0x400, 0x500  # within .text


def text_va(offset):
    return BASE + 0x1000 + offset


def interview_image(room=True, header_room=True, engine=ENGINE):
    """A PE file with .text (executable, headers ending at 0x400) holding the two functions and their calls."""
    image = bytearray(I_TEXT_RAW + I_TEXT_SIZE)
    optsize = 0xE0
    # without header room, the one section header ends right where .text starts
    pe = 0x80 if header_room else I_TEXT_RAW - 40 - optsize - 24
    struct.pack_into("<I", image, 0x3C, pe)
    image[pe : pe + 4] = b"PE\0\0"
    struct.pack_into("<HH", image, pe + 6, 1, 0)
    struct.pack_into("<H", image, pe + 20, optsize)
    struct.pack_into("<III", image, pe + 24 + 28, BASE, 0x1000, 0x200)  # image base, alignments
    struct.pack_into("<I", image, pe + 24 + 56, 0x1000 + I_TEXT_SIZE)  # SizeOfImage
    table = pe + 24 + optsize
    struct.pack_into("<8sIIII", image, table, b".text\0\0\0", I_TEXT_SIZE, 0x1000, I_TEXT_SIZE, I_TEXT_RAW)
    struct.pack_into("<I", image, table + 36, 0x60000020)
    if header_room:
        image[table + 40 : table + 80] = bytes(range(1, 41))  # leftovers behind the headers, kept on adding a section
    text = I_TEXT_RAW
    image[text + APPLY_AT : text + APPLY_AT + 14] = bytes.fromhex("5355568b74241057668b467450e8")
    image[text + MORALE_AT : text + MORALE_AT + 22] = bytes.fromhex("8b4c24048b442408660fb6919c00000003c2663dc800")
    call = text_va(APPLY_CALL_AT + 17)
    image[text + APPLY_CALL_AT : text + APPLY_CALL_AT + 27] = (
        b"\x8b\x0d"
        + struct.pack("<I", engine)
        + b"\x50\xe8"
        + bytes(4)
        + b"\x68"
        + struct.pack("<I", CONTEXT)
        + b"\xe8"
        + struct.pack("<i", text_va(APPLY_AT) - (call + 5))
        + b"\xa1"
        + struct.pack("<I", CONTEXT + 0x10)
    )
    call = text_va(MORALE_CALL_AT + 10)
    image[text + MORALE_CALL_AT : text + MORALE_CALL_AT + 24] = (
        bytes.fromhex("8b4c24508b54245c5152e8")
        + struct.pack("<i", text_va(MORALE_AT) - (call + 5))
        + bytes.fromhex("83c4085f5e83c440c3")
    )
    if not room:
        image[-0x200:] = b"\xcc" * 0x200
    return image


def call_target(image, at):
    va = text_va(at - I_TEXT_RAW)
    return va + 5 + struct.unpack_from("<i", image, at + 1)[0]


def check_stub(stub_bytes, stub_va):
    assert stub_bytes[:9] == b"A2GINT02\x01"
    assert stub_bytes[0x22:0x26] == struct.pack("<I", stub_va + 8)  # cmp byte [flag],0
    assert stub_bytes[0x2A:0x2E] == struct.pack("<I", ENGINE)
    assert stub_bytes[0x5E:0x62] == struct.pack("<I", CONTEXT + 0x14)
    assert stub_bytes[0xB0:0xB5] == b"\xb8" + struct.pack("<I", text_va(APPLY_AT))  # mov eax,apply
    assert stub_bytes[0xD3:0xD7] == struct.pack("<I", CONTEXT + 0xC258)  # money factor
    assert stub_bytes[0xEE:0xF3] == b"\xb8" + struct.pack("<I", text_va(MORALE_AT))  # mov eax,morale


def test_interviews_in_room_of_last_section():
    image = interview_image()
    assert p.interview_state(bytes(image)) == "original"
    out = p.apply_interviews(bytearray(image))
    assert len(out) == len(image)
    at = ((I_TEXT_RAW + I_TEXT_SIZE - 177) & ~15) - 256  # in front of A2G-Patch's cup draw helper
    stub_va = text_va(at - I_TEXT_RAW)
    check_stub(out[at : at + 256], stub_va)
    assert call_target(out, I_TEXT_RAW + APPLY_CALL_AT + 17) == stub_va + 0x20
    assert call_target(out, I_TEXT_RAW + MORALE_CALL_AT + 10) == stub_va + 0xC0
    assert p.interview_state(bytes(out)) == "patched"
    assert p.interview_locate(bytes(out))["stub"] == at


def test_interviews_in_section_of_their_own():
    image = interview_image(room=False)
    assert p.interview_state(bytes(image)) == "original"
    out = p.apply_interviews(bytearray(image))
    pe = p.Pe(bytes(out))
    name, vsize, va, rsize, raw, flags = pe.sections[-1]
    assert (name, vsize, va, rsize, raw, flags) == (
        ".a2int",
        0x100,
        0x1000 + I_TEXT_SIZE,
        0x200,
        len(image),
        0xE0000020,
    )
    assert pe.size_of_image == 0x1000 + I_TEXT_SIZE + 0x1000
    assert len(out) == len(image) + 0x200
    assert out[raw + 0x100 : raw + 0x100 + 40] == bytes(range(1, 41))  # the overwritten leftovers
    check_stub(out[raw : raw + 0x100], BASE + va)
    assert p.interview_state(bytes(out)) == "patched"


def test_interviews_put_their_section_in_front_of_v101(monkeypatch):
    """A2G-Patch recognizes 1.01 only as the last section, so the stub's section goes in front of it."""
    monkeypatch.setattr(p, "V101_HOOKS", [])  # the interview image has none of 1.01's places
    image = interview_image(room=False)
    with_v101 = p.apply_v101(bytearray(image))
    out = p.apply_interviews(bytearray(with_v101))
    pe = p.Pe(bytes(out))
    assert [s[0] for s in pe.sections] == [".text", p.INTERVIEW_SECTION, p.V101_SECTION_NAME]
    _, _, va, _, raw, _ = pe.sections[1]
    assert va == 0x1000 + I_TEXT_SIZE and raw == len(image)
    check_stub(out[raw : raw + 0x100], BASE + va)
    assert p.interview_state(bytes(out)) == "patched" and p.v101_state(bytes(out)) == "patched"
    # the same as both at once on the original, in the installer's order (interviews first)
    assert bytes(out) == bytes(p.apply_v101(p.apply_interviews(bytearray(image))))


def test_interviews_unknown():
    assert p.interview_state(bytes(interview_image(engine=ENGINE + 4))) is None
    assert p.interview_state(bytes(interview_image(room=False, header_room=False))) is None
    assert p.interview_state(bytes(filler(64))) is None
    stub_broken = p.apply_interviews(interview_image())
    stub_broken[((I_TEXT_RAW + I_TEXT_SIZE - 177) & ~15) - 256 + 0x2A] ^= 1
    assert p.interview_state(bytes(stub_broken)) is None


def test_pe_maps_offsets_and_addresses_across_sections():
    out = p.apply_interviews(interview_image(room=False))
    pe = p.Pe(bytes(out))
    _, _, va, _, raw, _ = pe.sections[-1]
    assert pe.va_at(raw + 4) == BASE + va + 4  # in the second section, behind .text
    assert pe.va_at(I_TEXT_RAW) == text_va(0)
    assert pe.va_at(0x10) is None  # headers
    assert pe.va_at(len(out)) is None
    assert pe.file_offset(BASE + va + 4) == raw + 4
    assert pe.file_offset(BASE) is None  # headers are not section data
    assert pe.file_offset(BASE + va + 0x200) is None  # behind the stub, virtual only


def aim_call(image, at, target):
    """Points the call at file offset at (within .text) to the address target."""
    struct.pack_into("<i", image, at + 1, target - (text_va(at - I_TEXT_RAW) + 5))


def test_interviews_calls_lead_elsewhere():
    apply_call, morale_call = I_TEXT_RAW + APPLY_CALL_AT + 17, I_TEXT_RAW + MORALE_CALL_AT + 10
    # apply leads somewhere unknown, morale still to its function: not one stub
    image = interview_image()
    aim_call(image, apply_call, text_va(0x600))
    assert p.interview_locate(bytes(image)) is None
    # both lead to a "stub" that would end behind the file
    image = interview_image()
    stub = text_va(I_TEXT_SIZE - 0x10)
    aim_call(image, apply_call, stub + p.INTERVIEW_APPLY_ENTRY)
    aim_call(image, morale_call, stub + p.INTERVIEW_MORALE_ENTRY)
    assert p.interview_locate(bytes(image)) is None
    assert p.interview_state(bytes(image)) is None


def test_interviews_without_executable_section():
    image = interview_image()
    struct.pack_into("<I", image, 0x80 + 24 + 0xE0 + 36, 0x40000020)  # .text: no execute flag
    assert p.interview_room(bytes(image), p.Pe(bytes(image))) == -1  # its zeros are no room for code
    out = p.apply_interviews(image)
    assert p.Pe(bytes(out)).sections[-1][0] == p.INTERVIEW_SECTION
    assert p.interview_state(bytes(out)) == "patched"


def test_main_balancing(tmp_path, monkeypatch, capsys):
    exe = tmp_path / "anstoss2.exe"
    image = interview_image()
    at = I_TEXT_RAW + 0x800
    for block in (NEGOTIATION_ORIGINAL, speech_image()):
        image[at : at + len(block)] = block
        at += len(block) + 16
    exe.write_bytes(image)
    run_main(monkeypatch, "--negotiation", "--speeches", "--interviews", exe)
    out = exe.read_bytes()
    assert p.negotiation_sites(out)[0][3] and all(s[3] for s in p.speech_sites(out))
    assert p.interview_state(out) == "patched"
    assert capsys.readouterr().out.count(": patched") == 3
    run_main(monkeypatch, "--negotiation", "--speeches", "--interviews", exe)
    assert capsys.readouterr().out.count("already patched") == 3
    assert exe.read_bytes() == out
    exe.write_bytes(interview_image(room=False, header_room=False))
    with pytest.raises(SystemExit, match="unknown version"):
        run_main(monkeypatch, "--interviews", exe)


# --- trainer supply -------------------------------------------------------------------------------

GROUP, COACH_LIST, COACH_TABLE, KEEPER_LIST = 0x6C1000, 0x826BDE, 0x6C2000, 0x826EFE
AGE_AT, COACH_AT, KEEPER_AT, RANDOM_AT = 0x10, 0x100, 0x200, 0x300


def coach_image(age=35, group2=GROUP):
    image = bytearray(filler(0x400))
    check = bytes.fromhex("8a561e6603868000000080fa") + bytes([age]) + bytes.fromhex("0f869e010000")
    image[AGE_AT : AGE_AT + len(check)] = check
    call = AGE_AT + 0x52
    image[call : call + 7] = bytes.fromhex("6a03e8") + struct.pack("<i", RANDOM_AT - (call + 2 + 5))
    image[COACH_AT : COACH_AT + 187] = p.coach_original(GROUP, COACH_LIST, COACH_TABLE)
    image[KEEPER_AT : KEEPER_AT + 120] = p.keeper_original(group2, KEEPER_LIST)
    return image


def test_coach_sites():
    image = coach_image()
    sites = p.coach_sites(bytes(image))
    assert [(s[0], s[3]) for s in sites] == [(AGE_AT + 12, False), (COACH_AT, False), (KEEPER_AT, False)]
    assert sites[0][1:3] == (b"\x23", b"\x20")  # cmp dl,35 -> cmp dl,32
    for offset, _, new, _ in sites:
        image[offset : offset + len(new)] = new
    for at, call in ((COACH_AT, 51), (KEEPER_AT, 48)):  # both call the game's random function
        assert image[at] == 0x53 and image[at + call] == 0xE8
        assert at + call + 5 + struct.unpack_from("<i", image, at + call + 1)[0] == RANDOM_AT
    patched = p.coach_sites(bytes(image))
    assert all(s[3] for s in patched) and [s[1:3] for s in patched] == [s[1:3] for s in sites]


def test_coach_sites_unknown():
    assert p.coach_sites(bytes(coach_image(age=30))) is None
    assert p.coach_sites(bytes(coach_image(group2=GROUP + 4))) is None  # the two functions disagree
    no_call = coach_image()
    no_call[AGE_AT + 0x52] = 0x6B
    assert p.coach_sites(bytes(no_call)) is None
    assert p.coach_sites(bytes(coach_image()) * 2) is None


# --- money limit (bytes as in A2G-Patch's Patches.cs) --------------------------------------------

# where the parts lie in money_block: the bookings 0x100 behind the first function they call
FIRST, M_BOOKINGS, SECOND, THIRD, WEEK, BOOKING = 0x000, 0x100, 0x1E0, 0x1F0, 0x200, 0x300
MONEY_CHECK = bytes.fromhex(
    "8b8e540100008bc103c7710a8bc7c1f81f35ffffff7f"  # mov ecx,[esi+154] / ... / xor eax,7FFFFFFF
    "3d009435777e0f3bc17e0bb8009435773bc17d028bc1"  # cmp eax,2000000000 / ... / mov eax,ecx
    "5f8986540100005e5b83c424c3"  # store
)


def put_call(block, at, target, opcode=0xE8):
    block[at] = opcode
    struct.pack_into("<i", block, at + 1, target - (at + 5))


def money_block(week_patched=False, booking_patched=False, second=SECOND):
    block = bytearray(filler(0x320))
    block[M_BOOKINGS : M_BOOKINGS + 216] = bytes(0 if b is None else b for b in p.MONEY_BOOKINGS)
    for at, target in ((0x07, FIRST), (0xC0, SECOND), (0xCB, THIRD)):
        put_call(block, M_BOOKINGS + at, target)
    if week_patched:
        block[WEEK : WEEK + 208] = (
            bytes.fromhex("8b442404055401000050e80000000059038138030000" "2b813c030000c3909090")
            + MONEY_CHECK
            + b"\x90" * (208 - 0x59)
        )
        put_call(block, WEEK + 0x0A, M_BOOKINGS)
    else:
        block[WEEK : WEEK + 208] = bytes(0 if b is None else b for b in p.MONEY_WEEK_ORIGINAL)
        for at, target in ((0x0D, FIRST), (0xB6, second), (0xC1, THIRD)):
            put_call(block, WEEK + at, target)
    block[BOOKING : BOOKING + 8] = bytes.fromhex("e80000000083c408")
    put_call(block, BOOKING, SECOND)
    if booking_patched:
        block[BOOKING + 8 : BOOKING + 31] = b"\0" * 5 + b"\x90" * 18
        put_call(block, BOOKING + 8, WEEK + 0x20, 0xE9)
    else:
        block[BOOKING + 8 : BOOKING + 31] = bytes.fromhex("8b865401000003c75f8986540100005e5b83c424c39090")
    return bytes(block)


def apply_sites(image, sites):
    image = bytearray(image)
    for at, _, new, _ in sites:
        image[at : at + len(new)] = new
    return bytes(image)


def test_money_sites():
    original = money_block()
    sites = p.money_sites(original)
    assert [(s[0], s[3]) for s in sites] == [(WEEK, False), (BOOKING + 8, False)]
    patched = apply_sites(original, sites)
    assert patched == money_block(week_patched=True, booking_patched=True)
    again = p.money_sites(patched)
    assert all(s[3] for s in again) and [s[:3] for s in again] == [s[:3] for s in sites]
    assert apply_sites(patched, [(at, None, old, None) for at, old, _, _ in again]) == original  # taken back


def test_money_sites_one_place_patched():
    for week, booking in ((True, False), (False, True)):
        sites = p.money_sites(money_block(week, booking))
        assert [s[3] for s in sites] == [week, booking]
        assert apply_sites(money_block(week, booking), sites) == money_block(True, True)


def test_money_sites_unknown():
    assert p.money_sites(money_block() * 2) is None
    assert p.money_sites(money_block()[:BOOKING]) is None  # no booking
    assert p.money_sites(money_block(second=THIRD)) is None  # the week's result calls something else
    other = bytearray(money_block())
    other[M_BOOKINGS + 0x20] ^= 1  # not the bookings where expected
    assert p.money_sites(bytes(other)) is None
    moved = bytearray(money_block(booking_patched=True))
    put_call(moved, BOOKING + 8, WEEK + 0x21, 0xE9)  # the booking jumps elsewhere
    assert p.money_sites(bytes(moved)) is None
    first_elsewhere = bytearray(money_block(week_patched=True))
    put_call(first_elsewhere, M_BOOKINGS + 0x07, SECOND)  # the bookings' first call isn't 0x100 in front
    assert p.money_sites(bytes(first_elsewhere)) is None
    far = bytearray(money_block(week_patched=True))
    put_call(far, WEEK + 0x0A, 0x10000)  # the bookings would lie behind the end
    assert p.money_sites(bytes(far)) is None


# --- rewrites that move a call (A2G-Patch's RewritePatch.FindOnce) --------------------------------

W = None  # a wildcard


def test_rewrite_site_moves_a_call_displacement():
    original = [0xE8, W, W, W, W, 0x90, 0x90, 0x6A, W]  # call x / nop / nop / push imm8
    patched = [0x90, 0x90, 0xE8, W, W, W, W, 0x6A, W]  # nop / nop / call x / push imm8
    image = filler(16) + bytes.fromhex("e800010000") + bytes.fromhex("90906a07") + filler(16)
    at, old, new, done = p.rewrite_site(image, original, patched)
    assert (at, done) == (16, False) and old == image[16:25]
    assert new == bytes.fromhex("9090e8fe0000006a07")  # 16+5+0x100 == 18+5+0xFE, the 07 kept
    back = image[:16] + new + image[25:]
    assert p.rewrite_site(back, original, patched) == (16, old, new, True)


def test_rewrite_site_keeps_other_wildcards_in_order():
    # five wildcards behind E8 are no displacement, nor are four behind a push
    for original, patched in (
        ([0xE8, W, W, W, W, W, 0x90], [0x90, 0xE8, W, W, W, W, W]),
        ([0x68, W, W, W, W, 0x90], [0x90, 0xE8, W, W, W, W]),
    ):
        image = filler(4) + bytes(original[0:1]) + bytes(range(1, len(original) - 1)) + b"\x90" + filler(4)
        _, old, new, _ = p.rewrite_site(image, original, patched)
        assert new[2:] == old[1:-1]


def test_rewrites_sites_needs_every_place():
    a, b = ([0x0F, 0x0B, 0x01], [0x0F, 0x0B, 0x02]), ([0x0F, 0x0B, 0x03], [0x0F, 0x0B, 0x04])
    assert p.rewrites_sites(bytes.fromhex("0f0b01cc0f0b04"), (a, b)) == [
        (0, b"\x0f\x0b\x01", b"\x0f\x0b\x02", False),
        (4, b"\x0f\x0b\x03", b"\x0f\x0b\x04", True),
    ]
    assert p.rewrites_sites(bytes.fromhex("0f0b01cc"), (a, b)) is None


# --- events, crashes, competence, grades, appearances, fish poisoning, manager events ---------------
# The patterns are A2G-Patch's (tests/test_real_exes.py compares them with Patches.cs); here each patch is
# applied to its places filled in, found as patched and taken back.

NEW_PLACES = {
    "events": p.EVENT_PLACES,
    "crashes": p.CRASH_PLACES,
    "competence": ((p.COMPETENCE_ORIGINAL, p.COMPETENCE_PATCHED),),
    "appearances": p.APPEARANCES_PLACES,
    "fish": ((p.FISH_ORIGINAL, p.FISH_PATCHED),),
    "manager": p.MANAGER_PLACES,
}


def concrete(pattern):
    """The pattern with its wildcards filled (none of them makes a call reach outside the image)."""
    return bytes(0x11 if b is None else b for b in pattern)


def places_image(key):
    if key == "grades":
        return filler(8).join([filler(0), p.GRADE_CODE, p.GRADE_CODE, filler(0)])
    return filler(8).join([filler(0)] + [concrete(o) for o, _ in NEW_PLACES[key]] + [filler(0)])


@pytest.mark.parametrize("key", list(NEW_PLACES) + ["grades"])
def test_new_patches_apply_and_take_back(key):
    find = p.PATCHES[key][1]
    original = places_image(key)
    sites = find(original)
    assert sites and not any(s[3] for s in sites)
    patched = apply_sites(original, sites)
    assert patched != original
    again = find(patched)
    assert all(s[3] for s in again) and [s[:3] for s in again] == [s[:3] for s in sites]
    assert apply_sites(patched, [(at, None, old, None) for at, old, _, _ in again]) == original
    assert find(original * 2) is None


@pytest.mark.parametrize("key", NEW_PLACES)
def test_new_patches_need_every_place(key):
    for i in range(len(NEW_PLACES[key])):
        image = places_image(key).replace(concrete(NEW_PLACES[key][i][0]), b"")
        assert p.PATCHES[key][1](image) is None


def test_new_patches_keep_their_call_targets():
    """Where a place moves a call (events 343, crashes, manager events), it still reaches the same target."""
    moved = 0
    for key, places in NEW_PLACES.items():
        image = places_image(key)
        for (original, patched), (at, old, new, _) in zip(places, p.PATCHES[key][1](image)):
            for k, (i, j) in enumerate(zip(p.holes(original), p.holes(patched))):
                if p.is_displacement(original, p.holes(original), k) and p.is_displacement(
                    patched, p.holes(patched), k
                ):
                    assert i + struct.unpack_from("<i", old, i)[0] == j + struct.unpack_from("<i", new, j)[0]
                    moved += i != j
    assert moved
