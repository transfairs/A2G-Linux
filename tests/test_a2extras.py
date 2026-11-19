# SPDX-License-Identifier: GPL-3.0-only
import io
import os
import runpy
import struct
import sys
import zipfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import a2extras  # noqa: E402


def test_refresh_icon_cache_runs_the_tool(tmp_path):
    with mock.patch("shutil.which", return_value="/usr/bin/gtk-update-icon-cache"), mock.patch(
        "subprocess.run", return_value=mock.Mock(returncode=0)
    ) as run:
        a2extras.refresh_icon_cache(str(tmp_path))
    run.assert_called_once_with(["/usr/bin/gtk-update-icon-cache", "-q", "-t", "-f", str(tmp_path)], check=False)


def test_refresh_icon_cache_marks_the_cache_stale_without_the_tool(tmp_path):
    cache = tmp_path / "icon-theme.cache"
    cache.write_bytes(b"")
    os.utime(cache, (1000, 1000))
    os.utime(tmp_path, (1000, 1000))
    with mock.patch("shutil.which", return_value=None):
        a2extras.refresh_icon_cache(str(tmp_path))
    assert os.stat(tmp_path).st_mtime > os.stat(cache).st_mtime


def test_refresh_icon_cache_without_folder(tmp_path):
    with mock.patch("subprocess.run") as run:
        a2extras.refresh_icon_cache(str(tmp_path / "missing"))
    run.assert_not_called()


def test_every_installer_uses_a_known_slug():
    import glob
    import re

    root = os.path.join(os.path.dirname(__file__), "..")
    slugs = set()
    for f in glob.glob(os.path.join(root, "lutris.net", "*.yml")):
        slugs.update(re.findall(r"a2extras\.py\" --slug (\S+)", open(f).read()))
    assert slugs == {"anstoss-2-cd", "anstoss-2-2007", "anstoss-2-gog"}
    assert slugs <= set(a2extras.SUFFIXES)


# Synthetic PE files

GROUP, ICON = a2extras.RT_GROUP_ICON, a2extras.RT_ICON


def rsrc_section(resources, va):
    """A .rsrc section (three levels: type, name, language) for {(type, name): data} at RVA va."""
    keys = sorted(resources)
    types = sorted({t for t, _ in keys})
    off = 16 + 8 * len(types)
    type_dirs = {}
    for t in types:
        type_dirs[t] = off
        off += 16 + 8 * sum(1 for tt, _ in keys if tt == t)
    lang_dirs, data_entries, data_offs = {}, {}, {}
    for key in keys:
        lang_dirs[key] = off
        off += 16 + 8
    for key in keys:
        data_entries[key] = off
        off += 16
    for key in keys:
        data_offs[key] = off
        off += len(resources[key])
    blob = bytearray(off)

    def directory(at, entries):
        struct.pack_into("<IIHHHH", blob, at, 0, 0, 0, 0, 0, len(entries))
        for i, (name, target) in enumerate(entries):
            struct.pack_into("<II", blob, at + 16 + 8 * i, name, target)

    directory(0, [(t, 0x80000000 | type_dirs[t]) for t in types])
    for t in types:
        directory(type_dirs[t], [(n, 0x80000000 | lang_dirs[(tt, n)]) for tt, n in keys if tt == t])
    for key in keys:
        directory(lang_dirs[key], [(0x407, data_entries[key])])
        struct.pack_into("<IIII", blob, data_entries[key], va + data_offs[key], len(resources[key]), 0, 0)
        blob[data_offs[key] : data_offs[key] + len(resources[key])] = resources[key]
    return bytes(blob)


def make_pe(resources, pe32plus=False, rsrc_rva=0x2000):
    """A minimal PE file: a .text section that holds nothing, then .rsrc with the given resources."""
    pe, opt = 0x40, 240 if pe32plus else 224
    blob = rsrc_section(resources, 0x2000)
    d = bytearray(0x400 + len(blob))
    struct.pack_into("<I", d, 0x3C, pe)
    d[pe : pe + 4] = b"PE\0\0"
    struct.pack_into("<H", d, pe + 6, 2)
    struct.pack_into("<H", d, pe + 20, opt)
    struct.pack_into("<H", d, pe + 24, 0x20B if pe32plus else 0x10B)
    struct.pack_into("<I", d, pe + 24 + (112 if pe32plus else 96) + 2 * 8, rsrc_rva)
    sections = [(b".text", 0x100, 0x1000, 0x200, 0x200), (b".rsrc", len(blob), 0x2000, len(blob), 0x400)]
    for i, s in enumerate(sections):
        struct.pack_into("<8sIIII", d, pe + 24 + opt + i * 40, *s)
    d[0x400:] = blob
    return bytes(d)


def icon_group(*entries):
    """RT_GROUP_ICON data for entries (width, bpp, icon id, data size)."""
    out = struct.pack("<HHH", 0, 1, len(entries))
    for w, bpp, icon_id, size in entries:
        out += struct.pack("<BBBBHHIH", w, w, 0, 0, 1, bpp, size, icon_id)
    return out


def icon_exe(path, small_only=False):
    """Writes an exe with a 32x32 8 bit icon (id 1) and, unless small_only, a 256x256 32 bit one (id 2)."""
    small, large = b"small icon", b"large icon data"
    entries = [(32, 8, 1, len(small))] if small_only else [(0, 32, 2, len(large)), (32, 8, 1, len(small))]
    resources = {(GROUP, 1): icon_group(*entries), (ICON, 1): small}
    if not small_only:
        resources[(ICON, 2)] = large
    path.write_bytes(make_pe(resources))
    return path


@pytest.mark.parametrize("pe32plus", [False, True])
def test_pe_resources_reads_every_resource(tmp_path, pe32plus):
    exe = tmp_path / "x.exe"
    exe.write_bytes(make_pe({(ICON, 1): b"one", (ICON, 7): b"seven", (GROUP, 1): b"group"}, pe32plus))
    assert a2extras.pe_resources(str(exe)) == {(ICON, 1): [b"one"], (ICON, 7): [b"seven"], (GROUP, 1): [b"group"]}


def test_pe_resources_rejects_an_rva_outside_the_sections(tmp_path):
    exe = tmp_path / "x.exe"
    exe.write_bytes(make_pe({(ICON, 1): b"one"}, rsrc_rva=0x9000))
    with pytest.raises(ValueError, match="RVA outside the sections"):
        a2extras.pe_resources(str(exe))


def fake_convert(calls):
    """subprocess.run replacement that records the command and the .ico it was given."""

    def run(cmd, check):
        calls.append((cmd, open(cmd[1], "rb").read(), check))
        return mock.Mock(returncode=0)

    return run


def test_exe_icon_converts_the_largest_icon_smoothly(tmp_path):
    exe = icon_exe(tmp_path / "x.exe")
    calls = []
    which = {"magick": None, "convert": "/usr/bin/convert"}
    with mock.patch("shutil.which", side_effect=which.get), mock.patch("subprocess.run", fake_convert(calls)):
        a2extras.exe_icon(str(exe), "out.png", 64)
    ((cmd, ico, check),) = calls
    assert cmd[0] == "/usr/bin/convert" and cmd[2:] == ["-resize", "64x64", "PNG32:out.png"] and check
    data = b"large icon data"
    assert ico == struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22) + data


def test_exe_icon_scales_small_icons_as_pixel_art(tmp_path):
    exe = icon_exe(tmp_path / "x.exe", small_only=True)
    calls = []
    with mock.patch.object(
        a2extras, "pixel_icon", lambda src, png, size: calls.append((open(src, "rb").read(), png, size))
    ):
        a2extras.exe_icon(str(exe), "out.png")
    ((ico, png, size),) = calls
    assert ico.endswith(b"small icon") and (png, size) == ("out.png", 128)


# Pixel art icons

R, Y, T = (255, 0, 0, 255), (255, 255, 0, 255), (0, 0, 0, 0)


def checkerboard(n):
    return [R if (x + y) % 2 else Y for y in range(n) for x in range(n)]


def test_dedither_blends_a_checkerboard():
    out = a2extras.dedither(checkerboard(4), 4, 4)
    # the corners have too few neighbours to tell a pattern from an edge
    corners = {0, 3, 12, 15}
    assert {p for i, p in enumerate(out) if i not in corners} == {(255, 127, 0, 255)}
    assert [out[i] for i in sorted(corners)] == [Y, R, R, Y]


def test_dedither_keeps_plain_areas_edges_and_transparency():
    # left half red, right half yellow, a transparent row at the bottom
    pixels = [R if x < 2 else Y for y in range(3) for x in range(4)] + [T] * 4
    assert a2extras.dedither(pixels, 4, 4) == pixels


def test_dedither_ignores_a_lone_pixel():
    pixels = [R] * 9
    pixels[4] = Y
    assert a2extras.dedither(pixels, 3, 3) == pixels


def fake_magick(pam, magnify_fails=False):
    """subprocess.run replacement: answers the PAM read with pam, records the writes and their input."""
    calls = []

    def run(cmd, input=None, capture_output=False, check=False):
        calls.append((cmd, input, check))
        if "PAM:-" in cmd:
            return mock.Mock(returncode=0, stdout=pam)
        return mock.Mock(returncode=1 if magnify_fails and "-magnify" in cmd else 0)

    return run, calls


def pam(w, h, pixels):
    header = f"P7\nWIDTH {w}\nHEIGHT {h}\nDEPTH 4\nMAXVAL 255\nTUPLTYPE RGB_ALPHA\nENDHDR\n".encode()
    return header + bytes(c for p in pixels for c in p)


def test_pixel_icon_dedithers_and_doubles_with_xbr(tmp_path):
    board = checkerboard(32)
    run, calls = fake_magick(pam(32, 32, board))
    out = str(tmp_path / "icons" / "a.png")
    with mock.patch("shutil.which", return_value="/usr/bin/magick"), mock.patch("subprocess.run", run):
        a2extras.pixel_icon("a.ico", out)
    (read, _, _), (write, data, check) = calls
    assert read == ["/usr/bin/magick", "a.ico", "-alpha", "set", "-depth", "8", "PAM:-"]
    assert write[:6] == ["/usr/bin/magick", "-size", "32x32", "-depth", "8", "RGBA:-"]
    assert write[6:] == ["-define", "magnify:method=xbr2X", "-magnify"] * 2 + ["-resize", "128x128", "PNG32:" + out]
    assert data == bytes(c for p in a2extras.dedither(board, 32, 32) for c in p) and not check
    assert data[4 * 33 : 4 * 34] == bytes((255, 127, 0, 255))
    assert os.path.isdir(tmp_path / "icons")


def test_pixel_icon_falls_back_to_sharp_pixels(tmp_path):
    run, calls = fake_magick(pam(48, 48, [R] * 48 * 48), magnify_fails=True)
    with mock.patch("shutil.which", return_value="/usr/bin/convert"), mock.patch("subprocess.run", run):
        a2extras.pixel_icon("a.ico", "out.png", 64)
    (magnify, _, _), (fallback, data, check) = calls[1:]
    assert magnify[6:9] == ["-define", "magnify:method=xbr2X", "-magnify"] and magnify.count("-magnify") == 1
    assert fallback[6:] == ["-filter", "point", "-resize", "64x64", "PNG32:out.png"] and check
    assert data == bytes(R) * 48 * 48


# Trainer


def test_install_trainer_from_a_zip(tmp_path):
    source = tmp_path / "t.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("Readme.txt", "read me")
        z.writestr("A2G-Trainer/Trainer.EXE", b"MZ trainer")
    target = tmp_path / "out" / "A2G-Trainer"
    exe = a2extras.install_trainer(str(source), str(target))
    assert exe == str(target / "A2G-Trainer.exe")
    assert (target / "A2G-Trainer.exe").read_bytes() == b"MZ trainer"


def test_install_trainer_rejects_a_zip_without_exe(tmp_path):
    source = tmp_path / "t.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("Readme.txt", "read me")
    with pytest.raises(SystemExit, match="no exe in the zip file"):
        a2extras.install_trainer(str(source), str(tmp_path / "out"))


def test_install_trainer_copies_an_exe(tmp_path):
    source = tmp_path / "trainer.exe"
    source.write_bytes(b"MZ trainer")
    exe = a2extras.install_trainer(str(source), str(tmp_path / "out"))
    assert open(exe, "rb").read() == b"MZ trainer"


def test_trainer_source_file_given():
    with mock.patch.object(a2extras, "pick") as pick:
        assert a2extras.trainer_source("file", "/x/t.zip", "/tmp") == "/x/t.zip"
    pick.assert_not_called()


@pytest.mark.parametrize("picked, expected", [("/x/t.exe", "/x/t.exe"), ("", None)])
def test_trainer_source_file_picked(picked, expected):
    with mock.patch.object(a2extras, "pick", return_value=picked) as pick:
        assert a2extras.trainer_source("file", None, "/tmp") == expected
    assert pick.call_args[0][0] == "file"


def test_trainer_source_none():
    with mock.patch("urllib.request.urlopen") as urlopen, mock.patch.object(a2extras, "pick") as pick:
        assert a2extras.trainer_source("none", None, "/tmp") is None
    urlopen.assert_not_called()
    pick.assert_not_called()


def test_trainer_source_download(tmp_path):
    with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"PK zip")) as urlopen:
        dest = a2extras.trainer_source("download", None, str(tmp_path))
    assert dest == str(tmp_path / "A2G-Trainer-Latest.zip")
    assert open(dest, "rb").read() == b"PK zip"
    req = urlopen.call_args[0][0]
    assert req.full_url == a2extras.TRAINER_URL
    assert req.get_header("User-agent") == "anstoss2-linux-installer"
    assert urlopen.call_args[1] == {"timeout": 60}


def test_trainer_source_download_failure_warns(tmp_path, capsys):
    with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")), mock.patch.object(
        a2extras, "zenity"
    ) as zen:
        assert a2extras.trainer_source("download", None, str(tmp_path)) is None
    assert "Download of A2G-Trainer failed: offline" in capsys.readouterr().out
    args = zen.call_args[0][0]
    assert args[0] == "--warning" and "(offline)" in args[-1]


def test_desktop_file(tmp_path, monkeypatch):
    monkeypatch.setattr(a2extras, "DATA", str(tmp_path))
    path = a2extras.desktop_file("Name", "Comment", '"/a2run.sh" editor', "slug-editor", "wm")
    assert path == str(tmp_path / "applications" / "slug-editor.desktop")
    assert open(path).read() == (
        '[Desktop Entry]\nType=Application\nName=Name\nComment=Comment\nExec="/a2run.sh" editor\n'
        "Icon=slug-editor\nStartupWMClass=wm\nCategories=Game;\n"
    )


def test_refresh_icon_cache_leaves_a_missing_cache_alone(tmp_path):
    os.utime(tmp_path, (1000, 1000))
    with mock.patch("shutil.which", return_value="/usr/bin/gtk-update-icon-cache"), mock.patch(
        "subprocess.run", return_value=mock.Mock(returncode=1)
    ):
        a2extras.refresh_icon_cache(str(tmp_path))
    assert os.stat(tmp_path).st_mtime == 1000
    assert not (tmp_path / "icon-theme.cache").exists()


# main()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A prefix, a fake a2run.sh and editor icon next to the script and DATA in tmp_path."""
    here = tmp_path / "src"
    here.mkdir()
    (here / "a2run.sh").write_text("#!/bin/sh\nSLUG=anstoss-2-gold  # set by a2extras.py\necho $SLUG\n")
    (here / "editor-icon.png").write_bytes(b"editor png")
    (here / "editor-icon.svg").write_text("<svg/>")
    monkeypatch.setattr(a2extras, "HERE", str(here))
    data = tmp_path / "data"
    monkeypatch.setattr(a2extras, "DATA", str(data))
    prefix = tmp_path / 'pre$fix "x" `y` \\z'
    (prefix / "drive_c" / "Spiele" / "Anstoss 2 Gold").mkdir(parents=True)
    calls = []

    def run(cmd, check, capture_output=False, input=None):
        calls.append(cmd)
        if "PAM:-" in cmd:  # pixel_icon reads the icon's pixels
            return mock.Mock(returncode=0, stdout=pam(1, 1, [R]))
        if cmd[0] == "magick":
            # Stands in for the PNG that ImageMagick writes
            open(cmd[-1][len("PNG32:") :], "wb").write(b"png")
        return mock.Mock(returncode=0)

    monkeypatch.setattr(a2extras.shutil, "which", lambda name: name)
    monkeypatch.setattr(a2extras.subprocess, "run", run)
    return mock.Mock(prefix=prefix, data=data, calls=calls)


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["a2extras.py"] + [str(a) for a in args])
    a2extras.main()


def test_main_installs_editor_and_trainer(setup, monkeypatch, tmp_path, capsys):
    trainer = icon_exe(tmp_path / "trainer.exe", small_only=True)
    run_main(monkeypatch, "--slug", "anstoss-2-gold-gog", setup.prefix, "file", trainer)

    run = setup.prefix / "a2run.sh"
    assert run.read_text() == "#!/bin/sh\nSLUG=anstoss-2-gold-gog  # set by a2extras.py\necho $SLUG\n"
    assert os.stat(run).st_mode & 0o777 == 0o755
    assert (
        setup.prefix / "drive_c" / "Spiele" / "A2G-Trainer" / "A2G-Trainer.exe"
    ).read_bytes() == trainer.read_bytes()

    icons = setup.data / "icons" / "hicolor" / "128x128" / "apps"
    assert (icons / "anstoss-2-gold-gog-editor.png").read_bytes() == b"editor png"
    assert (
        setup.data / "icons" / "hicolor" / "scalable" / "apps" / "anstoss-2-gold-gog-editor.svg"
    ).read_text() == "<svg/>"
    assert (icons / "anstoss-2-gold-gog-trainer.png").read_bytes() == b"png"
    q = '"' + str(run).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'
    apps = setup.data / "applications"
    editor = (apps / "anstoss-2-gold-gog-editor.desktop").read_text()
    assert "Name=Anstoss 2 Editor (GOG)\n" in editor and f"Exec={q} editor\n" in editor
    assert "StartupWMClass=anstoss-2-gold-gog-editor\n" in editor
    tr = (apps / "anstoss-2-gold-gog-trainer.desktop").read_text()
    assert "Name=A2G-Trainer (GOG)\n" in tr and f"Exec={q} trainer\n" in tr
    assert "StartupWMClass=a2g-trainer.exe\n" in tr
    # The editor's icon copied, the small trainer icon read and written, then the icon cache rebuilt
    assert [c[0] for c in setup.calls] == ["magick", "magick", "gtk-update-icon-cache"]
    assert setup.calls[-1][-1] == str(setup.data / "icons" / "hicolor")
    out = capsys.readouterr().out
    assert out.count("Written:") == 2 and "not installed" not in out


@pytest.mark.parametrize("slug, suffix", [(None, ""), ("anstoss-2-2007", " (2007)"), ("unknown", " (GOG)")])
def test_main_without_trainer_removes_an_old_entry(setup, monkeypatch, capsys, slug, suffix):
    name = slug or "anstoss-2-gold"
    old = setup.data / "applications" / f"{name}-trainer.desktop"
    old.parent.mkdir(parents=True)
    old.write_text("old")
    run_main(monkeypatch, *(["--slug", slug] if slug else []), setup.prefix, "none")

    assert not old.exists()
    editor = (setup.data / "applications" / f"{name}-editor.desktop").read_text()
    assert f"Name=Anstoss 2 Editor{suffix}\n" in editor
    assert not (setup.data / "icons" / "hicolor" / "128x128" / "apps" / f"{name}-trainer.png").exists()
    assert not (setup.prefix / "drive_c" / "Spiele" / "A2G-Trainer").exists()
    out = capsys.readouterr().out
    assert f"Removed: {old}" in out and "A2G-Trainer not installed" in out
    assert out.count("Removed:") == 1


def test_main_with_cancelled_file_dialog(setup, monkeypatch, capsys):
    with mock.patch.object(a2extras, "pick", return_value=""):
        run_main(monkeypatch, setup.prefix, "file")
    assert "A2G-Trainer not installed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args", [[], ["prefix"], ["prefix", "maybe"], ["prefix", "file", "a", "b"], ["--slug"], ["--slug", "x", "prefix"]]
)
def test_main_usage(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["a2extras.py"] + args)
    with pytest.raises(SystemExit) as e:
        a2extras.main()
    assert e.value.code == "a2extras.py [--slug SLUG] <prefix folder> none|download|file [zip or exe]"


def test_main_needs_the_slug_line(setup, monkeypatch):
    (setup.prefix.parent / "src" / "a2run.sh").write_text("#!/bin/sh\nSLUG=other\n")
    with pytest.raises(SystemExit, match="SLUG line missing"):
        run_main(monkeypatch, setup.prefix, "none")
    assert not (setup.prefix / "a2run.sh").exists()


def test_runs_as_a_script(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2extras.py"])
    with pytest.raises(SystemExit, match="none|download|file"):
        runpy.run_path(a2extras.__file__, run_name="__main__")
