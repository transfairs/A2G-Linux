# SPDX-License-Identifier: GPL-3.0-only
"""The patches on the real game files, as the installer applies them. Skipped unless the files are named:

    A2G_CD_EXE       anstoss2.exe of the 1999 CD, unpatched (e.g. a backup anstoss2.exe.vor-a2g-patch)
    A2G_GOG_SETUP    GOG's installer setup_anstoss_2_gold_..._(48434).exe (needs innoextract)
    A2G_2007_DVD     the mounted DVD "ANSTOSS 2007" or a folder with its ANSTOSS_2_GOLD/Setup.exe (needs innoextract)
    A2G_INNOEXTRACT  innoextract, if it is not in PATH
    A2G_PATCHER      a checkout of A2G-Patch; then the 1.01 section is compared with its V101Code.cs and
                     the patterns of the rewrites with its Patches.cs

Everything happens on copies in pytest's tmp_path; the files themselves are only read. .github/pre-release.sh
sets these from the usual places.
"""

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

import a2patch
from a2v101build import relocate

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def env_path(name):
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set")
    if not Path(value).exists():
        pytest.fail(f"{name}={value} does not exist")
    return Path(value)


def innoextract():
    tool = os.environ.get("A2G_INNOEXTRACT") or shutil.which("innoextract")
    if not tool:
        pytest.skip("innoextract not found (set A2G_INNOEXTRACT)")
    return tool


def run(script, *args, check=True):
    done = subprocess.run([sys.executable, str(SRC / script), *map(str, args)], capture_output=True, text=True)
    if check:
        assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture
def cd_exe(tmp_path):
    exe = tmp_path / "anstoss2.exe"
    shutil.copyfile(env_path("A2G_CD_EXE"), exe)
    return exe


@pytest.fixture
def gog_game(tmp_path):
    """The game folder as the GOG installer step of anstoss2.yml.in leaves it."""
    setup = env_path("A2G_GOG_SETUP")
    game = tmp_path / "Anstoss 2 Gold"
    subprocess.run([innoextract(), "-s", "-m", "-g", "-d", str(game), str(setup)], check=True)
    for save in (game / "__support" / "save").iterdir():
        shutil.copy(save, game)
    for data in ("DATA.DEF", "DATA.VER"):
        shutil.copytree(game / "app" / data, game / data, dirs_exist_ok=True)
    return game


@pytest.fixture
def dvd_exe(tmp_path):
    """run.exe of the 2007 CD as the DVD step of anstoss2.yml.in leaves it: unpacked from Setup.exe and its shell."""
    dvd = env_path("A2G_2007_DVD")
    setup = next(dvd.glob("[Aa][Nn][Ss][Tt][Oo][Ss][Ss]_2_[Gg][Oo][Ll][Dd]/[Ss]etup.exe"), None)
    if setup is None:
        pytest.fail(f"no ANSTOSS_2_GOLD/Setup.exe in {dvd}")
    subprocess.run([innoextract(), "-s", "-m", "-d", str(tmp_path / "inno"), str(setup)], check=True)
    exe = tmp_path / "inno" / "app" / "run.exe"
    run("a2unpack.py", exe)
    return exe


def install(exe, *fixes):
    """What the installer runs: the bug fixes with the patches it always applies, then each balancing patch
    on its own page."""
    original = exe.read_bytes()
    always = ["--" + k for k in a2patch.ALWAYS]
    out = run("a2patch.py", "--fixes", *always, *fixes, exe)
    for key in a2patch.BALANCING:
        out += run("a2patch.py", "--" + key, exe)
    assert "unknown version" not in out
    names = [a2patch.PATCHES[k][0] for k in a2patch.FIXES + a2patch.BALANCING if k in a2patch.PATCHES]
    names += [a2patch.FILE_PATCHES["interviews"][0]] + [a2patch.FILE_PATCHES["v101"][0]] * ("--v101" in fixes)
    for name in names:
        assert f"{name}: patched" in out, name
    assert (exe.parent / (exe.name + a2patch.BACKUP_SUFFIX)).read_bytes() == original
    patched = exe.read_bytes()
    again = run("a2patch.py", "--fixes", *always, *fixes, *("--" + k for k in a2patch.BALANCING), exe)
    assert ": patched" not in again and exe.read_bytes() == patched
    return original, patched


def check_run_exe(original, patched):
    """1.01 is the last section (as A2G-Patch wants it), the integrity values are right and the patches stay
    outside the code the game checks itself, apart from the CD checks."""
    pe = a2patch.Pe(patched)
    assert pe.sections[-1][0] == a2patch.V101_SECTION_NAME
    assert struct.unpack_from("<I", patched, a2patch.FILE_CRC_AT)[0] == zlib.crc32(patched[0x80:])
    disc = {at + i for at, _, new, _ in a2patch.disc_check_sites(original) for i in range(len(new))}
    for desc in a2patch.integrity_sites(patched):
        length = struct.unpack_from("<I", patched, desc + 8)[0]
        checked = patched[desc + 0xC : desc + 0xC + length]
        assert struct.unpack_from("<I", patched, desc)[0] == a2patch.crc32_raw(checked)
        changed = {i for i in range(desc + 0xC, desc + 0xC + length) if original[i] != patched[i]}
        assert changed <= disc


# where A2G-Patch's V101Code.cs is built for: the section's address in GOG's run.exe
A2G_PATCH_V101_ADDRESS = 0xCBD000


def check_v101_like_a2g_patch(original):
    """--v101 alone gives A2G-Patch's section (moved to where the section lands: the same address in GOG's
    run.exe, an earlier one in the 2007 CD's, whose .data ends earlier), and taking it back gives the
    original to the byte."""
    with_v101 = a2patch.apply_v101(bytearray(original))
    assert bytes(a2patch.remove_v101(bytearray(with_v101))) == original
    patcher = os.environ.get("A2G_PATCHER")
    if patcher:
        source = (Path(patcher) / "V101Code.cs").read_text(encoding="utf-8")
        block = source[source.index("internal const string Code =") :]
        code = base64.b64decode("".join(re.findall(r'"([^"]*)"', block[: block.index(";")])))
        pe = a2patch.Pe(bytes(with_v101))
        _, vsize, va, _, raw, _ = pe.sections[-1]
        with open(a2patch.V101_PREBUILT) as f:
            prebuilt = json.load(f)
        moved, _ = relocate({**prebuilt, "code": [code.hex()], "base": A2G_PATCH_V101_ADDRESS}, pe.image_base + va)
        assert bytes(with_v101[raw : raw + vsize]) == moved


def test_cd(cd_exe):
    original, patched = install(cd_exe)
    assert len(patched) > len(original)  # .a2int


def test_gog(gog_game):
    original, patched = install(gog_game / "run.exe", "--disc-check", "--v101")
    check_run_exe(original, patched)
    check_v101_like_a2g_patch(original)
    for script, done in (("a2resdll.py", "already there"), ("a2data101.py", "already there")):
        run(script, gog_game)
        assert done in run(script, gog_game)


def test_2007_cd(dvd_exe):
    original, patched = install(dvd_exe, "--disc-check", "--v101")
    check_run_exe(original, patched)
    names = [s[0] for s in a2patch.Pe(patched).sections]
    assert names.index(a2patch.INTERVIEW_SECTION) < names.index(a2patch.V101_SECTION_NAME)
    check_v101_like_a2g_patch(original)


# a2patch's rewrites with the classes of A2G-Patch's Patches.cs they come from
REWRITES = {
    "EventEffects": a2patch.EVENT_PLACES,
    "EventCrashes": a2patch.CRASH_PLACES,
    "AppearancesList": a2patch.APPEARANCES_PLACES,
    "ManagerEvents": a2patch.MANAGER_PLACES,
    "CompetenceBalance": ((a2patch.COMPETENCE_ORIGINAL, a2patch.COMPETENCE_PATCHED),),
    "FishPoisoning": ((a2patch.FISH_ORIGINAL, a2patch.FISH_PATCHED),),
}


def cs_hex(expression):
    """The hex string of a C# expression of string literals, + and string.Concat(Enumerable.Repeat(..))."""
    repeat = r'string\.Concat\(Enumerable\.Repeat\("(\w+)", (\d+)\)\)'
    expression = re.sub(repeat, lambda m: '"' + m[1] * int(m[2]) + '"', expression)
    return "".join(re.findall(r'"([0-9A-Fa-f?]*)"', expression)).upper()


def a2g_patch_class(source, name):
    start = source.index(f"internal sealed class {name} ")
    return source[start : source.index("\n    }\n", start)]


def test_rewrites_are_a2g_patchs():
    """The patterns of the rewrites ported from A2G-Patch are those of its Patches.cs, byte for byte."""
    patcher = env_path("A2G_PATCHER")
    source = (patcher / "Patches.cs").read_text(encoding="utf-8")

    def as_hex(pattern):
        return "".join("??" if b is None else f"{b:02X}" for b in pattern)

    for name, places in REWRITES.items():
        block = re.sub(r"//[^\n]*", "", a2g_patch_class(source, name))
        if "Place(" in block:
            theirs = [
                tuple(cs_hex(part) for part in re.split(r'(?<=")\s*,\s*(?=")', m[1], maxsplit=1))
                for m in re.finditer(r"Place\((.*?)\),\s*\n", block, re.S)
            ]
        else:
            theirs = [tuple(cs_hex(re.search(rf"{c}Code =>(.*?);", block, re.S)[1]) for c in ("Original", "Patched"))]
        assert theirs == [(as_hex(o), as_hex(n)) for o, n in places], name
    grades = a2g_patch_class(source, "GradeAverage")
    code = bytes(int(b, 16) for b in re.search(r"Exact\(([^)]*)\)", grades)[1].split(","))
    assert code == a2patch.GRADE_CODE
    assert "At => 5;" in grades and "PatchedByte => 0x1C;" in grades and "Occurrences => 2;" in grades
