# SPDX-License-Identifier: GPL-3.0-only
"""Checks that the places describing the patches agree: src/a2patch.py, install.sh, anstoss2.yml.in,
the lutris.net scripts, the release workflow, README.md and docs/index.html."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import a2patch
import a2patcher
import a2quiz
import a2texts

ROOT = Path(__file__).resolve().parent.parent
# variant of anstoss2.yml.in (install.sh's VARIANT), its lutris.net script and the exe it patches
VARIANTS = {
    "CD": ("anstoss-2-gold.yml", "anstoss2.exe"),
    "DVD": ("anstoss-2-gold-2007.yml", "run.exe"),
    "GOG": ("anstoss-2-gold-gog.yml", "run.exe"),
}
# variant of anstoss2.yml.in, of src/a2patcher.py
PATCHER = {"CD": "cd", "DVD": "2007", "GOG": "gog"}
OTHER_QUESTIONS = ("ICON", "DATASET", "SAVES", "QUIZ", "TRAINER")  # not patches
HOST_ONLY = ("ICON", "TRAINER")  # need the system's programs: install.sh only


def text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def install_sh_fixes():
    """{VARIANT: FIXES} as install.sh sets them."""
    return {m[1]: m[0] for m in re.findall(r'FIXES="([^"]*)"; VARIANT=(\w+)', text("install.sh"))}


def render(variant, icon_repo=True, flatpak=False):
    """anstoss2.yml.in as install.sh writes it for variant (blocks kept or dropped, placeholders filled),
    with A2G-Icon fetchable or not (block ICONREPO), for the distribution package of Lutris or its Flatpak."""
    tags = {variant, "FLATPAK" if flatpak else "NATIVE"} | ({"ICONREPO"} if icon_repo else set())
    lines, skip = [], False
    for line in text("anstoss2.yml.in").splitlines():
        if line.startswith("# @BEGIN "):
            skip = not tags & set(line.split()[2:])
        elif line.startswith("# @END"):
            skip = False
        elif not skip:
            lines.append(line)
    out = "\n".join(lines)
    fixes = install_sh_fixes()[variant]
    out = out.replace(" @FIXES@", " " + fixes if fixes else "").replace("@EXE@", VARIANTS[variant][1])
    out = out.replace("@PKG@", "/pkg").replace("@ICONS@", "/data/icons/hicolor")
    out = out.replace("@HOST@", "flatpak-spawn --host " if flatpak else "")
    assert "@SLUG@" in out
    return re.sub(r"@[A-Z]+@", "x", out)


def steps(script):
    """The installer steps of a Lutris script, as (kind, values)."""
    return [next(iter(step.items())) for step in yaml.safe_load(script)["script"]["installer"]]


def questions(script):
    """[(id, description, options, preselect, command of the step behind it)] of the input menus."""
    s = steps(script)
    return [
        (v["id"], v["description"], v["options"], v["preselect"], s[i + 1][1].get("command", ""))
        for i, (kind, v) in enumerate(s)
        if kind == "input_menu"
    ]


def lutris_script(variant):
    return text("lutris.net/" + VARIANTS[variant][0])


def patcher_step(variant):
    """The wineexec step of a lutris.net script that runs src/a2patcher.exe."""
    found = [v for kind, v in steps(lutris_script(variant)) if kind == "task" and v["name"] == "wineexec"]
    found = [v for v in found if v["executable"] == "$CACHE/a2g/src/a2patcher.exe"]
    assert len(found) == 1
    return found[0]


def balancing_questions(script):
    return [q for q in questions(script) if q[0] not in OTHER_QUESTIONS + tuple(a2texts.QUESTIONS)]


def text_questions(script):
    return [q for q in questions(script) if q[0] in a2texts.QUESTIONS]


def option(key):
    return "--" + key.replace("_", "-")


@pytest.mark.parametrize("variant", VARIANTS)
def test_rendered_installer_has_no_placeholders(variant):
    script = render(variant)
    yaml.safe_load(script)
    assert not re.search(r"@[A-Z]+@", script)


@pytest.mark.parametrize("variant", VARIANTS)
def test_balancing_questions_in_order(variant):
    for script in (render(variant), lutris_script(variant)):
        found = balancing_questions(script)
        assert [q[0] for q in found] == [k.upper() for k in a2patch.BALANCING]
        for key, _, options, preselect, command in found:
            assert preselect == "no" and options[0] == {"no": "Original beibehalten"} and "yes" in options[1]
    for key, _, _, _, command in balancing_questions(render(variant)):
        assert f'test "$INPUT_{key}" != yes || python3 ' in command
        assert f'/src/a2patch.py" --{key.lower()} "' in command
        assert command.endswith(f'/{VARIANTS[variant][1]}"')


@pytest.mark.parametrize("variant", VARIANTS)
def test_lutris_script_asks_what_install_sh_asks(variant):
    """The same pages, except those that need the system's programs."""
    ours = [q[:4] for q in questions(render(variant)) if q[0] not in HOST_ONLY]
    theirs = [q[:4] for q in questions(lutris_script(variant))]
    assert ours == theirs


@pytest.mark.parametrize("variant", VARIANTS)
def test_lutris_script_hands_every_answer_to_the_patcher(variant):
    """One wineexec of src/a2patcher.exe after the last question, with the variant, the source and each
    answer as --<id> $INPUT_<ID>; the patcher knows exactly these questions and answers."""
    s = steps(lutris_script(variant))
    step = patcher_step(variant)
    assert s[-1] == ("task", step)
    asked = questions(lutris_script(variant))
    assert list(a2patcher.QUESTIONS) == [q[0] for q in asked]
    for key, _, options, preselect, _ in asked:
        assert a2patcher.QUESTIONS[key] == tuple(next(iter(o)) for o in options)
        assert preselect == a2patcher.QUESTIONS[key][0]
    source = {"CD": '"$DISC"', "DVD": '"$CACHE/dvd"', "GOG": '"$CACHE/gog"'}[variant]
    args = " ".join(f"--{q[0].lower()} $INPUT_{q[0]}" for q in asked)
    assert step["args"] == f"{PATCHER[variant]} {source} {args}"


@pytest.mark.parametrize("variant", VARIANTS)
def test_lutris_script_runs_in_lutris_flatpak(variant):
    """lutris.net's rules: Lutris' own steps only, no commands of the system, nothing in the home folder."""
    script = yaml.safe_load(lutris_script(variant))["script"]
    assert "require-binaries" not in script
    kinds = {kind for kind, _ in steps(lutris_script(variant))}
    assert kinds <= {"extract", "insert-disc", "task", "merge", "input_menu"}
    assert not re.search(r"\$HOME|XDG_|disable_runtime|python3|bash ", lutris_script(variant))
    # No Wine version: Lutris' default, the newest GE-Proton through umu (Wine Staging 11.19 loses the mouse
    # after the loading screen of a new game; Lutris 0.5.23 can't download a pinned GE-Proton)
    assert "version" not in script["wine"]
    # gsfix.so for Gamescope, and next to it gsdisplay.so, which gsfix.so hands to the game: in the Flatpak,
    # Proton's sub-sandbox gets the desktop's DISPLAY otherwise
    assert script["system"]["env"]["LD_PRELOAD"] == "$GAMEDIR/gsfix.so"
    merged = [v["src"] for kind, v in steps(lutris_script(variant)) if kind == "merge" and v["dst"] == "$GAMEDIR"]
    assert {"$CACHE/a2g/src/gsfix.so", "$CACHE/a2g/src/gsdisplay.so"} <= set(merged)


@pytest.mark.parametrize("variant", VARIANTS)
def test_text_questions_follow_the_balancing_patches(variant):
    """One page each for the Euro and the centre-back, one for the names; the typing errors every time, before
    them and after patch 1.01's data and the dialog styles; the contract terms only on the command line."""
    game = '"$GAMEDIR/drive_c/Spiele/Anstoss 2 Gold"'
    for script in (render(variant), lutris_script(variant)):
        ids = [q[0] for q in questions(script)]
        first = ids.index(a2patch.BALANCING[-1].upper()) + 1
        assert ids[first : first + len(a2texts.QUESTIONS)] == list(a2texts.QUESTIONS)
        for key, _, options, preselect, command in text_questions(script):
            assert preselect == "no" and options[0] == {"no": "Original beibehalten"} and "yes" in options[1]
    script = render(variant)
    for key, _, options, preselect, command in text_questions(script):
        switches = " ".join(option(k) for k in a2texts.QUESTIONS[key])
        assert command.startswith(f'test "$INPUT_{key}" != yes || python3 ')
        assert command.endswith(f'/src/a2texts.py" {switches} {game}')
    commands = [v.get("command", "") for kind, v in steps(script) if kind == "execute"]
    always = [i for i, c in enumerate(commands) if c.endswith(f'/src/a2texts.py" --typos {game}')]
    assert len(always) == 1 and all("a2texts.py" not in c for c in commands[: always[0]])
    assert all(always[0] > i for i, c in enumerate(commands) if "a2data101.py" in c or "a2resdll.py" in c)
    assert all(always[0] > i for i, c in enumerate(commands) if "a2import.py" in c)
    assert not any("--contracts" in c for c in commands)


def test_text_switches_are_asked_once_or_applied_every_time():
    asked = [k for keys in a2texts.QUESTIONS.values() for k in keys]
    every = asked + list(a2texts.ALWAYS + a2texts.COMMAND_LINE_ONLY)
    assert sorted(every) == sorted(p.option for p in a2texts.PATCHES) and len(set(every)) == len(every)


@pytest.mark.parametrize("variant", VARIANTS)
def test_quiz_is_asked_after_the_text_questions(variant):
    """One page with the four ways of a2quiz.py's switches, the original first."""
    for script in (render(variant), lutris_script(variant)):
        ids = [q[0] for q in questions(script)]
        assert ids.index("QUIZ") == ids.index(list(a2texts.QUESTIONS)[-1]) + 1
        _, _, options, preselect, command = questions(script)[ids.index("QUIZ")]
        assert [next(iter(o)) for o in options] == list(a2quiz.MODES) and preselect == "original"
        assert options[0] == {"original": "Original beibehalten"}
    command = next(q[4] for q in questions(render(variant)) if q[0] == "QUIZ")
    assert command.startswith('test "$INPUT_QUIZ" = original || python3 ')
    assert command.endswith('/src/a2quiz.py" "$INPUT_QUIZ" "$GAMEDIR/drive_c/Spiele/Anstoss 2 Gold"')


def test_balancing_questions_are_the_same_for_every_variant():
    texts = {v: [q[1:4] for q in balancing_questions(lutris_script(v))] for v in VARIANTS}
    assert texts["CD"] == texts["DVD"] == texts["GOG"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_fixes_applied_on_every_install(variant):
    fixes = install_sh_fixes()[variant]
    assert fixes == ("" if variant == "CD" else "--disc-check --v101")
    commands = [v.get("command", "") for kind, v in steps(render(variant)) if kind == "execute"]
    wanted = (
        " ".join(["--fixes"] + ["--" + k for k in a2patch.ALWAYS] + fixes.split())
        + f' "$GAMEDIR/drive_c/Spiele/Anstoss 2 Gold/{VARIANTS[variant][1]}"'
    )
    assert sum(c.endswith('/src/a2patch.py" ' + wanted) for c in commands) == 1
    # the lutris.net script: src/a2patcher.py, with the same exe and switches (tests/test_a2patcher.py)
    assert a2patcher.FIXES[PATCHER[variant]] == fixes.split()
    assert a2patcher.EXE[PATCHER[variant]] == VARIANTS[variant][1]


def test_fixes_and_balancing_are_all_code_patches():
    every = set(a2patch.FIXES) | set(a2patch.ALWAYS) | set(a2patch.BALANCING) | {"disc_check", "v101"}
    assert every == set(a2patch.PATCHES) | set(a2patch.FILE_PATCHES)
    assert len(every) == len(a2patch.FIXES + a2patch.ALWAYS + a2patch.BALANCING) + 2


def test_patches_applied_every_time_are_not_asked():
    for variant in VARIANTS:
        for script in (render(variant), lutris_script(variant)):
            asked = {q[0] for q in questions(script)}
            assert not asked & {k.upper() for k in a2patch.ALWAYS + a2patch.FIXES}


def test_lutris_scripts_download_the_release_asset():
    asset = re.search(r"gh release create \S+ (\S+\.tar\.gz)", text(".github/workflows/release.yml"))[1]
    for variant in VARIANTS:
        urls = re.findall(r"url: (\S+)", lutris_script(variant))
        assert "https://github.com/transfairs/A2G-Linux/releases/latest/download/" + asset in urls


def test_readme_documents_every_patch():
    readme = text("README.md")
    for key in a2patch.FIXES + a2patch.ALWAYS + a2patch.BALANCING + ("disc_check", "v101", "fixes"):
        assert f"`--{key.replace('_', '-')}`" in readme, key
    for patch in a2texts.PATCHES:
        assert f"`{option(patch.option)}`" in readme, patch.option


def test_project_page_has_both_languages_everywhere():
    page = text("docs/index.html")
    body = page[page.index("<body") :]
    german = re.findall(r'<span lang="de">', body)
    pairs = re.findall(r'<span lang="de">(?:(?!</span>).)*</span>\s*<span lang="en">', body, re.S)
    assert german and len(pairs) == len(german) == len(re.findall(r'<span lang="en">', body))


def test_project_page_links_lead_somewhere():
    page = text("docs/index.html")
    ids = set(re.findall(r'id="([^"]+)"', page))
    assert {h for h in re.findall(r'href="#([^"]+)"', page)} <= ids
    for local in re.findall(r'(?:src|href)="(?!https?:|#|data:|mailto:)([^"]+)"', page):
        assert (ROOT / "docs" / local).exists(), local


@pytest.mark.parametrize("variant", VARIANTS)
def test_icon_is_asked_with_the_games_icon_as_default(variant):
    """install.sh's installer asks for the icon before the other questions, the game's own preselected,
    and installs it with a2assets.py icon under Lutris' name for the game, given the game's icon to fall
    back on; install.sh drops A2G-Icon from the choice if it can't fetch it. The lutris.net scripts
    don't ask: the icon would go to the home folder, lutris.net's game page brings it instead."""
    assert not list((ROOT / "src").glob("anstoss2-icon.*"))  # kept in the repository A2G-Icon
    first = questions(render(variant))[0]
    assert first[0] == "ICON" and first[3] == "game"
    assert [next(iter(o)) for o in first[2]] == ["game", "repo", "file"]
    desktop = r'"\$GAMEDIR/drive_c/Spiele/Anstoss 2 Gold/a2desktop\.bmp"'
    assert re.search(
        r'a2assets\.py" icon "\$INPUT_ICON" "[^"]+" "[^"]*/icons/hicolor" "lutris_\w[\w-]*" ' + desktop, first[4]
    )
    assert "ICON" not in [q[0] for q in questions(lutris_script(variant))]
    without = questions(render(variant, icon_repo=False))[0]
    assert without[0] == "ICON" and [next(iter(o)) for o in without[2]] == ["game", "file"]
    install = text("install.sh")
    assert 'a2assets.py" icon-check; then TAGS+=" ICONREPO"' in install
    assert 'cp "$ICO" "$PKG/build/anstoss2.ico"' in install and "@PKG@/build/anstoss2.ico" in text("anstoss2.yml.in")


def test_editor_icon_is_what_its_script_draws(tmp_path):
    """src/editor-icon.svg is the output of .github/editor-icon.py (README: Building the helper programs)."""
    svg = tmp_path / "editor-icon.svg"
    subprocess.run([sys.executable, str(ROOT / ".github" / "editor-icon.py"), str(svg)], check=True)
    assert svg.read_text() == text("src/editor-icon.svg"), "run python3 .github/editor-icon.py"


@pytest.mark.skipif(
    not shutil.which("rsvg-convert") or not shutil.which("magick"), reason="needs rsvg-convert and magick"
)
@pytest.mark.parametrize("name", ["editor-icon"])
def test_icon_png_is_the_svg_rendered(tmp_path, name):
    """src/<name>.png is up to date with src/<name>.svg (README: Building the helper programs)."""
    png = tmp_path / "icon.png"
    subprocess.run(
        ["rsvg-convert", "-w", "128", "-h", "128", str(ROOT / "src" / f"{name}.svg"), "-o", str(png)], check=True
    )
    compare = [
        "magick",
        "compare",
        "-metric",
        "AE",
        "-fuzz",
        "2%",
        str(ROOT / "src" / f"{name}.png"),
        str(png),
        "null:",
    ]
    differing = subprocess.run(compare, capture_output=True, text=True).stderr.split()[0]
    assert float(differing) < 20, f"{differing} pixels differ, render src/{name}.png anew"


@pytest.mark.parametrize("variant", VARIANTS)
def test_install_sh_script_for_lutris_flatpak(variant):
    """install.sh with Lutris' Flatpak: steps that need the system's programs run there (flatpak-spawn
    --host), the others inside the Flatpak; no schema copy (Gamescope takes the runtime's), gsdisplay.so
    next to gsfix.so, a2run.sh starting the editor and the trainer inside the Flatpak."""
    native, flatpak = render(variant), render(variant, flatpak=True)
    assert "GSETTINGS_SCHEMA_DIR" in native and "GSETTINGS_SCHEMA_DIR" not in flatpak
    assert "--make-schemas" in native and "--make-schemas" not in flatpak
    native_commands = [v["command"] for kind, v in steps(native) if kind == "execute"]
    assert not any("flatpak-spawn" in c or "gsdisplay.so" in c for c in native_commands)
    commands = [v["command"] for kind, v in steps(flatpak) if kind == "execute"]
    tools = ("a2assets.py", "a2import.py", "a2extras.py", "--convert-only", '"x" -s')
    for c in commands:
        for part in re.split(r"&&|\|\|", c):
            if any(t in part for t in tools):
                assert part.strip().startswith("flatpak-spawn --host "), part
    assert any(c == 'cp "/pkg/src/gsdisplay.so" "$GAMEDIR/"' for c in commands)
    assert any("a2extras.py" in c and " --flatpak " in c for c in commands)
    script = yaml.safe_load(flatpak)["script"]
    assert script["system"]["env"]["LD_PRELOAD"] == "$GAMEDIR/gsfix.so"
