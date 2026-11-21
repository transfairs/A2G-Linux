#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Brings the data files of the GOG version to patch 1.01.

    a2data101.py <game folder>

Patch 1.01 changes three data files; all three are made here from the GOG files and own code:

- TEXTE/EreigGld.saq (event texts; run.exe reads the same file as TEXTE/EreigGold.saq): two texts end
  with "." instead of ":". The file is decrypted (each byte XOR the previous encrypted byte, starting
  with the low byte of the length), the two characters are changed and the file is encrypted again;
  written under both names. The result is identical to the file of patch 1.01. The file is known by
  its texts without the changes of src/a2texts.py, which stay.
- DATA.DEF/LAENDER.SAV, DATA.VER/LAENDER.SAV: one value changes from 3 to 4 (identical to 1.01).
- ARCHIVES/MoveList.dat: new in 1.01, the animation of the sign in the video window
  of the cup draw. Computed by src/a2movelist.py (see there; inside the sign at most one pixel off
  the file of 1.01).

Inputs and results are checked against their SHA-256; on a mismatch the file is left unchanged and
the exit code is 1. Originals are kept as <name>.vor-1.01.
"""

import hashlib
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import a2movelist  # noqa: E402
import a2texts  # noqa: E402
from a2import import match  # noqa: E402

BACKUP_SUFFIX = ".vor-1.01"
# fmt: off
EVENTS = ("f7d1b920fe90881a78a949748940185cc0c3bf3276b8511fc4544b723cbf04f5",   # GOG 1.0 fix2
          "df6a3684216271716d792e10e5b14a449701a92888c81fca2aba73078a9a6d0e")   # 1.01
EVENT_TEXTS = (10, 55)                  # texts whose ":" at the end becomes "."
LAENDER = ("fe8818ea7024ad4650fb274501e6f6b524f6299249d2815d83f3124517a6a27f",
           "13762d5b8158a89952a1e724fc1a65046d0fd3a2e122089c6accc4d328d14675")
LAENDER_AT, LAENDER_OLD, LAENDER_NEW = 2065, ord("3"), ord("4")
MOVELIST = "832ea122aac02ce4f8fad4936351cd8ed91ed9991b0e2233cf210b1526859920"   # src/a2movelist.py
# fmt: on


def sha(data):
    return hashlib.sha256(data).hexdigest()


def game_path(game, rel):
    """rel inside the game folder, with the case the files there have."""
    path = game
    for part in rel.split("/"):
        path = os.path.join(path, match(path, part))
    return path


def read(path):
    """The contents of the file at path."""
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    """Writes data to path; an existing file is kept as <path>.vor-1.01 unless that backup exists already."""
    if os.path.exists(path) and not os.path.exists(path + BACKUP_SUFFIX):
        shutil.copy2(path, path + BACKUP_SUFFIX)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def original(path):
    """The GOG file: the backup if an earlier run replaced it already."""
    return path + BACKUP_SUFFIX if os.path.exists(path + BACKUP_SUFFIX) else path


def events_101(data):
    """The event file of 1.01 made from the one of 1.00."""
    length, count = struct.unpack_from("<ii", data, 0)
    key, plain = length & 0xFF, bytearray()
    for b in data[8 : 8 + length]:
        plain.append(key ^ b)
        key = b
    texts = bytes(plain).split(b"\0")
    for i in EVENT_TEXTS:
        if not texts[i].endswith(b":"):
            return None
        texts[i] = texts[i][:-1] + b"."
    key, out = length & 0xFF, bytearray()
    for p in b"\0".join(texts):
        key = p ^ key
        out.append(key)
    return data[:8] + bytes(out) + data[8 + length :]


def laender_101(data):
    """LAENDER.SAV of 1.01 made from the one of 1.00 ("3" -> "4"), or None if that byte is not "3"."""
    if len(data) <= LAENDER_AT or data[LAENDER_AT] != LAENDER_OLD:
        return None
    data = bytearray(data)
    data[LAENDER_AT] = LAENDER_NEW
    return bytes(data)


def change(game, rels, make, hashes, label, plain=lambda data: data):
    """Applies make() to the GOG file of rels[0] and writes the result to all rels; True if ok. The files are
    known by the SHA-256 of plain(data): for the event texts without the changes of src/a2texts.py, which
    stay (the current file is taken before the backup)."""
    gog, v101 = hashes
    current = game_path(game, rels[0])
    if not os.path.isfile(current):
        print(f"Patch 1.01: {rels[0]} missing")
        return False
    if all(os.path.isfile(game_path(game, r)) and sha(plain(read(game_path(game, r)))) == v101 for r in rels):
        print(f"Patch 1.01: {label} already applied")
        return True
    for src in (read(current), read(original(current))):
        if sha(plain(src)) in hashes:
            break
    else:
        print(f"Patch 1.01: {rels[0]} is not the file of the GOG version, {label} left out")
        return False
    result = make(src) if sha(plain(src)) == gog else src
    if result is None or sha(plain(result)) != v101:
        print(f"Patch 1.01: {label}: unexpected result, left out")
        return False
    for rel in rels:
        path = game_path(game, rel)
        if not os.path.isfile(path) or read(path) != result:
            write(path, result)
    print(f"Patch 1.01: {label}")
    return True


def main():
    """Brings the event texts, LAENDER.SAV and MoveList.dat of the game folder to 1.01; exit status 1 if one
    of them was left out."""
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    game = sys.argv[1]
    events = ["TEXTE/EreigGold.saq", "TEXTE/EreigGld.saq"]
    ok = change(game, events, events_101, EVENTS, "event texts", a2texts.plain_events)
    ok &= change(game, ["DATA.DEF/LAENDER.SAV", "DATA.VER/LAENDER.SAV"], laender_101, LAENDER, "LAENDER.SAV")
    movelist = game_path(game, "ARCHIVES/MoveList.dat")
    data = a2movelist.build()
    if sha(data) != MOVELIST:
        print("Patch 1.01: MoveList.dat: unexpected result, left out")
        ok = False
    elif os.path.isfile(movelist) and read(movelist) == data:
        print("Patch 1.01: MoveList.dat already there")
    else:
        write(movelist, data)
        print("Patch 1.01: MoveList.dat")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
