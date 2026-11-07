#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Patches anstoss2.exe (1999 CD) or run.exe (GOG, 2007 CD) of Anstoss 2 Gold on disk.

    a2patch.py [--sound] [--goals] [--disc-check] [--v101] <path to anstoss2.exe or run.exe>

--sound  "Ton über das Standard-Audiogerät von Windows" (bug fix): the game enumerates the sound
         devices and keeps the one with the most 3D hardware buffers. Every device reports 0, and on
         a tie the last one wins, so with several outputs (speakers, Bluetooth headphones, HDMI) the
         sound may go to the wrong one. The patch passes NULL instead of the kept GUID to
         DirectSoundCreate, which means the default device:

             push esi / push &ds / push &guid / call DirectSoundCreate ... mov [&ds],esi
             ->                    push esi / nop x4   (esi is 0 there, as the first push shows)

--goals  "Torgrenzen aufheben" (gameplay change): the match engine lets a team score only while it
         has fewer than 6 goals up to minute 45 and fewer than 10 after, and halves its chances from
         7 goals on. The patch raises the limit to 15 (the most a result nibble holds) and drops the
         halving:

             limit:  setg r8 / dec r32 / and r, -4 / add r, 10   ->  setg r8 / mov r32, 15 / nop...
             brakes: jle (7E)                                     ->  jmp (EB)

--disc-check  run.exe (GOG, 2007 CD) only, bug fix: run.exe is the game of the 2007 CD release, whose
         copy protection checks the CD in 11 places of the game (team names become "Raubkopie",
         players drop to strength 1, ...). Each check calls one signature routine and subtracts
         the expected value; zero (or more) means "original CD". GOG replaced the subtraction with
         NOPs, so the raw signature remains and the checks fail; run.exe of the 2007 CD (unpacked
         with src/a2unpack.py) still has the subtraction and fails as well, since a copy of the CD
         gives another signature. The patch puts in what a passed check leaves, as the 1999 CD
         version (which has none of these checks) behaves:

             call check / mov r32,eax / add esp,4 / {nop x6 | sub r32,imm32}  ->  ... / xor r32,r32 / nop x4
             call check / add esp,4 / {nop x5 | sub eax,imm32} / mov [..],eax ->  ... / xor eax,eax / nop x3 / ...

--v101   run.exe (GOG, 2007 CD) only: the program changes of patch 1.01 (run.exe is built from the
         1.00 source). The code is in src/a2v101.S, assembled by src/a2v101build.py into
         src/a2v101.json (no GNU binutils needed here); it is moved to the address of a new section
         ".a2v101" appended to run.exe, and 12 places jump there (see V101_HOOKS). A 13th place
         makes the cup draw load archives/movelist.dat from the game folder instead of the CD, as
         1.01 does (the file comes with patch 1.01, see src/a2data101.py). GOG's signature
         at the end of the file, invalid after any patch, is replaced by the section.

Integrity of run.exe (GOG, 2007 CD, automatic): the 2007 release checks its own program in two ways.
         Five places compute a CRC32 of run.exe on disk (from offset 0x80 to the end) and compare it with
         the value stored at offset 0x7c; five others compute a CRC32 of a stretch of their own code and
         compare it with a value stored in front of it. On a mismatch the game silently skips work,
         doubles negative values (0x418ca0) or runs into garbage. GOG's unpacked run.exe already fails
         all of them (GOG disabled four of the code checks, not the others), run.exe of the 2007 CD fails
         the file checks once it is unpacked or patched. Whenever run.exe is written,
         a2patch.py therefore stores the correct values, so the checks pass as with the untouched original.

Port of the first two patches from A2G-Patch by transfairs (GPLv3,
https://github.com/transfairs/A2G-Patcher, Patches.cs and GameInstall.cs). Like A2G-Patch, it writes
the backup anstoss2.exe.vor-a2g-patch first, so A2G-Patch recognizes the result and can take the
patches back. Each place must occur exactly once and hold either the original or the patched bytes;
otherwise nothing is written.
"""

import argparse
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from a2v101build import relocate  # noqa: E402

BACKUP_SUFFIX = ".vor-a2g-patch"
NOP = 0x90


def find_all(image, pattern):
    """Every start of pattern in image; None entries in pattern match any byte."""
    regex = re.compile(
        b"(?=" + b"".join(b"." if b is None else re.escape(bytes([b])) for b in pattern) + b")", re.DOTALL
    )
    return [m.start() for m in regex.finditer(image)]


# --- Goal limits --------------------------------------------------------------
MAX_GOALS = 15
JLE, JMP = 0x7E, 0xEB
# The instructions right before each rewritten byte.
LIMIT_PATTERN = bytes([0x66, 0x83, 0x7F, 0x08, 0x2D, 0x57, 0x6A, 0x01, 0x0F, 0x9F])
HOME_BRAKE_PATTERN = bytes([0x66, 0x83, 0x7E, 0x0E, 0x06, 0x89, 0x44, 0x24, 0x30])
AWAY_BRAKE_PATTERN = bytes([0x66, 0x8B, 0x56, 0x10, 0x83, 0xC4, 0x04, 0x66, 0x83, 0xFA, 0x06, 0x8B, 0xC8])


def after(image, pattern):
    """The position right after the pattern's only occurrence, or None."""
    found = find_all(image, pattern)
    return found[0] + len(pattern) if len(found) == 1 else None


def limit_originals(register):
    # dec r32 / and r, -4 / add r, 10; with eax the compiler may use the short "and al, -4".
    # The long form comes first: patched, the short form is a prefix of it.
    add = bytes([0x83, 0xC0 + register, 0x0A])
    long_form = bytes([0x48 + register, 0x83, 0xE0 + register, 0xFC]) + add
    return [long_form, bytes([0x48, 0x24, 0xFC]) + add] if register == 0 else [long_form]


def limit_patched(register, length):
    # mov r32, 15, padded with nops to the original's length.
    return bytes([0xB8 + register]) + struct.pack("<i", MAX_GOALS) + bytes([NOP] * (length - 5))


def goal_sites(image):
    """[(offset, original, patched, is_patched)] or None if the exe doesn't match."""
    limit, home, away = (after(image, p) for p in (LIMIT_PATTERN, HOME_BRAKE_PATTERN, AWAY_BRAKE_PATTERN))
    if limit is None or home is None or away is None:
        return None
    # limit is setg's ModR/M byte (C0+r); the rewritten instructions follow it.
    if limit + 8 > len(image) or not 0xC0 <= image[limit] <= 0xC3:
        return None
    register = image[limit] - 0xC0
    sites = []
    for original in limit_originals(register):
        patched = limit_patched(register, len(original))
        current = image[limit + 1 : limit + 1 + len(original)]
        if current in (original, patched):
            sites.append((limit + 1, original, patched, current == patched))
            break
    else:
        return None
    for at in (home, away):
        if at >= len(image) or image[at] not in (JLE, JMP):
            return None
        sites.append((at, bytes([JLE]), bytes([JMP]), image[at] == JMP))
    return sites


# --- Default sound device -------------------------------------------------------
GUID_AT = 6  # where "push &guid" starts
GUID_BEFORE_POINTER = 0x18  # the kept GUID lies 0x18 bytes before the DirectSound pointer
SOUND_PATCHED = bytes([0x56, NOP, NOP, NOP, NOP])  # push esi (0) / nop x4


def sound_pattern(guid):
    # push esi / push &ds / {push &guid | push esi, nop x4} / call / test eax,eax / je +15 / call / mov [&ds],esi
    return (
        [0x56, 0x68, None, None, None, None]
        + list(guid)
        + [0xE8, None, None, None, None, 0x85, 0xC0, 0x74, 0x15]
        + [0xE8, None, None, None, None, 0x89, 0x35, None, None, None, None]
    )


def sound_sites(image):
    original = find_all(image, sound_pattern([0x68, None, None, None, None]))
    patched = find_all(image, sound_pattern(SOUND_PATCHED))
    if len(original) + len(patched) != 1:
        return None
    is_patched = len(patched) == 1
    at = patched[0] if is_patched else original[0]
    pointer = struct.unpack_from("<i", image, at + 2)[0]
    # Both mentions of the pointer must agree, and the GUID must sit where it's expected.
    if struct.unpack_from("<i", image, at + 27)[0] != pointer:
        return None
    push = bytes([0x68]) + struct.pack("<i", pointer - GUID_BEFORE_POINTER)
    if not is_patched and image[at + GUID_AT : at + GUID_AT + len(push)] != push:
        return None
    return [(at + GUID_AT, push, SOUND_PATCHED, is_patched)]


# --- CD checks of the 2007 release (GOG, 2007 CD) -------------------------------------
DISC_CHECKS = 11
ADD_ESP_4 = bytes([0x83, 0xC4, 0x04])
MOV_FROM_EAX = {0xF0: 6, 0xD8: 3, 0xF8: 7}  # ModR/M of "mov esi|ebx|edi, eax" -> register number


def disc_check_sites(image):
    """The 11 checks after calls of the signature routine, or None if the exe doesn't match."""
    found = {}
    for m in re.finditer(re.compile(b"\xe8(....)(?:\x8b([\xf0\xd8\xf8]))?\x83\xc4\x04", re.DOTALL), image):
        target = m.start() + 5 + struct.unpack("<i", m.group(1))[0]
        after = m.end()
        modrm = m.group(2)
        if modrm:  # mov r32,eax: 6 bytes "sub r32, imm32" follow
            register, length = MOV_FROM_EAX[modrm[0]], 6
        else:  # eax itself: 5 bytes "sub eax, imm32" follow
            register, length = 0, 5
        current = image[after : after + length]
        patched = bytes([0x31, 0xC0 + register * 9]) + bytes([NOP] * (length - 2))  # xor r32,r32
        # sub r32,imm32 (2007 CD) or the NOPs GOG put there
        sub = bytes([0x81, 0xE8 + register]) if modrm else bytes([0x2D])
        if current in (bytes([NOP] * length), patched) or current.startswith(sub):
            found.setdefault(target, []).append((after, current, patched, current == patched))
    sites = [v for v in found.values() if len(v) == DISC_CHECKS]
    return sites[0] if len(sites) == 1 else None


# --- Patch 1.01 for run.exe (GOG, 2007 CD) ---------------------------------------------
V101_SECTION = b".a2v101\0"
V101_PREBUILT = os.path.join(HERE, "a2v101.json")  # src/a2v101.S assembled by src/a2v101build.py
JMP_REL32 = 0xE9
# (address in run.exe, original bytes, symbol in a2v101.S or None for an in-place change, new bytes)
# fmt: off
V101_HOOKS = [
    (0x412DD0, "81ecf8090000", "fix_412dd0", None),             # sub esp,0x9f8 (whole function)
    (0x415F96, "74338a4e04", "fix_415f96", None),               # je / mov cl,[esi+4]
    (0x4160BD, "74328a066a01", "fix_4160bd", None),             # je / mov al,[esi] / push 1
    (0x501DCF, "7454", None, "eb54"),                           # je -> jmp: message 0xa41 is gone
    (0x557E3F, "808eae00000001", "fix_557e3f", None),           # or byte ptr [esi+0xae],1
    (0x557E64, "668b4e6083c4146601 4e5e", None, "83c41466ff465e90909090"),  # +=[esi+0x60] -> inc
    (0x568CA0, "83ec085355", "fix_568ca0", None),               # whole function
    (0x5A0BF7, "6a008d8c2478030000", "fix_5a0bf7", None),       # push 0 / lea ecx,[esp+0x378]
    (0x5A0F95, "e816d00c00", "fix_5a0f95", None),               # call 0x66dfb0 (DoModal)
    (0x5A2836, "33c98a4e208a91585a6c00885621", "fix_5a2836", None),  # alternative position
    (0x5A2FC0, "568b742408", "fix_5a2fc0", None),               # whole function
    (0x5BD540, "b86c9f0000", "fix_5bd540", None),               # mov eax,0x9f6c (wrapped)
    (0x468A4E, "688c097000", None, "6870097000"),               # movelist.dat: CD path -> game folder
]
# fmt: on


def pe_layout(image):
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    nsec = struct.unpack_from("<H", image, pe + 6)[0]
    opt = pe + 24
    table = opt + struct.unpack_from("<H", image, pe + 20)[0]
    sections = [struct.unpack_from("<8sIIII", image, table + 40 * i) for i in range(nsec)]
    return pe, nsec, opt, table, sections


def va_offset(sections, va):
    rva = va - 0x400000
    for _, vsize, vaddr, rsize, raw in sections:
        if vaddr <= rva < vaddr + min(vsize, rsize):
            return raw + rva - vaddr
    return None


def load_v101(address):
    """(code, {symbol: address}) of the prebuilt src/a2v101.json, moved to address."""
    with open(V101_PREBUILT) as f:
        return relocate(json.load(f), address)


def v101_state(image):
    """ "patched", "original" or None (unknown exe)."""
    _, _, _, _, sections = pe_layout(image)
    if any(name == V101_SECTION for name, *_ in sections):
        return "patched"
    for va, original, _, _ in V101_HOOKS:
        at = va_offset(sections, va)
        want = bytes.fromhex(original.replace(" ", ""))
        if at is None or image[at : at + len(want)] != want:
            return None
    return "original"


def apply_v101(image):
    """image with the section added and the places redirected to it."""
    pe, nsec, opt, table, sections = pe_layout(bytes(image))
    if table + 40 * (nsec + 1) > sections[0][4]:
        sys.exit("no room for another section header")
    size_of_image = struct.unpack_from("<I", image, opt + 56)[0]
    va = 0x400000 + size_of_image
    code, symbols = load_v101(va)
    raw = max(r + s for _, _, _, s, r in sections)  # end of the section data
    sec_dir = opt + 96 + 4 * 8  # certificate table (GOG's signature)
    cert_at, cert_size = struct.unpack_from("<II", image, sec_dir)
    if cert_at and cert_at >= raw:
        struct.pack_into("<II", image, sec_dir, 0, 0)
    del image[raw:]
    raw_size = (len(code) + 0x1FF) & ~0x1FF
    image += code + bytes(raw_size - len(code))
    header = (V101_SECTION, len(code), size_of_image, raw_size, raw, 0, 0, 0, 0)
    flags = 0xE0000020  # code, execute, read, write
    struct.pack_into("<8sIIIIIIHHI", image, table + 40 * nsec, *header, flags)
    struct.pack_into("<H", image, pe + 6, nsec + 1)
    struct.pack_into("<I", image, opt + 56, size_of_image + ((len(code) + 0xFFF) & ~0xFFF))
    for hook_va, original, symbol, new in V101_HOOKS:
        at = va_offset(sections, hook_va)
        length = len(bytes.fromhex(original.replace(" ", "")))
        if symbol:
            rel = symbols[symbol] - (hook_va + 5)
            patch = bytes([JMP_REL32]) + struct.pack("<i", rel) + bytes([NOP] * (length - 5))
        else:
            patch = bytes.fromhex(new)
        if len(patch) != length:
            sys.exit(f"1.01: patch at {hook_va:#x} has {len(patch)} bytes instead of {length}")
        image[at : at + length] = patch
    return image


# --- Integrity values of run.exe (GOG, 2007 CD) -------------------------------------------
# Code self-checks: a stub "sub esp,0xc0 / push ebx,ebp,esi,edi / mov ebp,esp" right after a
# descriptor {CRC, ?, length}; the checked code starts at the stub.
SELF_CHECK_STUB = bytes.fromhex("81ecc0000000535556578bec")
SELF_CHECKS = 5
FILE_CRC_AT = 0x7C


def crc32_raw(data):
    """CRC32 without the final inversion, as the game computes it (start value 0xffffffff)."""
    import zlib

    return zlib.crc32(data) ^ 0xFFFFFFFF


def integrity_sites(image):
    """File offsets of the code self-check descriptors, or None if this is not run.exe of 2007 (GOG, CD)."""
    _, _, _, _, sections = pe_layout(image)
    text = sections[0]
    code = image[text[4] : text[4] + min(0x2B0000, text[3])]
    found = [m.start() + text[4] - 0xC for m in re.finditer(re.escape(SELF_CHECK_STUB), code)]
    return found if len(found) == SELF_CHECKS else None


def fix_integrity(image):
    """Stores the CRC values the integrity checks of run.exe expect; returns the image."""
    for desc in integrity_sites(bytes(image)):
        length = struct.unpack_from("<I", image, desc + 8)[0]
        struct.pack_into("<I", image, desc, crc32_raw(bytes(image[desc + 0xC : desc + 0xC + length])))
    import zlib

    struct.pack_into("<I", image, FILE_CRC_AT, zlib.crc32(bytes(image[0x80:])))  # must come last
    return image


PATCHES = {
    "sound": ("default sound device", sound_sites),
    "goals": ("goal limits lifted", goal_sites),
    "disc_check": ("CD checks of the 2007 release pass", disc_check_sites),
}


def main():
    ap = argparse.ArgumentParser(description="Patches anstoss2.exe (port from A2G-Patch).")
    ap.add_argument("--sound", action="store_true", help="play sound on the default audio device")
    ap.add_argument("--goals", action="store_true", help="lift the goal limits")
    ap.add_argument("--disc-check", action="store_true", help="run.exe of 2007 (GOG, CD): let the CD checks pass")
    ap.add_argument("--v101", action="store_true", help="run.exe of 2007 (GOG, CD): program changes of patch 1.01")
    ap.add_argument("exe")
    a = ap.parse_args()
    wanted = [k for k in PATCHES if getattr(a, k)]
    if not wanted and not a.v101:
        ap.error("no patch selected")

    image = bytearray(open(a.exe, "rb").read())
    changes = []
    for key in wanted:
        name, find = PATCHES[key]
        sites = find(bytes(image))
        if sites is None:
            sys.exit(f"{a.exe}: unknown version, patch '{name}' does not fit. Nothing was changed.")
        if all(s[3] for s in sites):
            print(f"{a.exe}: {name}: already patched")
        else:
            changes += sites
            print(f"{a.exe}: {name}: patched")
    v101 = False
    if a.v101:
        state = v101_state(bytes(image))
        if state is None:
            sys.exit(f"{a.exe}: unknown version, patch 'program changes of 1.01' does not fit. Nothing was changed.")
        if state == "patched":
            print(f"{a.exe}: program changes of 1.01: already patched")
        else:
            v101 = True
            print(f"{a.exe}: program changes of 1.01: patched")
    gog = disc_check_sites(bytes(image)) is not None and integrity_sites(bytes(image)) is not None
    if not changes and not v101 and not (gog and bytes(fix_integrity(bytearray(image))) != bytes(image)):
        return
    if not os.path.exists(a.exe + BACKUP_SUFFIX):
        shutil.copy2(a.exe, a.exe + BACKUP_SUFFIX)
    for offset, _, patched, _ in changes:
        image[offset : offset + len(patched)] = patched
    if v101:
        image = apply_v101(image)
    if gog:
        image = fix_integrity(image)
        print(f"{a.exe}: integrity values updated")
    tmp = a.exe + ".tmp"
    with open(tmp, "wb") as f:
        f.write(image)
    shutil.copymode(a.exe, tmp)
    os.replace(tmp, a.exe)
    print(f"Backup of the original: {os.path.basename(a.exe) + BACKUP_SUFFIX}")


if __name__ == "__main__":
    main()
