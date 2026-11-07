#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Gives the dialogs in the RESDLL.dll of the GOG version the window styles of the 1999 CD release.

    a2resdll.py <game folder>

All dialogs of the game are templates in RESDLL.dll. In the file of the GOG version, they lack
styles the 1999 file has (found by comparing the two files; the values below are own data):

- Title bar (WS_CAPTION) on 342 dialogs and DS_MODALFRAME on 65 of them. GOG's file has DS_CENTER
  on 75 dialogs, the 1999 file on 15: the game itself centers every dialog with a title bar over its
  main window (in OnInitDialog). Five dialogs also get back DS_SYSMODAL, DS_FIXEDSYS, DS_3DLOOK or
  DS_SETFOREGROUND, one loses WS_EX_TOPMOST.
- The sunken frame (WS_EX_CLIENTEDGE) around 68 controls: the choices that look like buttons (e.g.
  "Frei (Vorsaison voreingestellt)" for the shirt numbers) and boxes with values. Two of them have
  WS_BORDER in GOG's file instead.
- WS_EX_TRANSPARENT on 16 radio buttons and group boxes of one dialog (598).
- Font of the dialogs: character set DEFAULT_CHARSET instead of ANSI_CHARSET and the name
  "MS Sans Serif" instead of "MS SANS SERIF".
- Controls without an ID have -1 as a 32-bit value (0xffffffff instead of 0xffff), three titles
  use double instead of single quotes.

Not changed: texts of different length (version "1.0" in the info dialog, "Championsleague",
string 6390 "Managerkarriere") and four pictures, all of which the 2007 release changed on purpose.

Everything is changed in place, the file keeps its size. Input and result are checked against
their SHA-256; on a mismatch the file is left unchanged and the exit code is 1. The original is
kept as RESDLL.dll.vor-dialoge.
"""

import hashlib
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from a2import import match  # noqa: E402

BACKUP_SUFFIX = ".vor-dialoge"
# fmt: off
GOG = "e47e0802188c00b51b227675c172b4fb05bf92af9b3feba95aba3f293c135aae"      # GOG 1.0 fix2
RESULT = "31b058abfc46c3bca421e85952ba57a517292ca7ae2ff6be009dc563d1015adc"   # this script

DE, EN, GB = 1031, 1033, 2057
WS_CAPTION, WS_BORDER = 0x00C00000, 0x00800000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_CLIENTEDGE = 0x08, 0x20, 0x200
DEFAULT_CHARSET = 1

# Dialogs without a title bar in the 1999 file as well
CAPTIONLESS = {
    DE: (108, 129, 181, 183, 188, 189, 196, 203, 221, 228, 229, 236, 263, 266, 276, 279, 291, 304,
         305, 306, 320, 321, 327, 382, 394, 407, 475, 476, 503, 515, 519, 520, 536, 591, 594, 597,
         601, 602, 605, 624, 625, 630, 631, 633),
    EN: (205, 206, 226, 621),
}
# Dialogs whose style differs by more than WS_CAPTION: (style in GOG's file, style of 1999) -> dialogs
STYLES = {
    (0x90080840, 0x90C800C0): {DE: (116, 119, 200, 202, 209, 210, 224, 265, 270, 271, 274, 275, 289,
                                    290, 302, 329, 331, 344, 346, 379, 388, 396, 405, 406, 428, 445,
                                    473, 478, 508, 509, 513, 517, 524, 531, 532, 559, 567, 570, 574,
                                    575, 576, 592, 603, 606, 608, 609, 613, 620, 626)},
    (0x900A0840, 0x90CA00C0): {DE: (297, 314, 332, 378, 479, 482, 541)},
    (0x900A0040, 0x90CA00C0): {DE: (102, 571)},
    (0x90080040, 0x90C800C0): {DE: (223, 492)},
    (0x908A0A40, 0x90CA02C0): {DE: (319,)},
    (0x90080840, 0x90C802C0): {DE: (337,)},
    (0x90000840, 0x90C002C0): {DE: (505,)},
    (0x90080840, 0x90C80AC0): {DE: (549,)},
    (0x44000040, 0x44000240): {DE: (611,)},
    (0x800800C0, 0x80C800C4): {DE: (30721,)},
    (0x80080840, 0x80C800C0): {GB: (231,)},
}
EX_STYLES = {(DE, 613): (0x00040008, 0x00040000)}      # WS_EX_TOPMOST removed
# Controls (index in the dialog) that get WS_EX_CLIENTEDGE back
CLIENTEDGE = {
    DE: {116: (55, 56, 94), 193: (15, 16), 200: (45, 46), 234: (13,), 244: (4,), 262: (0, 1, 3),
         283: (16,), 302: (2,), 322: (50,), 369: (2, 3, 4), 371: (6, 7, 8), 383: (1, 2, 3),
         390: (2,), 396: (44, 45), 403: (17, 18, 19), 404: (1, 2, 3), 433: (4,), 440: (8, 9),
         466: (1,), 470: (1, 2, 3), 484: (1, 3), 487: (1, 2, 3), 490: (1, 2), 491: (1, 2, 3),
         510: (19,), 516: (38, 39), 541: (2,), 575: (34,), 576: (17,), 581: (4, 5, 6), 583: (2, 3),
         588: (25, 27), 596: (1, 2), 635: (5,)},
    GB: {231: (9, 10)},
}
BORDER_INSTEAD = {(DE, 490): (1, 2)}                   # have WS_BORDER in GOG's file instead
TRANSPARENT = {(DE, 598): (0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)}
KEEP_ID = {(DE, 382): (5,)}                            # 0xffff in the 1999 file as well
QUOTES = ((DE, 237), (DE, 296), (DE, 593))             # title: ' -> "
# fmt: on
FACE_GOG, FACE = "MS SANS SERIF", "MS Sans Serif"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dialogs(pe):
    """(language, dialog id, file offset, size) of all dialog templates of the DLL."""
    peo = struct.unpack_from("<I", pe, 0x3C)[0]
    nsec, optsize = struct.unpack_from("<H", pe, peo + 6)[0], struct.unpack_from("<H", pe, peo + 20)[0]
    opt = peo + 24
    rsrc_rva = struct.unpack_from("<I", pe, opt + 96 + 2 * 8)[0]
    sections = [struct.unpack_from("<IIII", pe, opt + optsize + 40 * i + 8) for i in range(nsec)]

    def offset(rva):
        for vsize, va, rawsize, raw in sections:
            if va <= rva < va + max(vsize, rawsize):
                return raw + rva - va
        raise ValueError(f"RVA {rva:#x} outside the sections")

    base = offset(rsrc_rva)

    def entries(at):
        named, ids = struct.unpack_from("<HH", pe, base + at + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from("<II", pe, base + at + 16 + 8 * i)
            yield name, target

    for rtype, tdir in entries(0):
        if rtype != 5 or not tdir & 0x80000000:  # RT_DIALOG
            continue
        for did, ldir in entries(tdir & 0x7FFFFFFF):
            for lang, data in entries(ldir & 0x7FFFFFFF):
                rva, size = struct.unpack_from("<II", pe, base + data)
                yield lang, did, offset(rva), size


def string_end(b, o):
    """Offset after a name or ordinal field of a template."""
    if struct.unpack_from("<H", b, o)[0] == 0xFFFF:
        return o + 4
    while struct.unpack_from("<H", b, o)[0]:
        o += 2
    return o + 2


class Mismatch(Exception):
    pass


def put(b, o, fmt, old, new):
    if struct.unpack_from(fmt, b, o)[0] != old:
        raise Mismatch(f"{struct.unpack_from(fmt, b, o)[0]:#x} instead of {old:#x} at {o:#x}")
    struct.pack_into(fmt, b, o, new)


def in_table(table, lang, did):
    return did in table.get(lang, ())


def fix_dialog(b, o, lang, did):
    """Changes the template at offset o of bytearray b."""
    key = (lang, did)
    ex = struct.unpack_from("<HH", b, o) == (1, 0xFFFF)
    st_at, exst_at, count_at = (o + 12, o + 8, o + 16) if ex else (o, o + 4, o + 8)
    style = struct.unpack_from("<I", b, st_at)[0]
    target = [cd for (gog, cd), table in STYLES.items() if in_table(table, lang, did)]
    if target:
        old = [gog for (gog, cd), table in STYLES.items() if in_table(table, lang, did)][0]
        put(b, st_at, "<I", old, target[0])
    elif not in_table(CAPTIONLESS, lang, did) and not style & WS_CAPTION:
        put(b, st_at, "<I", style, style | WS_CAPTION)
    if key in EX_STYLES:
        put(b, exst_at, "<I", *EX_STYLES[key])
    count = struct.unpack_from("<H", b, count_at)[0]
    p = string_end(b, string_end(b, count_at + 10))  # menu, class
    title, p = p, string_end(b, p)
    if key in QUOTES:
        text = b[title : p - 2].decode("utf-16le")
        if "'" not in text:
            raise Mismatch(f"title of dialog {did} without '")
        b[title : p - 2] = text.replace("'", '"').encode("utf-16le")
    if struct.unpack_from("<I", b, st_at)[0] & 0x40:  # DS_SETFONT
        if ex:
            if b[p + 5] != DEFAULT_CHARSET:
                put(b, p + 5, "<B", 0, DEFAULT_CHARSET)
            p += 6
        else:
            p += 2
        end = string_end(b, p)
        face = b[p : end - 2].decode("utf-16le")
        if face == FACE_GOG:
            b[p : end - 2] = FACE.encode("utf-16le")
        p = end
    for i in range(count):
        p = (p + 3) & ~3
        if ex:
            exst_c, st_c, id_c, p = p + 4, p + 8, p + 20, p + 24
        else:
            st_c, exst_c, id_c, p = p, p + 4, p + 16, p + 18
        if ex and struct.unpack_from("<I", b, id_c)[0] == 0xFFFF and i not in KEEP_ID.get(key, ()):
            put(b, id_c, "<I", 0xFFFF, 0xFFFFFFFF)
        exst = struct.unpack_from("<I", b, exst_c)[0]
        if i in CLIENTEDGE.get(lang, {}).get(did, ()):
            put(b, exst_c, "<I", exst & ~WS_EX_CLIENTEDGE, exst | WS_EX_CLIENTEDGE)
        if i in TRANSPARENT.get(key, ()):
            put(b, exst_c, "<I", exst & ~WS_EX_TRANSPARENT, exst | WS_EX_TRANSPARENT)
        if i in BORDER_INSTEAD.get(key, ()):
            st = struct.unpack_from("<I", b, st_c)[0]
            put(b, st_c, "<I", st | WS_BORDER, st & ~WS_BORDER)
        p = string_end(b, string_end(b, p))  # class, text
        p += 2 + struct.unpack_from("<H", b, p)[0]  # creation data


def restore(pe):
    """The DLL with the dialog styles of 1999, or None if the file does not match."""
    b = bytearray(pe)
    try:
        for lang, did, o, size in dialogs(pe):
            fix_dialog(b, o, lang, did)
    except (Mismatch, struct.error, ValueError, UnicodeDecodeError) as e:
        print(f"RESDLL.dll: {e}")
        return None
    return bytes(b)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    game = sys.argv[1]
    path = os.path.join(game, match(game, "RESDLL.dll"))
    if not os.path.isfile(path):
        sys.exit("RESDLL.dll: missing")
    backup = path + BACKUP_SUFFIX
    with open(path, "rb") as f:
        current = f.read()
    if sha(current) == RESULT:
        print("RESDLL.dll: dialog styles of 1999 already there")
        return
    src = current
    if os.path.exists(backup):
        with open(backup, "rb") as f:
            src = f.read()
    if sha(src) != GOG:
        print("RESDLL.dll is not the file of the GOG version, dialog styles left unchanged")
        sys.exit(1)
    result = restore(src)
    if result is None or sha(result) != RESULT:
        print("RESDLL.dll: unexpected result, dialog styles left unchanged")
        sys.exit(1)
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    with open(path, "wb") as f:
        f.write(result)
    print("RESDLL.dll: dialog styles of 1999")


if __name__ == "__main__":
    main()
