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

import a2managerbuild
import a2patch
import a2texts
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


def test_cd_manager_events_of_a2g_linux_0_2(cd_exe, tmp_path):
    """An exe with the manager events of A2G-Linux 0.2.0 (case 34's weight 0) gets the cases' code and the 4
    back, as an untouched one gets them."""
    original = cd_exe.read_bytes()
    old = bytearray(original)
    for at, _, new, _ in a2patch.rewrites_sites(original, a2patch.MANAGER_PLACES):
        old[at : at + len(new)] = new
    weights = original.index(a2patch.MANAGER_WEIGHTS)
    old[weights : weights + len(a2patch.MANAGER_WEIGHTS)] = a2patch.MANAGER_OLD_WEIGHTS
    run("a2patch.py", "--manager", cd_exe)
    fresh = cd_exe.read_bytes()
    upgraded = tmp_path / "old" / "anstoss2.exe"
    upgraded.parent.mkdir()
    upgraded.write_bytes(old)
    assert "all events around the manager's private life: patched" in run("a2patch.py", "--manager", upgraded)
    assert upgraded.read_bytes() == fresh


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
    "RefereeGrudge": ((a2patch.REFEREE_ORIGINAL, a2patch.REFEREE_PATCHED),),
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


def test_grade_chart_label_is_a2g_patchs():
    """The patterns of the grade chart's label are those of A2G-Patch's GradeChartLabel."""
    patcher = env_path("A2G_PATCHER")
    block = a2g_patch_class((patcher / "Patches.cs").read_text(encoding="utf-8"), "GradeChartLabel")
    rest = cs_hex(re.search(r"string Rest = (.*?);", block, re.S)[1])

    def pattern(name):
        expression = re.search(rf"{name} =(.*?)\.Pattern\(\);", block, re.S)[1]
        return "".join(rest if part.strip() == "Rest" else cs_hex(part) for part in re.split(r"\+", expression))

    def as_hex(pattern):
        return "".join("??" if b is None else f"{b:02X}" for b in pattern)

    assert pattern("OriginalCode") == as_hex(a2patch.GRADE_CHART_ORIGINAL)
    assert pattern("PatchedCode") == as_hex(a2patch.GRADE_CHART_PATCHED)
    assert pattern("LoaderCode") == as_hex(a2patch.GRADE_CHART_LOADER)
    calls = re.search(r"TextCall = (\w+), AssignCall = (\w+), NextTextCall = (\w+), LoaderAssignCall = (\w+);", block)
    assert [int(c, 0) for c in calls.groups()] == [
        a2patch.GRADE_CHART_TEXT_CALL,
        a2patch.GRADE_CHART_ASSIGN_CALL,
        a2patch.GRADE_CHART_NEXT_TEXT_CALL,
        a2patch.GRADE_CHART_LOADER_ASSIGN_CALL,
    ]


def test_manager_code_is_a2g_patchs():
    """src/a2manager.json holds A2G-Patch's ManagerCode.cs, and the switch, the weights and the layout are those
    of its ManagerEvents."""
    patcher = env_path("A2G_PATCHER")
    source = (patcher / "ManagerCode.cs").read_text(encoding="utf-8")
    assert a2managerbuild.parse(source) == a2patch.load_manager_code()
    block = a2g_patch_class((patcher / "Patches.cs").read_text(encoding="utf-8"), "ManagerEvents")
    assert cs_hex(re.search(r"SwitchPattern = (.*?)\.Pattern", block)[1]) == "".join(
        "??" if b is None else f"{b:02X}" for b in a2patch.MANAGER_SWITCH
    )
    assert f"TableAt = {a2patch.MANAGER_TABLE_AT};" in block
    weights = re.search(r'OldWeights = "(\w+)"\.Hex\(\), Weights = "(\w+)"', block)
    assert bytes.fromhex(weights[1]) == a2patch.MANAGER_OLD_WEIGHTS
    assert bytes.fromhex(weights[2]) == a2patch.MANAGER_WEIGHTS
    assert "RegionOf = { %s };" % ", ".join(map(str, a2patch.MANAGER_REGION_OF)) in block
    assert f"QuestionSize = 0x{a2patch.MANAGER_QUESTION_SIZE:X};" in block
    assert f"Fill = 0x{a2patch.MANAGER_FILL:X};" in block


# --- texts (src/a2texts.py) -------------------------------------------------------------------------------

TEXT_OPTIONS = ["--" + p.option.replace("_", "-") for p in a2texts.PATCHES]


def text_files(game):
    """{name: bytes} of the files the text switches change, as far as game has them."""
    files = a2texts.GameFiles(str(game))
    names = ("RESDLL.dll", *a2texts.EVENT_FILES, a2texts.TIPS_FILE)
    return {n: files.read(n) for n in names if files.read(n) is not None}


def check_texts(game, *scripts):
    """Every switch fits the release's texts; all on (the installer's --typos first), the scripts that know the
    files by their SHA-256 run again and find them as they left them, then all off: the files as before."""
    before = text_files(game)
    assert "RESDLL.dll" in before and a2texts.TIPS_FILE in before
    assert any(n in before for n in a2texts.EVENT_FILES)
    assert run("a2texts.py", "--typos", game) == "Tippfehler: on\n"
    out = run("a2texts.py", *TEXT_OPTIONS, game)
    assert out.count(": on\n") == len(a2texts.PATCHES) - 1 and "Tippfehler: already on" in out
    files = a2texts.GameFiles(str(game))
    assert all(a2texts.state(p, files) == "on" for p in a2texts.PATCHES)
    assert a2texts.plain_resources(files.read("RESDLL.dll")) == before["RESDLL.dll"]
    for name in a2texts.EVENT_FILES:
        if name in before:
            texts = a2texts.read_events(files.read(name))
            assert len(files.read(name)) == len(before[name]) and texts[909] == "Innenverteidiger", name
            assert a2texts.plain_events(files.read(name)) == before[name]
    for script in scripts:
        assert "already" in run(script, game)
    assert text_files(game) != before
    out = run("a2texts.py", "--off", *TEXT_OPTIONS, game)
    assert out.count(": off\n") == len(a2texts.PATCHES)
    assert text_files(game) == before


def test_cd_texts(tmp_path):
    folder = env_path("A2G_CD_EXE").parent
    for name in ("RESDLL.dll", "TEXTE/EreigGld.saq", "TEXTE/tips.txt"):
        source = Path(a2texts.GameFiles(str(folder)).path(name))
        if not source.is_file():
            pytest.skip(f"no {name} next to A2G_CD_EXE")
        (tmp_path / name).parent.mkdir(exist_ok=True)
        shutil.copyfile(source, tmp_path / name)
    check_texts(tmp_path)


def test_gog_texts(gog_game):
    run("a2data101.py", gog_game)
    run("a2resdll.py", gog_game)
    check_texts(gog_game, "a2data101.py", "a2resdll.py")


def test_2007_cd_texts(dvd_exe):
    game = dvd_exe.parent
    run("a2data101.py", game, check=False)  # the DVD's LAENDER.SAV is not where GOG has it
    check_texts(game, "a2data101.py")


def cs_arguments(source, at):
    """The arguments (strings and numbers) of the call whose "(" is at at, and where it ends."""
    args, depth, i = [], 0, at
    while True:
        c = source[i]
        if c == '"':
            end = source.index('"', i + 1)
            args.append(source[i + 1 : end])
            i = end
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return args, i
        elif c.isdigit() and not source[i - 1].isalnum():
            number = re.match(r"\d+", source[i:])[0]
            args.append(int(number))
            i += len(number) - 1
        i += 1


def test_texts_are_a2g_patchs():
    """The switches' texts, ids and order are those of A2G-Patch's TextPatches.cs."""
    patcher = env_path("A2G_PATCHER")
    source = (patcher / "TextPatches.cs").read_text(encoding="utf-8")
    theirs = {}
    for name in a2texts.KEYS:
        body = a2g_patch_class(source, name)
        changes = []
        for m in re.finditer(r"TextChange\.(Strings|Dialogs|Event|Tips)\(", body):
            args, _ = cs_arguments(body, m.end() - 1)
            kind = m[1]
            if kind == "Event":
                changes.append((a2texts.EVENT, args[1], args[2], (args[0],)))
            elif kind == "Tips":
                changes.append((a2texts.TIPS, args[0], args[1], ()))
            else:
                changes.append(
                    (a2texts.STRING if kind == "Strings" else a2texts.DIALOG, args[0], args[1], tuple(args[2:]))
                )
        title = re.search(r'Title => "([^"]*)"', body)[1]
        theirs[name] = (title, changes)
    assert {p.key: (p.title, [tuple(c) for c in p.changes]) for p in a2texts.PATCHES} == theirs
    # the order of InOrder: the switches as in Patch.All, then the game's bugs
    patches = (patcher / "Patches.cs").read_text(encoding="utf-8")
    order = [m for m in re.findall(r"new (\w+)\(\)", patches) if m in a2texts.KEYS]
    assert tuple(dict.fromkeys(order)) == a2texts.KEYS
