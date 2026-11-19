"""a2assets.py: wide font and Lutris images, with ImageMagick, the CD and GOG's API mocked."""

import io
import json
import os
import runpy
import struct
import sys
import types
import urllib.error

import pytest

import a2assets


def bitmap(w=300, h=386, bpp=8, colors=0):
    """BITMAPINFOHEADER plus palette and pixels of a resource bitmap (no BITMAPFILEHEADER)."""
    hdr = struct.pack("<IiiHHIIiiII", 40, w, h, 1, bpp, 0, 0, 0, 0, colors, 0)
    return hdr + bytes(4 * (colors or 256)) + b"pixels"


@pytest.fixture
def cd(tmp_path):
    folder = tmp_path / "cd" / "SETUP"
    folder.mkdir(parents=True)
    (folder / "AutoRun.EXE").write_bytes(b"MZ")
    return str(tmp_path / "cd")


@pytest.fixture
def run(monkeypatch):
    """Records the ImageMagick calls; magick is missing, convert is there."""
    calls = []
    monkeypatch.setattr(a2assets.shutil, "which", lambda name: "/usr/bin/convert" if name == "convert" else None)
    monkeypatch.setattr(a2assets.subprocess, "run", lambda cmd, check: calls.append((cmd, check)))
    return calls


def test_find_any_case_in_subfolders(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "AUTORUN.exe").write_bytes(b"")
    (tmp_path / "a" / "other.exe").write_bytes(b"")
    assert a2assets.find(str(tmp_path), "autorun.EXE") == str(tmp_path / "a" / "b" / "AUTORUN.exe")
    assert a2assets.find(str(tmp_path), "missing.exe") is None


def test_fonts_removes_old_files_and_builds_the_wide_font(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "fonts").mkdir(parents=True)
    (out / "a2wide24.fnt").write_bytes(b"old")
    (out / "keep.txt").write_bytes(b"")
    calls = []
    monkeypatch.setattr(a2assets.mkwide, "main", lambda src, dst: calls.append((src, dst)))
    a2assets.fonts("/wine/fonts", str(out))
    assert calls == [(os.path.join("/wine/fonts", "sserife.fon"), os.path.join(str(out), "a2wide"))]
    assert os.listdir(out) == ["keep.txt"]


def test_fonts_creates_the_output_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(a2assets.mkwide, "main", lambda src, dst: None)
    a2assets.fonts("/wine/fonts", str(tmp_path / "new" / "out"))
    assert (tmp_path / "new" / "out").is_dir()


def test_autorun_cover_without_autorun(tmp_path):
    assert a2assets.autorun_cover(str(tmp_path), str(tmp_path)) is None


def test_autorun_cover_with_a_broken_exe(cd, tmp_path):
    # the real PE parser fails on a 2-byte file
    assert a2assets.autorun_cover(cd, str(tmp_path)) is None


@pytest.mark.parametrize("resources", [{}, {(2, 130): [b""]}, {(2, 131): [bitmap()]}])
def test_autorun_cover_without_the_box_bitmap(cd, tmp_path, monkeypatch, resources):
    monkeypatch.setattr(a2assets, "pe_resources", lambda exe: resources)
    assert a2assets.autorun_cover(cd, str(tmp_path)) is None


@pytest.mark.parametrize("size", [(300, 385, 8), (301, 386, 8), (300, 386, 24)])
def test_autorun_cover_wrong_bitmap_size(cd, tmp_path, monkeypatch, size):
    monkeypatch.setattr(a2assets, "pe_resources", lambda exe: {(2, 130): [bitmap(*size)]})
    assert a2assets.autorun_cover(cd, str(tmp_path)) is None


@pytest.mark.parametrize("res_id, colors", [(130, 0), (129, 16)])
def test_autorun_cover_writes_a_bmp_file(cd, tmp_path, monkeypatch, res_id, colors):
    data = bitmap(colors=colors)
    monkeypatch.setattr(a2assets, "pe_resources", lambda exe: {(2, res_id): [data]})
    bmp = a2assets.autorun_cover(cd, str(tmp_path))
    assert bmp == str(tmp_path / "cover.bmp")
    out = open(bmp, "rb").read()
    # BITMAPFILEHEADER: size and offset of the pixels after header and palette
    assert struct.unpack_from("<2sIHHI", out) == (b"BM", 14 + len(data), 0, 0, 14 + 40 + 4 * (colors or 256))
    assert out[14:] == data


def test_media_cuts_banner_and_cover_from_the_box_art(cd, tmp_path, monkeypatch, run, capsys):
    monkeypatch.setattr(a2assets, "pe_resources", lambda exe: {(2, 130): [bitmap()]})
    banner, cover = tmp_path / "b" / "banner.jpg", tmp_path / "c" / "coverart.jpg"
    a2assets.media(cd, str(banner), str(cover))
    assert banner.parent.is_dir() and cover.parent.is_dir()
    assert len(run) == 3 and all(check for _, check in run)
    crop, compose, resize = (cmd for cmd, _ in run)
    bmp = crop[1]
    assert bmp.endswith("cover.bmp")
    logo = crop[-1]
    assert crop == ["/usr/bin/convert", bmp, "-crop", "255x150+24+0", "+repage", logo]
    assert compose[0] == "/usr/bin/convert" and compose[-1] == str(banner)
    assert compose.count(logo) == 2 and "-composite" in compose
    assert resize[:3] == ["/usr/bin/convert", bmp, "-crop"] and resize[-1] == str(cover)
    assert "264x352!" in resize
    assert capsys.readouterr().out.splitlines() == [
        "banner: from the box art on the CD",
        "cover: from the box art on the CD",
    ]


def test_media_without_box_art(tmp_path, run, capsys):
    banner, cover = tmp_path / "b" / "banner.jpg", tmp_path / "c" / "coverart.jpg"
    a2assets.media(str(tmp_path / "empty"), str(banner), str(cover))
    assert run == []
    assert banner.parent.is_dir() and cover.parent.is_dir()
    assert "No box art on the CD" in capsys.readouterr().out


@pytest.mark.parametrize("url", ["http://example.com/x.jpg", "file:///etc/passwd", None, 42])
def test_download_only_https(tmp_path, monkeypatch, url):
    monkeypatch.setattr(a2assets.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no request expected"))
    with pytest.raises(urllib.error.URLError, match="not an https URL"):
        a2assets.download(url, str(tmp_path / "x"))
    assert not (tmp_path / "x").exists()


def test_download_writes_the_response(tmp_path, monkeypatch):
    seen = []

    def urlopen(req, timeout):
        seen.append((req.full_url, req.get_header("User-agent"), timeout))
        return io.BytesIO(b"image data")

    monkeypatch.setattr(a2assets.urllib.request, "urlopen", urlopen)
    a2assets.download("https://images.example/box.jpg", str(tmp_path / "box.jpg"))
    assert seen == [("https://images.example/box.jpg", a2assets.USER_AGENT, 60)]
    assert (tmp_path / "box.jpg").read_bytes() == b"image data"


def gog(monkeypatch, api_body):
    """Fake download(): the API answer, then the two images; records the URLs."""
    urls = []

    def download(url, dest):
        urls.append(url)
        if url == a2assets.GOG_API.format("1234"):
            body = api_body
        elif url.startswith("https://"):
            body = url.encode()
        else:
            raise urllib.error.URLError(f"not an https URL: {url}")
        with open(dest, "wb") as f:
            f.write(body)

    monkeypatch.setattr(a2assets, "download", download)
    return urls


LINKS = {
    "_links": {"boxArtImage": {"href": "https://gog.example/box.jpg"}, "logo": {"href": "https://gog.example/l.png"}}
}


def test_media_gog_builds_banner_and_cover(tmp_path, monkeypatch, run, capsys):
    urls = gog(monkeypatch, json.dumps(LINKS).encode())
    banner, cover = tmp_path / "b" / "banner.jpg", tmp_path / "c" / "coverart.jpg"
    a2assets.media_gog("1234", str(banner), str(cover))
    assert urls == [a2assets.GOG_API.format("1234"), "https://gog.example/box.jpg", "https://gog.example/l.png"]
    assert banner.parent.is_dir() and cover.parent.is_dir()
    (cover_cmd, check1), (banner_cmd, check2) = run
    assert check1 and check2
    box = cover_cmd[1]
    assert box.endswith("box.jpg")
    assert cover_cmd == [
        "/usr/bin/convert",
        box,
        "-resize",
        "264x352^",
        "-gravity",
        "center",
        "-extent",
        "264x352",
        "-quality",
        "92",
        str(cover),
    ]
    assert banner_cmd[:2] == ["/usr/bin/convert", box] and banner_cmd[-1] == str(banner)
    assert any(arg.endswith("logo.png") for arg in banner_cmd) and "-composite" in banner_cmd
    assert "from GOG's images" in capsys.readouterr().out


@pytest.mark.parametrize(
    "body, error",
    [
        (b"not json", "Expecting value"),  # ValueError
        (b"{}", "'_links'"),  # KeyError
        (b"[]", "list indices"),  # TypeError
        (json.dumps({"_links": {"boxArtImage": {"href": "file:///x"}, "logo": {}}}).encode(), "not an https URL"),
    ],
)
def test_media_gog_without_images(tmp_path, monkeypatch, run, capsys, body, error):
    gog(monkeypatch, body)
    a2assets.media_gog("1234", str(tmp_path / "banner.jpg"), str(tmp_path / "coverart.jpg"))
    assert run == []
    out = capsys.readouterr().out
    assert out.startswith("Images from GOG not available (") and error in out
    assert out.rstrip().endswith("Lutris shows its default images")


def test_media_gog_offline(tmp_path, monkeypatch, run, capsys):
    def offline(url, dest):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(a2assets, "download", offline)
    a2assets.media_gog("1234", str(tmp_path / "banner.jpg"), str(tmp_path / "coverart.jpg"))
    assert run == []
    assert "no network" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args, func",
    [
        (["fonts", "w", "o"], "fonts"),
        (["media", "cd", "b", "c"], "media"),
        (["media-gog", "1234", "b", "c"], "media_gog"),
        (["icon", "game", "a.ico", "hicolor", "lutris_x"], "icon"),
        (["icon", "repo", "a.ico", "hicolor", "lutris_x", "desktop.bmp"], "icon"),
        (["icon", "file", "a.ico", "hicolor", "lutris_x"], "icon"),
    ],
)
def test_main_dispatches(monkeypatch, args, func):
    calls = []
    for name in ("fonts", "media", "media_gog", "icon"):
        monkeypatch.setattr(a2assets, name, lambda *a, name=name: calls.append((name, a)))
    monkeypatch.setattr(sys, "argv", ["a2assets.py", *args])
    a2assets.main()
    assert calls == [(func, tuple(args[1:]))]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["fonts", "w"],
        ["media", "cd", "b"],
        ["media-gog", "1"],
        ["icon", "a", "b"],
        ["icon", "repo", "a", "b"],
        ["icon", "repo", "a", "b", "c", "d", "e"],
        ["icon", "other", "a", "b", "c"],
        ["icon-check", "x"],
        ["other", "a", "b"],
    ],
)
def test_main_usage(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["a2assets.py", *args])
    with pytest.raises(SystemExit) as e:
        a2assets.main()
    lines = e.value.code.splitlines()
    assert [line.split()[:2] for line in lines] == [
        ["a2assets.py", "fonts"],
        ["a2assets.py", "media"],
        ["a2assets.py", "media-gog"],
        ["a2assets.py", "icon-check"],
        ["a2assets.py", "icon"],
    ]


@pytest.mark.parametrize("available, status", [(True, 0), (False, 1)])
def test_main_icon_check(monkeypatch, available, status):
    monkeypatch.setattr(a2assets, "icon_check", lambda: available)
    monkeypatch.setattr(sys, "argv", ["a2assets.py", "icon-check"])
    with pytest.raises(SystemExit) as e:
        a2assets.main()
    assert e.value.code == status


def test_script_entry_point(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["a2assets.py"])
    with pytest.raises(SystemExit, match="a2assets.py fonts"):
        runpy.run_path(a2assets.__file__, run_name="__main__")


# Icon

PNG = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 128, 128) + b"rest of the picture"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"></svg>'


def serve(monkeypatch, files):
    """Fake download(): writes files[url ending] or raises URLError; records the URLs."""
    urls = []

    def download(url, dest):
        urls.append(url)
        data = files.get(url.rsplit(".", 1)[1])
        if data is None:
            raise urllib.error.URLError("no network")
        with open(dest, "wb") as f:
            f.write(data)

    monkeypatch.setattr(a2assets, "download", download)
    return urls


@pytest.fixture
def hicolor(tmp_path):
    """An icon theme folder with an SVG left from an earlier installation."""
    folder = tmp_path / "hicolor"
    old_svg = folder / "scalable" / "apps" / "lutris_x.svg"
    old_svg.parent.mkdir(parents=True)
    old_svg.write_bytes(b"<svg>old</svg>")
    return folder


def installed(hicolor):
    return hicolor / "128x128" / "apps" / "lutris_x.png", hicolor / "scalable" / "apps" / "lutris_x.svg"


@pytest.mark.parametrize("files, available", [({"png": PNG, "svg": SVG}, True), ({}, False)])
def test_icon_check_fetches_a2g_icon(monkeypatch, files, available):
    urls = serve(monkeypatch, files)
    assert a2assets.icon_check() is available and urls[0] == a2assets.ICON_URL.format("png")


def test_icon_from_a2g_icon(hicolor, monkeypatch, run, capsys):
    urls = serve(monkeypatch, {"png": PNG, "svg": SVG})
    monkeypatch.setattr(a2assets, "own_icon", lambda: pytest.fail("no dialog when A2G-Icon is chosen"))
    a2assets.icon("repo", "game.ico", str(hicolor), "lutris_x")
    assert urls == [a2assets.ICON_URL.format("png"), a2assets.ICON_URL.format("svg")]
    assert urls[0] == "https://raw.githubusercontent.com/transfairs/A2G-Icon/main/anstoss2-icon.png"
    png, svg = installed(hicolor)
    assert png.read_bytes() == PNG and svg.read_bytes() == SVG
    assert run == [] and "from A2G-Icon" in capsys.readouterr().out


@pytest.mark.parametrize(
    "files, message",
    [
        ({}, "not available"),  # offline or the repository gone
        ({"png": PNG}, "not available"),
        ({"png": b"<html>not found</html>", "svg": SVG}, "not usable"),
        ({"png": PNG.replace(struct.pack(">II", 128, 128), struct.pack(">II", 64, 64)), "svg": SVG}, "not usable"),
        ({"png": PNG, "svg": b"<html>not found</html>"}, "not usable"),
    ],
)
def test_icon_falls_back_to_the_games_own(hicolor, monkeypatch, run, capsys, files, message):
    serve(monkeypatch, files)
    monkeypatch.setattr(a2assets, "own_icon", lambda: pytest.fail("no dialog when A2G-Icon is chosen"))
    a2assets.icon("repo", "game.ico", str(hicolor), "lutris_x")
    png, svg = installed(hicolor)
    assert run == [
        (["/usr/bin/convert", "game.ico", "-filter", "point", "-resize", "128x128", "PNG32:" + str(png)], True)
    ]
    assert not svg.exists()  # it would hide the game's icon in the dock
    out = capsys.readouterr().out
    assert f"Icon of A2G-Icon {message}" in out and "icon: the game's own\n" in out


def test_icon_fallback_without_an_earlier_svg(tmp_path, monkeypatch, run):
    serve(monkeypatch, {})
    a2assets.icon("repo", "game.ico", str(tmp_path / "hicolor"), "lutris_x")
    assert len(run) == 1 and not (tmp_path / "hicolor" / "scalable").exists()


def own(monkeypatch, tmp_path, png, svg, rsvg=True):
    """The user picks png and/or svg (written to tmp_path); returns their paths. Nothing is downloaded."""
    serve(monkeypatch, {"png": PNG, "svg": SVG})
    paths = []
    for name, data in (("own.png", png), ("own.svg", svg)):
        if data is not None:
            (tmp_path / name).write_bytes(data)
        paths.append(str(tmp_path / name) if data is not None else None)
    monkeypatch.setattr(a2assets, "own_icon", lambda: tuple(paths))
    tools = {"convert": "/usr/bin/convert", "rsvg-convert": "/usr/bin/rsvg-convert" if rsvg else None}
    monkeypatch.setattr(a2assets.shutil, "which", tools.get)
    return paths


def test_icon_picked_png_and_svg(hicolor, monkeypatch, tmp_path, run, capsys):
    own_png, _ = own(monkeypatch, tmp_path, PNG, SVG)
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x")
    png, svg = installed(hicolor)
    assert svg.read_bytes() == SVG
    fit = ["-resize", "128x128", "-background", "none", "-gravity", "center", "-extent", "128x128"]
    assert run == [(["/usr/bin/convert", own_png, *fit, "PNG32:" + str(png)], True)]
    assert "icon: picked by the user" in capsys.readouterr().out


def test_icon_picked_png_only(hicolor, monkeypatch, tmp_path, run):
    own_png, _ = own(monkeypatch, tmp_path, PNG, None)
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x")
    png, svg = installed(hicolor)
    assert not svg.exists() and run[0][0][1] == own_png


def test_icon_picked_svg_only_is_rendered_for_lutris(hicolor, monkeypatch, tmp_path, run):
    _, own_svg = own(monkeypatch, tmp_path, None, SVG)
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x")
    png, svg = installed(hicolor)
    assert svg.read_bytes() == SVG
    assert run == [(["/usr/bin/rsvg-convert", "-w", "128", "-h", "128", own_svg, "-o", str(png)], True)]


def gdkpixbuf(monkeypatch, error=None):
    """A stand-in for PyGObject's GdkPixbuf: writes "rendered <size>" or raises error; records calls."""
    calls = []

    class Pixbuf:
        @staticmethod
        def new_from_file_at_size(path, w, h):
            calls.append(("load", path, w, h))
            if error:
                raise error
            return Pixbuf()

        def savev(self, png, kind, keys, values):
            calls.append(("save", png, kind))
            with open(png, "w") as f:
                f.write("rendered")

    gi = types.ModuleType("gi")
    gi.require_version = lambda name, version: calls.append(("require", name, version))
    repository = types.ModuleType("gi.repository")
    repository.GdkPixbuf = types.SimpleNamespace(Pixbuf=Pixbuf)
    gi.repository = repository
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    return calls


def test_icon_picked_svg_rendered_with_gdkpixbuf_without_rsvg_convert(hicolor, monkeypatch, tmp_path, run, capsys):
    _, own_svg = own(monkeypatch, tmp_path, None, SVG, rsvg=False)
    calls = gdkpixbuf(monkeypatch)
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x")
    png, svg = installed(hicolor)
    assert calls == [("require", "GdkPixbuf", "2.0"), ("load", own_svg, 128, 128), ("save", str(png), "png")]
    assert png.read_text() == "rendered" and svg.read_bytes() == SVG and run == []
    assert "icon: picked by the user" in capsys.readouterr().out


@pytest.mark.parametrize("broken", ["no PyGObject", "unreadable SVG"])
def test_icon_picked_svg_that_cannot_be_rendered(hicolor, monkeypatch, tmp_path, run, capsys, broken):
    own(monkeypatch, tmp_path, None, SVG, rsvg=False)
    if broken == "no PyGObject":
        monkeypatch.setitem(sys.modules, "gi", None)  # import gi raises ImportError
    else:
        gdkpixbuf(monkeypatch, error=RuntimeError("Couldn't recognize the image file format"))
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x")
    png, svg = installed(hicolor)
    assert svg.read_bytes() == SVG and run[0][0][1:3] == ["game.ico", "-filter"]
    out = capsys.readouterr().out
    assert "SVG could not be rendered for Lutris" in out
    assert "icon: the game's own (dock: the SVG picked by the user)" in out


# The picture on the virtual desktop

FLATTEN = ["-alpha", "remove", "-alpha", "off"]


def desktop_call(src, bmp):
    fit = ["-resize", "256x256", "-background", "rgb(41,56,74)", "-gravity", "center", "-extent", "256x256"]
    return (["/usr/bin/convert", src, *fit, *FLATTEN, "BMP3:" + str(bmp)], True)


def test_desktop_color_is_the_background_of_the_lutris_scripts():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rgb = a2assets.DESKTOP_COLOR[4:-1].replace(",", " ")
    for name in ("anstoss2.yml.in", "lutris.net/anstoss-2-gold.yml"):
        with open(os.path.join(root, name)) as f:
            assert f'key: Background\n        value: "{rgb}"' in f.read()


def test_icon_from_a2g_icon_on_the_desktop(hicolor, monkeypatch, tmp_path, run, capsys):
    serve(monkeypatch, {"png": PNG, "svg": SVG})
    rendered = []
    monkeypatch.setattr(a2assets, "render_svg", lambda svg, png, size: rendered.append(size) or True)
    bmp = tmp_path / "game" / "a2desktop.bmp"
    a2assets.icon("repo", "game.ico", str(hicolor), "lutris_x", str(bmp))
    assert rendered == [256] and bmp.parent.is_dir()
    assert len(run) == 1 and run[0][0][1].endswith("icon.png") and run[0] == desktop_call(run[0][0][1], bmp)
    assert "desktop: A2G-Icon's icon" in capsys.readouterr().out


def test_icon_picked_png_on_the_desktop(hicolor, monkeypatch, tmp_path, run, capsys):
    own_png, _ = own(monkeypatch, tmp_path, PNG, None)
    bmp = tmp_path / "a2desktop.bmp"
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x", str(bmp))
    assert run[1] == desktop_call(own_png, bmp)
    assert "desktop: the icon picked by the user" in capsys.readouterr().out


def test_icon_picked_svg_on_the_desktop_without_a_png(hicolor, monkeypatch, tmp_path, run):
    _, own_svg = own(monkeypatch, tmp_path, None, SVG)
    bmp = tmp_path / "a2desktop.bmp"
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x", str(bmp))
    assert run[1][0][:6] == ["/usr/bin/rsvg-convert", "-w", "256", "-h", "256", own_svg]
    assert run[2] == desktop_call(run[1][0][-1], bmp)


@pytest.mark.parametrize("earlier", [True, False])
def test_games_own_icon_is_not_put_on_the_desktop(hicolor, monkeypatch, tmp_path, run, earlier):
    urls = serve(monkeypatch, {"png": PNG, "svg": SVG})
    monkeypatch.setattr(a2assets, "own_icon", lambda: pytest.fail("no dialog for the game's own icon"))
    bmp = tmp_path / "a2desktop.bmp"
    if earlier:
        bmp.write_bytes(b"BM from an earlier installation")
    a2assets.icon("game", "game.ico", str(hicolor), "lutris_x", str(bmp))
    png, svg = installed(hicolor)
    assert not bmp.exists() and not svg.exists() and urls == []
    assert run == [
        (["/usr/bin/convert", "game.ico", "-filter", "point", "-resize", "128x128", "PNG32:" + str(png)], True)
    ]


def test_icon_picked_nothing_falls_back_to_the_games_own(hicolor, monkeypatch, run, capsys):
    monkeypatch.setattr(a2assets, "own_icon", lambda: (None, None))
    a2assets.icon("file", "game.ico", str(hicolor), "lutris_x")
    assert run[0][0][1] == "game.ico" and "icon: the game's own\n" in capsys.readouterr().out


def test_desktop_picture_without_a_picture_it_can_use(tmp_path, monkeypatch, run):
    monkeypatch.setattr(a2assets, "render_svg", lambda svg, png, size: False)
    assert not a2assets.desktop_picture(None, "own.svg", str(tmp_path / "a2desktop.bmp"))
    assert run == []


# The dialog


def dialogs(monkeypatch, answers):
    """Fake zenity(): returns the answers in turn, records the dialogs; a display is there."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    asked = []

    def zenity(args):
        asked.append(args)
        return answers.pop(0)

    monkeypatch.setattr(a2assets, "zenity", zenity)
    return asked


def test_own_icon_takes_a_png_and_an_svg(monkeypatch, tmp_path, capsys):
    (tmp_path / "a.png").write_bytes(PNG)
    (tmp_path / "b.svg").write_bytes(SVG)
    (tmp_path / "c.png").write_bytes(PNG)
    (tmp_path / "d.txt").write_bytes(b"text")
    picked = "\n".join(str(tmp_path / n) for n in ("a.png", "b.svg", "c.png", "d.txt", "gone.png"))
    asked = dialogs(monkeypatch, [picked])
    assert a2assets.own_icon() == (str(tmp_path / "a.png"), str(tmp_path / "b.svg"))
    assert len(asked) == 1 and asked[0][:2] == ["--file-selection", "--multiple"] and "*.svg" in asked[0][-1]
    out = capsys.readouterr().out
    assert "d.txt: neither PNG nor SVG" in out and "gone.png" in out


def test_own_icon_file_dialog_cancelled(monkeypatch):
    asked = dialogs(monkeypatch, [None])
    assert a2assets.own_icon() == (None, None) and len(asked) == 1


def test_own_icon_without_a_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(a2assets, "zenity", lambda args: pytest.fail("no dialog without a display"))
    assert a2assets.own_icon() == (None, None)
