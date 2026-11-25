"""a2patcher.py with stand-ins for ffmpeg, Wine's kernel32 and the scripts it runs: no game files needed."""

import ctypes
import os
import runpy
import stat
import sys

import pytest

import a2patcher as p

# a stand-in for ffmpeg: "Video: indeo3" for files that hold IV32, a conversion writes MSVC; FAIL fails
FAKE_FFMPEG = """#!{python}
import sys
args = sys.argv[1:]
data = open(args[args.index("-i") + 1], "rb").read()
if "-c:v" not in args:
    sys.stderr.write("Stream #0:0: Video: indeo3 (IV32)" if b"IV32" in data else "Stream #0:0: Video: msvideo1")
    sys.exit(1)
if b"FAIL" in data:
    sys.exit(1)
open(args[-1], "wb").write(b"MSVC")
"""


@pytest.fixture
def ffmpeg(tmp_path):
    path = tmp_path / "ffmpeg"
    path.write_text(FAKE_FFMPEG.format(python=sys.executable))
    path.chmod(0o755)
    return str(path)


def write(path, data=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_wine_path(monkeypatch):
    assert p.wine_path("/run/media/cd") == "/run/media/cd"
    monkeypatch.setattr(p.os, "name", "nt")
    assert p.wine_path("/run/media/cd") == "Z:\\run\\media\\cd"
    assert p.wine_path("C:\\Spiele") == "C:\\Spiele"


def script(code):
    """A stand-in for a script's main() that ends as code says."""

    def main():
        if code != "return":
            sys.exit(code)

    main.__module__ = "a2test"
    return main


@pytest.mark.parametrize("code", ["return", None, 0])
def test_run_passes(code):
    argv = sys.argv
    p.run(script(code), "x")
    assert sys.argv is argv


@pytest.mark.parametrize("code", [1, "a2test: unknown version"])
def test_run_fails(code, capsys):
    with pytest.raises(p.Failed, match="a2test --flag x"):
        p.run(script(code), "--flag", "x")
    assert ("unknown version" in capsys.readouterr().out) == isinstance(code, str)


def test_run_hands_over_the_command_line():
    seen = []
    main = script("return")

    def record():
        seen.append(list(sys.argv))

    record.__module__ = main.__module__
    p.run(record, "--typos", "C:\\game")
    assert seen == [["a2test.py", "--typos", "C:\\game"]]


def test_copy_tree_leaves_out_and_makes_writable(tmp_path):
    src = tmp_path / "src"
    write(src / "a.txt", b"a")
    write(src / "Sub" / "b.txt", b"b")
    write(src / "__Redist" / "dx.exe")
    (src / "a.txt").chmod(0o444)
    p.copy_tree(str(src), str(tmp_path / "dst"), {"__redist"})
    assert (tmp_path / "dst" / "a.txt").read_bytes() == b"a"
    assert (tmp_path / "dst" / "Sub" / "b.txt").read_bytes() == b"b"
    assert not (tmp_path / "dst" / "__Redist").exists()
    assert os.stat(tmp_path / "dst" / "a.txt").st_mode & stat.S_IWUSR


def test_need(tmp_path):
    write(tmp_path / "RUN.EXE")
    assert p.need(str(tmp_path), "run.exe") == str(tmp_path / "RUN.EXE")
    with pytest.raises(p.Failed, match="rest.sav is missing"):
        p.need(str(tmp_path), "rest.sav")


def gog_source(tmp_path):
    src = tmp_path / "gog"
    for name in ("run.exe", "RESDLL.dll", "ARCHIVES/x.cpr", "ddraw.dll", "game.sdb", "goggame-1808817480.id"):
        write(src / name, name.encode())
    write(src / "__support" / "save" / "rest.sav", b"rest")
    write(src / "__redist" / "DirectX" / "dx.exe")
    write(src / "commonappdata" / "x")
    write(src / "app" / "DATA.DEF" / "ExSpiel.sav", b"def")
    write(src / "app" / "DATA.VER" / "ExSpiel.sav", b"ver")
    return src


def test_install_gog(tmp_path):
    game = tmp_path / "game"
    p.install_gog(str(gog_source(tmp_path)), str(game))
    assert sorted(os.listdir(game)) == ["ARCHIVES", "DATA.DEF", "DATA.VER", "RESDLL.dll", "rest.sav", "run.exe"]
    assert (game / "DATA.VER" / "ExSpiel.sav").read_bytes() == b"ver"


def test_install_gog_needs_rest_sav(tmp_path):
    src = gog_source(tmp_path)
    os.remove(src / "__support" / "save" / "rest.sav")
    with pytest.raises(p.Failed, match="rest.sav"):
        p.install_gog(str(src), str(tmp_path / "game"))


def test_install_gog_needs_run_exe(tmp_path):
    with pytest.raises(p.Failed, match="run.exe"):
        p.install_gog(str(tmp_path), str(tmp_path / "game"))


def test_install_2007(tmp_path, monkeypatch):
    src = tmp_path / "dvd"
    write(src / "app" / "run.exe")
    write(src / "app" / "CD" / "ARCHIVES" / "COMMENTS.CPR")
    calls = []
    monkeypatch.setattr(p, "run", lambda main, *args: calls.append((main.__module__, args)))
    mounted = []
    game = tmp_path / "game"
    p.install_2007(str(src), str(game), lambda letter, folder: mounted.append((letter, folder)))
    assert (game / "CD" / "ARCHIVES" / "COMMENTS.CPR").exists()
    assert mounted == [("d", str(game / "CD"))]
    assert calls == [("a2unpack", (str(game / "run.exe"),))]


def test_install_2007_without_the_folder_app(tmp_path, monkeypatch):
    """Lutris unpacks the contents of the setup's only folder app directly."""
    src = tmp_path / "dvd"
    write(src / "run.exe")
    write(src / "CD" / "ARCHIVES" / "COMMENTS.CPR")
    monkeypatch.setattr(p, "run", lambda main, *args: None)
    game = tmp_path / "game"
    p.install_2007(str(src), str(game), lambda letter, folder: None)
    assert (game / "CD" / "ARCHIVES" / "COMMENTS.CPR").exists() and (game / "run.exe").exists()


def test_install_2007_needs_the_cd_files(tmp_path):
    write(tmp_path / "dvd" / "app" / "run.exe")
    with pytest.raises(p.Failed, match="CD is missing"):
        p.install_2007(str(tmp_path / "dvd"), str(tmp_path / "game"), None)


ISS = b"[InstallShield Silent]\r\nszDir=C:\\Programme\\Ascaron\r\nszPath=C:\\Programme\\Ascaron\r\nResult=1\r\n"


def cd_source(tmp_path, iss=ISS):
    src = tmp_path / "cdrom"
    write(src / "SETUP.EXE")
    write(src / "SETUP.ISS", iss)
    write(src / "Videos" / "INTRO.AVI", b"RIFF IV32")
    for f in src.rglob("*"):
        if f.is_file():
            f.chmod(0o444)
    return src


def fake_setup(game, result="0", exe=True):
    """A stand-in for a2setup.exe: writes the log to the CD copy and anstoss2.exe to the game folder."""
    calls = []

    def setup(command):
        calls.append(command)
        (game / "CD" / "a2setup.log").write_text(f"[ResponseResult]\nResultCode={result}\n", encoding="cp1252")
        if exe:
            write(game / "ANSTOSS2.EXE")

    return setup, calls


def test_install_cd(tmp_path, ffmpeg):
    game = tmp_path / "game"
    write(game / "CD" / "a2setup.log", b"ResultCode=0")  # of an earlier try: removed before the setup
    mounted = []
    setup, calls = fake_setup(game)
    p.install_cd(str(cd_source(tmp_path)), str(game), ffmpeg, lambda *a: mounted.append(a), setup)
    iss = (game / "CD" / "a2setup.iss").read_bytes()
    assert iss == ISS.replace(b"C:\\Programme\\Ascaron", b"C:\\Spiele\\Anstoss 2 Gold")
    assert (game / "CD" / "Videos" / "INTRO.AVI").read_bytes() == b"MSVC"
    assert mounted == [("d", str(game / "CD"))]
    assert calls == [
        [os.path.join(p.HERE, "a2setup.exe"), "D:\\SETUP.EXE", "-s", "-f1D:\\a2setup.iss", "-f2D:\\a2setup.log"]
    ]


def test_install_cd_without_target_in_setup_iss(tmp_path, ffmpeg):
    with pytest.raises(p.Failed, match="no szPath and szDir"):
        p.install_cd(str(cd_source(tmp_path, b"[x]\r\nszDir=C:\\x\r\n")), str(tmp_path / "game"), ffmpeg, None, None)


@pytest.mark.parametrize("result, exe", [("-3", True), ("0", False)])
def test_install_cd_setup_failed(tmp_path, ffmpeg, result, exe):
    game = tmp_path / "game"
    setup, _ = fake_setup(game, result, exe)
    with pytest.raises(p.Failed, match="the setup failed"):
        p.install_cd(str(cd_source(tmp_path)), str(game), ffmpeg, lambda *a: None, setup)


def test_install_cd_setup_without_log(tmp_path, ffmpeg):
    with pytest.raises(p.Failed, match="the setup failed"):
        p.install_cd(str(cd_source(tmp_path)), str(tmp_path / "game"), ffmpeg, lambda *a: None, lambda c: None)


class Kernel32:
    """A stand-in for Wine's kernel32: the calls of unix_path() and mount_cdrom()."""

    def __init__(self, unix=b"/prefix/dosdevices/c:/Spiele/Anstoss 2 Gold/CD", handle=8, ok=1):
        self.unix, self.handle, self.ok, self.ioctl, self.closed = unix, handle, ok, None, []
        self.wine_get_unix_file_name = self.function(lambda path: self.unix)
        self.CreateFileW = self.function(lambda *args: self.handle)

    @staticmethod
    def function(f):
        def call(*args):
            return f(*args)

        return call

    def DeviceIoControl(self, handle, code, data, size, *rest):
        self.ioctl = (handle.value, code, data, size)
        return self.ok

    def CloseHandle(self, handle):
        self.closed.append(handle.value)


@pytest.fixture
def kernel32(monkeypatch):
    k = Kernel32()
    monkeypatch.setattr(ctypes, "windll", type("WinDLL", (), {"kernel32": k}), raising=False)
    return k


def test_mount_cdrom(kernel32, capsys):
    p.mount_cdrom("d", "C:\\Spiele\\Anstoss 2 Gold\\CD")
    handle, code, data, size = kernel32.ioctl
    point = kernel32.unix + b"\0"
    assert (handle, code, size) == (8, 0x6DC080, 32 + len(point))
    assert p.UNIX_DRIVE.unpack(data[:32]) == (32 + len(point), 5, 0, 0, 0, ord("d"), 32, 0, 0)
    assert data[32:] == point and kernel32.closed == [8]
    assert "is drive D:" in capsys.readouterr().out


def test_mount_cdrom_without_unix_path(kernel32):
    kernel32.unix = None
    with pytest.raises(p.Failed, match="no Unix path"):
        p.mount_cdrom("d", "C:\\x")


@pytest.mark.parametrize("handle", [None, ctypes.c_void_p(-1).value])
def test_mount_cdrom_without_mount_manager(kernel32, handle):
    kernel32.handle = handle
    with pytest.raises(p.Failed, match="mount manager"):
        p.mount_cdrom("d", "C:\\x")


def test_mount_cdrom_refused(kernel32):
    kernel32.ok = 0
    with pytest.raises(p.Failed, match="drive D: could not be set up"):
        p.mount_cdrom("d", "C:\\x")
    assert kernel32.closed == [8]


def test_run_setup():
    p.run_setup([sys.executable, "-c", "pass"])
    with pytest.raises(p.Failed, match="did not finish"):
        p.run_setup([sys.executable, "-c", "raise SystemExit(3)"])


def test_ffmpeg_path(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "HERE", str(tmp_path))
    monkeypatch.setattr(p.shutil, "which", lambda name: None)
    assert p.ffmpeg_path() == "ffmpeg"
    monkeypatch.setattr(p.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert p.ffmpeg_path() == "/usr/bin/ffmpeg"
    write(tmp_path / "ffmpeg.exe")
    assert p.ffmpeg_path() == str(tmp_path / "ffmpeg.exe")


def test_convert_videos(tmp_path, ffmpeg, capsys):
    write(tmp_path / "VIDEOS" / "INTRO.AVI", b"RIFF IV32")
    write(tmp_path / "VIDEOS" / "LOGO.avi", b"RIFF MSVC")
    write(tmp_path / "VIDEOS" / "README.TXT", b"IV32")
    write(tmp_path / "CD" / "EM.AVI", b"RIFF IV32 new")
    write(tmp_path / "CD" / "EM.AVI.indeo3.bak", b"first original")
    p.convert_videos(str(tmp_path), ffmpeg)
    assert (tmp_path / "VIDEOS" / "INTRO.AVI").read_bytes() == b"MSVC"
    assert (tmp_path / "VIDEOS" / "INTRO.AVI.indeo3.bak").read_bytes() == b"RIFF IV32"
    assert (tmp_path / "VIDEOS" / "LOGO.avi").read_bytes() == b"RIFF MSVC"
    assert (tmp_path / "VIDEOS" / "README.TXT").read_bytes() == b"IV32"
    assert (tmp_path / "CD" / "EM.AVI.indeo3.bak").read_bytes() == b"first original"
    assert "2 video(s) converted" in capsys.readouterr().out


def test_convert_videos_fails(tmp_path, ffmpeg):
    write(tmp_path / "INTRO.AVI", b"RIFF IV32 FAIL")
    with pytest.raises(p.Failed, match="could not be converted"):
        p.convert_videos(str(tmp_path), ffmpeg)


class Dialogs:
    """Stand-ins for comdlg32, shell32, user32 and ole32: the calls of pick(), answered with path ("" cancels)."""

    def __init__(self, path):
        self.path, self.calls = path, []
        fn = Kernel32.function
        self.comdlg32 = type("comdlg32", (), {"GetOpenFileNameW": staticmethod(fn(self.open_file))})()
        self.shell32 = type(
            "shell32",
            (),
            {
                "SHBrowseForFolderW": staticmethod(fn(self.browse)),
                "SHGetPathFromIDListW": staticmethod(fn(self.path_of)),
            },
        )()
        self.user32 = type("user32", (), {"SendMessageW": staticmethod(fn(self.send))})()
        self.ole32 = type(
            "ole32",
            (),
            {
                "CoInitialize": staticmethod(lambda reserved: self.calls.append(("CoInitialize",))),
                "CoTaskMemFree": staticmethod(lambda pidl: self.calls.append(("CoTaskMemFree", pidl.value))),
            },
        )()

    def put(self, address):
        text = ctypes.create_unicode_buffer(self.path)
        ctypes.memmove(address, text, ctypes.sizeof(text))

    def open_file(self, ref):
        ofn = ref._obj
        filters = ctypes.wstring_at(ofn.lpstrFilter, 33)
        self.calls.append(("GetOpenFileNameW", ofn.lpstrTitle, ofn.lpstrInitialDir, filters, ofn.Flags))
        if not self.path:
            return 0
        self.put(ofn.lpstrFile)
        return 1

    def browse(self, ref):
        bi = ref._obj
        self.calls.append(("SHBrowseForFolderW", bi.lpszTitle, bi.ulFlags))
        bi.lpfn(7, 2, 0, 0)  # another message: nothing to do
        bi.lpfn(7, 1, 0, 0)  # BFFM_INITIALIZED
        return 1234 if self.path else None

    def path_of(self, pidl, buffer):
        self.calls.append(("SHGetPathFromIDListW", pidl.value))
        buffer.value = self.path
        return 1

    def send(self, hwnd, msg, wparam, lparam):
        self.calls.append(("SendMessageW", hwnd, msg, wparam, ctypes.wstring_at(lparam)))


@pytest.fixture
def dialogs(monkeypatch):
    def make(path, home="/home/u"):
        d = Dialogs(path)
        monkeypatch.setattr(ctypes, "windll", d, raising=False)
        monkeypatch.setenv("HOME", home)
        return d

    return make


def test_pick_zip(dialogs):
    d = dialogs("Z:\\home\\u\\set.zip")
    assert p.pick("zip", "Anstoss-2-Datensatz") == "Z:\\home\\u\\set.zip"
    assert d.calls == [
        ("GetOpenFileNameW", "Anstoss-2-Datensatz", "/home/u", "Zip-Dateien (*.zip)\0*.zip;*.ZIP\0\0", 0x81804)
    ]


def test_pick_zip_cancelled(dialogs):
    dialogs("", home="")
    assert p.pick("zip", "x") == ""


def test_pick_dir(dialogs):
    d = dialogs("Z:\\home\\u\\saves")
    assert p.pick("dir", "Anstoss-2-Spielstände") == "Z:\\home\\u\\saves"
    assert d.calls == [
        ("CoInitialize",),
        ("SHBrowseForFolderW", "Anstoss-2-Spielstände", 0x41),
        ("SendMessageW", 7, 0x400 + 103, 1, "/home/u"),
        ("SHGetPathFromIDListW", 1234),
        ("CoTaskMemFree", 1234),
    ]


def test_pick_dir_cancelled(dialogs):
    d = dialogs("", home="relative")
    assert p.pick("dir", "x") == ""
    assert ("SendMessageW" not in [c[0] for c in d.calls]) and ("CoTaskMemFree" not in [c[0] for c in d.calls])


def test_pick_dir_without_path(dialogs, monkeypatch):
    d = dialogs("Z:\\x")
    monkeypatch.setattr(d.shell32, "SHGetPathFromIDListW", lambda pidl, buffer: 0, raising=False)
    assert p.pick("dir", "x") == ""


def test_import_files(tmp_path, monkeypatch, capsys):
    game, data, saves = tmp_path / "game", tmp_path / "data", tmp_path / "saves"
    write(game / "DATA.DEF" / "A.SAV", b"old")
    write(game / "a.gld", b"old")
    write(data / "data.def" / "a.sav", b"new")
    write(saves / "a.gld", b"new")
    write(saves / "b.syt", b"new")
    write(saves / "notes.txt", b"new")
    picked = {"Anstoss-2-Datensatz": str(data), "Anstoss-2-Spielstände": str(saves)}
    monkeypatch.setattr(p, "pick", lambda mode, title: picked[title])
    p.import_files(str(game), answers(DATASET="dir", SAVES="dir"))
    assert (game / "DATA.DEF" / "A.SAV").read_bytes() == b"new"
    assert (game / "a.gld").read_bytes() == b"old"
    assert sorted(f.name for f in game.iterdir()) == ["DATA.DEF", "a.gld", "b.syt"]
    out = capsys.readouterr().out
    assert "0 added, 1 replaced, 0 kept" in out and "1 added, 0 replaced, 1 kept" in out


def test_import_files_skipped_and_refused(tmp_path, monkeypatch, capsys):
    import zipfile

    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../evil.gld", "x")
    monkeypatch.setattr(p, "pick", lambda mode, title: "" if title == "Anstoss-2-Datensatz" else str(archive))
    with pytest.raises(p.Failed, match="unsafe path"):
        p.import_files(str(tmp_path), answers(DATASET="zip", SAVES="zip"))
    assert "Anstoss-2-Datensatz: import skipped" in capsys.readouterr().out


def answers(**given):
    a = {k: v[0] for k, v in p.QUESTIONS.items()}
    a.update(given)
    return a


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """The scripts' calls of patch() as [(module, args)], with a2start.exe from tmp_path/here."""
    calls = []
    monkeypatch.setattr(p, "run", lambda main, *args: calls.append((main.__module__, list(args))))
    monkeypatch.setattr(p, "convert_videos", lambda folder, ffmpeg: calls.append(("videos", [folder, ffmpeg])))
    monkeypatch.setattr(p, "HERE", str(tmp_path / "here"))
    write(tmp_path / "here" / "a2start.exe", b"a2start")
    return calls


def test_patch_gog_with_everything(tmp_path, recorded):
    game = tmp_path / "game"
    write(game / "RUN.EXE")
    yes = {k: "yes" for k, v in p.QUESTIONS.items() if v == ("no", "yes")}
    p.patch("gog", str(game), "ff", answers(QUIZ="both", **yes))
    exe, g = str(game / "RUN.EXE"), str(game)
    assert (game / "a2start.exe").read_bytes() == b"a2start"
    assert recorded == [
        ("a2patch", ["--fixes", "--interviews", "--disc-check", "--v101", exe]),
        ("videos", [g, "ff"]),
        ("a2data101", [g]),
        ("a2resdll", [g]),
        ("a2patch", ["--negotiation", exe]),
        ("a2patch", ["--goals", exe]),
        ("a2patch", ["--speeches", exe]),
        ("a2patch", ["--coaches", exe]),
        ("a2texts", ["--typos", g]),
        ("a2texts", ["--euro", g]),
        ("a2texts", ["--centre-back", g]),
        ("a2texts", ["--cups", "--leagues", "--groups", g]),
        ("a2quiz", ["both", g]),
    ]


@pytest.mark.parametrize("variant, exe, data", [("2007", "run.exe", True), ("cd", "anstoss2.exe", False)])
def test_patch_with_the_defaults(tmp_path, recorded, variant, exe, data):
    game = tmp_path / "game"
    write(game / exe)
    p.patch(variant, str(game), "ff", answers())
    path, g = str(game / exe), str(game)
    expected = [("a2patch", ["--fixes", "--interviews", *p.FIXES[variant], path]), ("videos", [g, "ff"])]
    expected += [("a2data101", [g])] if data else []
    expected += [("a2texts", ["--typos", g])]
    assert recorded == expected


def test_patch_needs_the_exe(tmp_path, recorded):
    with pytest.raises(p.Failed, match="anstoss2.exe is missing"):
        p.patch("cd", str(tmp_path), "ff", answers())


def call_main(monkeypatch, *argv, **kwargs):
    monkeypatch.setattr(sys, "argv", ["a2patcher.py", *argv])
    p.main(**kwargs)


@pytest.mark.parametrize("variant", ["gog", "2007", "cd"])
def test_main(tmp_path, monkeypatch, capsys, variant):
    calls = []
    for name in ("install_gog", "install_2007", "install_cd"):
        monkeypatch.setattr(p, name, lambda *a, name=name: calls.append((name, a)))
    monkeypatch.setattr(p, "patch", lambda *a: calls.append(("patch", a)))
    game = str(tmp_path / "game")
    call_main(monkeypatch, variant, str(tmp_path), "--game", game, "--ffmpeg", "ff", "--goals", "yes", "--quiz", "new")
    src = str(tmp_path)
    installs = {
        "gog": ("install_gog", (src, game)),
        "2007": ("install_2007", (src, game, p.mount_cdrom)),
        "cd": ("install_cd", (src, game, "ff", p.mount_cdrom, p.run_setup)),
    }
    assert calls[0] == installs[variant]
    assert calls[1][0] == "patch" and calls[1][1][:3] == (variant, game, "ff")
    chosen = {k: v for k, v in calls[1][1][3].items() if k in p.QUESTIONS}
    assert chosen == answers(GOALS="yes", QUIZ="new")
    assert "Anstoss 2 Gold is set up in " + game in capsys.readouterr().out


def test_main_without_source(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="is not a folder"):
        call_main(monkeypatch, "gog", str(tmp_path / "missing"))


def test_main_when_a_step_fails(tmp_path, monkeypatch):
    def fail(*args):
        raise p.Failed("run.exe is missing in x")

    monkeypatch.setattr(p, "install_gog", fail)
    with pytest.raises(SystemExit, match="Installation failed: run.exe is missing in x"):
        call_main(monkeypatch, "gog", str(tmp_path))


def test_main_on_the_command_line(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["a2patcher.py", "--help"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(p.__file__, run_name="__main__")
    assert e.value.code == 0 and "--centreback" in capsys.readouterr().out
