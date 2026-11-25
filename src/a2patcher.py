#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Sets up and patches Anstoss 2 Gold inside the Wine prefix: the work of the lutris.net scripts.

    a2patcher.exe <gog|2007|cd> <source> [--dataset zip|dir] [--saves zip|dir] [--negotiation yes]
                  [--goals yes] [--speeches yes] [--coaches yes] [--euro yes] [--centreback yes]
                  [--names yes] [--quiz MODE]

The options are the questions of the installers (lowercase ids of their input menus), with their answers.

lutris.net only takes installer scripts that run in Lutris' Flatpak as well, which has none of the
system's programs (python3, ffmpeg, ImageMagick, zenity) and must not write to the home folder. The
lutris.net scripts therefore do in YAML what Lutris does itself (download, unpack, registry,
questions) and leave the rest to this program, in one wineexec step. The release workflow builds it
with PyInstaller into src/a2patcher.exe, a Windows program that runs under Wine like the game.
install.sh and anstoss2.yml.in do the same steps on the host with the scripts themselves.

<source> is a Linux path, which Wine reaches through drive Z:
- gog:  the GOG installer, unpacked by Lutris (innoextract). The game files go to the game folder;
        left out are DirectX, GOG's DirectDraw wrapper ddraw.dll, the compatibility database
        game.sdb, the goggame-* files and the installer's own folders. Taken from them: rest.sav
        (__support/save; without it a new game crashes) and ExSpiel.sav (app/DATA.DEF, app/DATA.VER).
- 2007: ANSTOSS_2_GOLD/Setup.exe of the DVD "ANSTOSS 2007", unpacked by Lutris (which leaves out
        the folder app, the only one in it; with app also taken); app is the game folder, with the
        CD's files in the folder CD, which becomes CD-ROM drive D:. run.exe is taken out of its
        PECRYPT32 shell (src/a2unpack.py).
- cd:   the 1999 CD. It is copied to the folder CD of the game folder, which becomes CD-ROM drive D:,
        and its setup runs from there without dialogs (SETUP.ISS with the game folder as target,
        through a2setup.exe).
Drive D: is set up through Wine's mount manager, as winecfg does it: the link in dosdevices and the
drive type in the registry stay, a CD that Wine had taken as D: before is replaced.

Then, as install.sh does: a2start.exe into the game folder, the bug fixes (src/a2patch.py, for 2007
and GOG also --disc-check and --v101), the Indeo 3 videos converted to MS Video 1 (Wine has no Indeo
decoder; ffmpeg.exe from the release, a build with just these codecs), for 2007 and GOG the data of
patch 1.01 (src/a2data101.py), for GOG the dialog styles of 1999 (src/a2resdll.py), a data set and
save games (src/a2import.py) from a zip file or folder picked in Windows' dialog (Wine's, which
reaches the home folder through drive Z:), the balancing patches asked for, the typing errors and
the text switches asked for (src/a2texts.py) and the quiz (src/a2quiz.py).

The game folder is C:\\Spiele\\Anstoss 2 Gold (--game for the tests). a2start.exe, a2setup.exe and
ffmpeg.exe are taken from the folder of this program. Exit status 1 if a step fails.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a2data101  # noqa: E402
import a2import  # noqa: E402
import a2patch  # noqa: E402
import a2quiz  # noqa: E402
import a2resdll  # noqa: E402
import a2texts  # noqa: E402
import a2unpack  # noqa: E402
from a2import import match  # noqa: E402

GAME = "C:\\Spiele\\Anstoss 2 Gold"
EXE = {"gog": "run.exe", "2007": "run.exe", "cd": "anstoss2.exe"}
# beyond --fixes and a2patch.ALWAYS, as install.sh's FIXES
FIXES = {"gog": ["--disc-check", "--v101"], "2007": ["--disc-check", "--v101"], "cd": []}
GOG_LEFT_OUT = {"__redist", "__support", "app", "commonappdata", "ddraw.dll", "game.sdb"}
# the questions: id of the input menu, its answers (the first one is the default)
QUESTIONS = {"DATASET": ("none", "zip", "dir"), "SAVES": ("none", "dir", "zip")}
QUESTIONS.update({k.upper(): ("no", "yes") for k in a2patch.BALANCING})
QUESTIONS.update({k: ("no", "yes") for k in a2texts.QUESTIONS})
QUESTIONS["QUIZ"] = tuple(a2quiz.MODES)
CD_DRIVE = "d"
# Wine's mount manager (include/ddk/mountmgr.h): IOCTL_MOUNTMGR_DEFINE_UNIX_DRIVE and struct
# mountmgr_unix_drive (size, type, fs_type, serial, unix_dev, letter, offsets of mount point, device
# and label); the mount point follows as a Unix path in bytes
MOUNTMGR = "\\\\.\\MountPointManager"
DEFINE_UNIX_DRIVE = (0x6D << 16) | (3 << 14) | (32 << 2)
UNIX_DRIVE = struct.Struct("<IIIIQHHHH")
DRIVE_CDROM = 5


class Failed(Exception):
    """A step failed; the message says which."""


def wine_path(path):
    """A Linux path as Windows path through drive Z: (under Wine), other paths unchanged."""
    if os.name == "nt" and path.startswith("/"):
        return "Z:" + path.replace("/", "\\")
    return path


def run(main, *args):
    """Runs the main() of one of the scripts with args as its command line; Failed on exit status != 0."""
    argv = sys.argv
    sys.argv = [main.__module__ + ".py", *args]
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, str):
                print(e.code)
            raise Failed(f"{main.__module__} {' '.join(args)}") from None
    finally:
        sys.argv = argv


def copy_tree(src, dst, left_out=()):
    """Copies the contents of src into dst, without the names in left_out (any case); the copies
    are writable (files from a CD are read-only)."""
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        if name.lower() in left_out:
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            copy_tree(s, d)
        else:
            shutil.copyfile(s, d)


def need(folder, name):
    """Path of name (any case) in folder; Failed if it is missing."""
    path = os.path.join(folder, match(folder, name))
    if not os.path.exists(path):
        raise Failed(f"{name} is missing in {folder}")
    return path


def install_gog(src, game):
    """The game files of the unpacked GOG installer into the game folder."""
    need(src, "run.exe")
    copy_tree(src, game, GOG_LEFT_OUT)
    for name in os.listdir(game):
        if name.lower().startswith("goggame-"):
            os.remove(os.path.join(game, name))
    copy_tree(need(need(src, "__support"), "save"), game)
    app = need(src, "app")
    for name in ("DATA.DEF", "DATA.VER"):
        copy_tree(need(app, name), os.path.join(game, name))
    need(game, "rest.sav")


def install_2007(src, game, mount):
    """The folder app of the unpacked ANSTOSS_2_GOLD/Setup.exe as game folder, its folder CD as D:
    (as Kalypso's compatibility.dll fakes it); run.exe unpacked. app is the only folder in the setup, and
    Lutris unpacks the contents of a single folder without the folder itself: then src is app."""
    app = src if os.path.exists(os.path.join(src, match(src, "run.exe"))) else need(src, "app")
    need(need(app, "CD"), "ARCHIVES")
    copy_tree(app, game)
    mount(CD_DRIVE, need(game, "CD"))
    run(a2unpack.main, need(game, "run.exe"))


def install_cd(src, game, ffmpeg, mount, setup):
    """Copies the CD to the folder CD, converts its videos, mounts it as D: and runs its setup."""
    iss = need(src, "SETUP.ISS")
    need(src, "SETUP.EXE")
    cd = os.path.join(game, "CD")
    copy_tree(src, cd)
    convert_videos(cd, ffmpeg)
    with open(iss, "rb") as f:
        lines = f.read().decode("cp1252").splitlines()
    target = [line for line in lines if line.startswith(("szPath=", "szDir="))]
    if len(target) != 2:
        raise Failed(f"{iss}: no szPath and szDir")
    lines = [line.split("=")[0] + "=" + GAME if line in target else line for line in lines]
    with open(os.path.join(cd, "a2setup.iss"), "wb") as f:
        f.write(("\r\n".join(lines) + "\r\n").encode("cp1252"))
    log = os.path.join(cd, "a2setup.log")
    if os.path.exists(log):
        os.remove(log)
    mount(CD_DRIVE, cd)
    drive = CD_DRIVE.upper() + ":\\"
    setup(
        [
            os.path.join(HERE, "a2setup.exe"),
            drive + "SETUP.EXE",
            "-s",
            f"-f1{drive}a2setup.iss",
            f"-f2{drive}a2setup.log",
        ]
    )
    result = open(log, encoding="cp1252").read() if os.path.exists(log) else ""
    if "ResultCode=0" not in result.split() or not os.path.exists(os.path.join(game, match(game, "anstoss2.exe"))):
        raise Failed(f"the setup failed, see {log}")


def unix_path(path):
    """The Unix path of a Windows path, from Wine's kernel32 (wine_get_unix_file_name)."""
    get = ctypes.windll.kernel32.wine_get_unix_file_name
    get.restype = ctypes.c_char_p
    get.argtypes = [ctypes.c_wchar_p]
    result = get(path)
    if not result:
        raise Failed(f"{path}: no Unix path")
    return result


def mount_cdrom(letter, folder):
    """Makes folder the CD-ROM drive letter: through Wine's mount manager, as winecfg does, so the
    link in dosdevices and the drive type in the registry stay for the next start."""
    point = unix_path(folder) + b"\0"
    data = UNIX_DRIVE.pack(UNIX_DRIVE.size + len(point), DRIVE_CDROM, 0, 0, 0, ord(letter), UNIX_DRIVE.size, 0, 0)
    data += point
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(MOUNTMGR, 0xC0000000, 3, None, 3, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise Failed("Wine's mount manager is not there")
    done = ctypes.c_ulong()
    ok = kernel32.DeviceIoControl(
        ctypes.c_void_p(handle), DEFINE_UNIX_DRIVE, data, len(data), None, 0, ctypes.byref(done), None
    )
    kernel32.CloseHandle(ctypes.c_void_p(handle))
    if not ok:
        raise Failed(f"drive {letter.upper()}: could not be set up")
    print(f"{folder} is drive {letter.upper()}:")


def run_setup(command):
    """Runs the setup through a2setup.exe; Failed on exit status != 0."""
    if subprocess.run(command).returncode != 0:
        raise Failed("the setup did not finish")


def ffmpeg_path():
    """ffmpeg.exe next to this program, else ffmpeg from PATH (tests under Linux)."""
    path = os.path.join(HERE, "ffmpeg.exe")
    return path if os.path.exists(path) else shutil.which("ffmpeg") or "ffmpeg"


def convert_videos(folder, ffmpeg):
    """Converts the Indeo 3 videos below folder to MS Video 1 with 16 bit (RGB555), the original kept as
    <name>.indeo3.bak; the other videos (MS Video 1 with 8 bit and palette) Wine plays itself."""
    n = 0
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            if not name.lower().endswith(".avi"):
                continue
            f = os.path.join(root, name)
            probe = subprocess.run([ffmpeg, "-hide_banner", "-i", f], capture_output=True, text=True)
            if "Video: indeo3" not in probe.stderr:
                continue
            print(f"Converting: {f}")
            tmp = f + ".tmp"
            command = [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", f, "-map", "0", "-c:v", "msvideo1"]
            command += ["-pix_fmt", "rgb555le", "-c:a", "copy", "-f", "avi", tmp]
            if subprocess.run(command).returncode != 0:
                raise Failed(f"{f} could not be converted")
            if not os.path.exists(f + ".indeo3.bak"):
                os.replace(f, f + ".indeo3.bak")
            os.replace(tmp, f)
            n += 1
    print(f"{n} video(s) converted in {folder}")


# the imports: question, title of the dialog, files replaced, only these files (a2import.py)
IMPORTS = (("DATASET", "Anstoss-2-Datensatz", True, None), ("SAVES", "Anstoss-2-Spielstände", False, a2import.SAVES))
WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
BROWSE_CALLBACK = WINFUNCTYPE(ctypes.c_int, wt.HWND, wt.UINT, wt.LPARAM, wt.LPARAM)


class OPENFILENAMEW(ctypes.Structure):
    """OPENFILENAMEW of commdlg.h (lpstrFilter and lpstrFile as addresses of buffers)."""

    _fields_ = [
        ("lStructSize", wt.DWORD),
        ("hwndOwner", wt.HWND),
        ("hInstance", wt.HINSTANCE),
        ("lpstrFilter", ctypes.c_void_p),
        ("lpstrCustomFilter", wt.LPWSTR),
        ("nMaxCustFilter", wt.DWORD),
        ("nFilterIndex", wt.DWORD),
        ("lpstrFile", ctypes.c_void_p),
        ("nMaxFile", wt.DWORD),
        ("lpstrFileTitle", wt.LPWSTR),
        ("nMaxFileTitle", wt.DWORD),
        ("lpstrInitialDir", wt.LPCWSTR),
        ("lpstrTitle", wt.LPCWSTR),
        ("Flags", wt.DWORD),
        ("nFileOffset", wt.WORD),
        ("nFileExtension", wt.WORD),
        ("lpstrDefExt", wt.LPCWSTR),
        ("lCustData", wt.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wt.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wt.DWORD),
        ("FlagsEx", wt.DWORD),
    ]


class BROWSEINFOW(ctypes.Structure):
    """BROWSEINFOW of shlobj.h."""

    _fields_ = [
        ("hwndOwner", wt.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", ctypes.c_void_p),
        ("lpszTitle", wt.LPCWSTR),
        ("ulFlags", wt.UINT),
        ("lpfn", BROWSE_CALLBACK),
        ("lParam", wt.LPARAM),
        ("iImage", ctypes.c_int),
    ]


def pick(mode, title):
    """A zip file (mode "zip") or folder chosen in Windows' dialog, starting in the home folder; "" if
    cancelled."""
    home = os.environ.get("HOME", "")
    start = wine_path(home) if home.startswith("/") else None
    path = ctypes.create_unicode_buffer(1024)
    if mode == "zip":
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(ofn)
        filters = ctypes.create_unicode_buffer("Zip-Dateien (*.zip)\0*.zip;*.ZIP\0\0")
        ofn.lpstrFilter = ctypes.addressof(filters)
        ofn.lpstrFile = ctypes.addressof(path)
        ofn.nMaxFile = len(path)
        ofn.lpstrInitialDir = start
        ofn.lpstrTitle = title
        ofn.Flags = 0x80000 | 0x1000 | 0x800 | 0x4  # OFN_EXPLORER, FILEMUSTEXIST, PATHMUSTEXIST, HIDEREADONLY
        return path.value if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)) else ""
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    first = ctypes.create_unicode_buffer(start or "")

    def init(hwnd, msg, lparam, data):
        if msg == 1 and start:  # BFFM_INITIALIZED: BFFM_SETSELECTIONW with the path
            user32.SendMessageW(hwnd, 0x400 + 103, 1, ctypes.addressof(first))
        return 0

    bi = BROWSEINFOW()
    bi.pszDisplayName = ctypes.addressof(path)
    bi.lpszTitle = title
    bi.ulFlags = 0x1 | 0x40  # BIF_RETURNONLYFSDIRS, BIF_NEWDIALOGSTYLE
    bi.lpfn = BROWSE_CALLBACK(init)
    ctypes.windll.ole32.CoInitialize(None)
    shell32 = ctypes.windll.shell32
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return ""
    ok = shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), path)
    ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    return path.value if ok else ""


def import_files(game, a):
    """The data set and the save games, each from a zip file or folder picked in a dialog if asked for
    (answer zip or dir); nothing if the dialog is cancelled."""
    for key, title, overwrite, only in IMPORTS:
        if a[key] == "none":
            continue
        source = pick(a[key], title)
        if not source:
            print(f"{title}: import skipped")
            continue
        try:
            print(a2import.report(source, a2import.copy_in(a[key], source, game, overwrite, only)))
        except SystemExit as e:
            raise Failed(str(e.code))


def option(key):
    """The command line option of a switch of a2patch.py, a2texts.py."""
    return "--" + key.replace("_", "-")


def patch(variant, game, ffmpeg, a):
    """a2start.exe, bug fixes, videos, data and texts of the game folder, with the answers in a
    ({question id: answer})."""
    shutil.copyfile(os.path.join(HERE, "a2start.exe"), os.path.join(game, "a2start.exe"))
    exe = need(game, EXE[variant])
    run(a2patch.main, "--fixes", *(option(k) for k in a2patch.ALWAYS), *FIXES[variant], exe)
    convert_videos(game, ffmpeg)
    if variant != "cd":
        run(a2data101.main, game)
    if variant == "gog":
        run(a2resdll.main, game)
    import_files(game, a)
    for key in a2patch.BALANCING:
        if a[key.upper()] == "yes":
            run(a2patch.main, option(key), exe)
    run(a2texts.main, *(option(k) for k in a2texts.ALWAYS), game)
    for key, switches in a2texts.QUESTIONS.items():
        if a[key] == "yes":
            run(a2texts.main, *(option(k) for k in switches), game)
    if a["QUIZ"] != "original":
        run(a2quiz.main, a["QUIZ"], game)


def main(mount=mount_cdrom, setup=run_setup):
    """Installs the variant from the source and patches it; exit status 1 if a step fails."""
    ap = argparse.ArgumentParser(description="Sets up and patches Anstoss 2 Gold in the Wine prefix.")
    ap.add_argument("variant", choices=sorted(EXE))
    ap.add_argument("source", help="Linux path of the unpacked installer (gog, 2007) or of the CD (cd)")
    for key, answers in QUESTIONS.items():
        ap.add_argument("--" + key.lower(), dest=key, choices=answers, default=answers[0])
    ap.add_argument("--game", default=GAME, help="game folder (tests)")
    ap.add_argument("--ffmpeg", default=ffmpeg_path(), help="ffmpeg to convert the videos with")
    a = ap.parse_args()
    src = wine_path(a.source)
    try:
        if not os.path.isdir(src):
            raise Failed(f"{src} is not a folder")
        if a.variant == "gog":
            install_gog(src, a.game)
        elif a.variant == "2007":
            install_2007(src, a.game, mount)
        else:
            install_cd(src, a.game, a.ffmpeg, mount, setup)
        patch(a.variant, a.game, a.ffmpeg, vars(a))
    except (Failed, OSError) as e:
        sys.exit(f"Installation failed: {e}")
    print("Anstoss 2 Gold is set up in " + a.game)


if __name__ == "__main__":
    main()
