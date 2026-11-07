#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Sets up the Anstoss 2 editor and, optionally, A2G-Trainer next to the game.

    a2extras.py [--slug SLUG] <prefix folder> none|download|file [zip or exe]

- copies a2run.sh into the prefix folder (with the slug for the menu entries, default
  anstoss-2-gold; install.sh uses the Lutris slug: anstoss-2-gold-edition for GOG,
  anstoss-2-gold-2007 for the 2007 CD; the lutris.net scripts use anstoss-2-cd, anstoss-2-2007
  and anstoss-2-gog, so every installation gets its own menu entries)
- trainer "download": fetches the latest release zip from GitHub; "file": a zip or exe given as
  third argument or chosen in a dialog; A2G-Trainer.exe goes to C:\\Spiele\\A2G-Trainer
- takes the icons out of Editor.exe and A2G-Trainer.exe
- writes the .desktop files "Anstoss 2 Editor" and "A2G-Trainer" for the application menu
  (without the trainer, an entry left from an earlier installation is removed)
- refreshes the icon cache of ~/.local/share/icons/hicolor, so that GNOME finds these icons and
  the game's icon (Lutris' cache would hide icons added after it)
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from a2import import pick, zenity  # noqa: E402

TRAINER_URL = "https://github.com/transfairs/A2G-Trainer/releases/latest/download/A2G-Trainer-Latest.zip"
DATA = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
RT_ICON, RT_GROUP_ICON = 3, 14
# Suffix of the menu entries' names per slug (CD: none)
SUFFIXES = {
    "anstoss-2-gold": "",
    "anstoss-2-gold-2007": " (2007)",
    "anstoss-2-gold-edition": " (GOG)",
    "anstoss-2-cd": "",
    "anstoss-2-2007": " (2007)",
    "anstoss-2-gog": " (GOG)",
}


def pe_resources(path):
    """{(type, name): [data, ...]} for the resources of a PE file (all languages)."""
    d = open(path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    magic = struct.unpack_from("<H", d, pe + 24)[0]
    rsrc_rva = struct.unpack_from("<I", d, pe + 24 + (112 if magic == 0x20B else 96) + 2 * 8)[0]
    sections = [struct.unpack_from("<8sIIII", d, pe + 24 + opt + i * 40) for i in range(nsec)]

    def off(rva):
        for _, vsize, va, rsize, raw in sections:
            if va <= rva < va + max(vsize, rsize):
                return raw + rva - va
        raise ValueError("RVA outside the sections")

    base = off(rsrc_rva)

    def entries(at):
        named, ids = struct.unpack_from("<HH", d, base + at + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from("<II", d, base + at + 16 + i * 8)
            yield name, target

    res = {}
    for typ, t in entries(0):
        for name, n in entries(t & 0x7FFFFFFF):
            for _, leaf in entries(n & 0x7FFFFFFF):
                rva, size = struct.unpack_from("<II", d, base + (leaf & 0x7FFFFFFF))
                res.setdefault((typ, name), []).append(d[off(rva) : off(rva) + size])
    return res


def exe_icon(exe, png, size=128):
    """Writes the largest icon of exe as a size x size PNG."""
    res = pe_resources(exe)
    group = next(v[0] for (t, _), v in sorted(res.items()) if t == RT_GROUP_ICON)
    count = struct.unpack_from("<H", group, 4)[0]
    best = None
    for i in range(count):
        w, h, colors, _, planes, bpp, _, icon_id = struct.unpack_from("<BBBBHHIH", group, 6 + i * 14)
        key = (w or 256, bpp)
        if best is None or key > best[0]:
            best = (key, (w, h, colors, planes, bpp, icon_id))
    w, h, colors, planes, bpp, icon_id = best[1]
    data = res[(RT_ICON, icon_id)][0]
    ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", w, h, colors, 0, planes, bpp, len(data), 22) + data
    with tempfile.NamedTemporaryFile(suffix=".ico") as f:
        f.write(ico)
        f.flush()
        im = shutil.which("magick") or shutil.which("convert")
        # Pixel art (old 32x32 icons) stays sharp, large icons are scaled smoothly
        flt = ["-filter", "point"] if (w or 256) < 64 else []
        subprocess.run([im, f.name] + flt + ["-resize", f"{size}x{size}", "PNG32:" + png], check=True)


def install_trainer(source, target_dir):
    os.makedirs(target_dir, exist_ok=True)
    exe = os.path.join(target_dir, "A2G-Trainer.exe")
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".exe")), None)
            if not name:
                sys.exit(f"{source}: no exe in the zip file")
            with z.open(name) as src, open(exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        shutil.copyfile(source, exe)
    return exe


def desktop_file(name, comment, exec_args, icon, wm_class):
    path = os.path.join(DATA, "applications", icon + ".desktop")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(
            "[Desktop Entry]\nType=Application\n"
            f"Name={name}\nComment={comment}\nExec={exec_args}\nIcon={icon}\n"
            f"StartupWMClass={wm_class}\nCategories=Game;\n"
        )
    return path


def trainer_source(mode, given, tmp):
    """Path of the trainer zip/exe to install, or None (not wanted, cancelled, download failed)."""
    if mode == "file":
        return (
            given
            or pick(
                "file", "A2G-Trainer (zip oder exe)", "A2G-Trainer (*.zip *.ZIP *.exe *.EXE) | *.zip *.ZIP *.exe *.EXE"
            )
            or None
        )
    if mode == "download":
        dest = os.path.join(tmp, "A2G-Trainer-Latest.zip")
        try:
            req = urllib.request.Request(TRAINER_URL, headers={"User-Agent": "anstoss2-linux-installer"})
            # TRAINER_URL is a fixed https URL
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # nosec B310
                shutil.copyfileobj(r, f)
            return dest
        except OSError as e:
            # The game is installed by now; a missing trainer must not fail the installation
            print(f"Download of A2G-Trainer failed: {e}")
            zenity(
                [
                    "--warning",
                    "--title",
                    "A2G-Trainer",
                    "--text",
                    f"A2G-Trainer konnte nicht heruntergeladen werden ({e}).\n"
                    "Das Spiel ist ohne ihn installiert. Um ihn nachzuinstallieren, den "
                    "Installer erneut starten oder eine lokale Datei wählen.",
                ]
            )
            return None
    return None


def refresh_icon_cache(hicolor):
    """Make icons added to hicolor visible. Lutris writes icon-theme.cache there when it starts;
    GTK and GNOME trust it as long as the folder hicolor is not newer than the cache, and adding a
    file to 128x128/apps does not change that folder. Rebuild the cache, or else mark it stale."""
    if not os.path.isdir(hicolor):
        return
    tool = shutil.which("gtk-update-icon-cache") or shutil.which("gtk4-update-icon-cache")
    if tool and subprocess.run([tool, "-q", "-t", "-f", hicolor], check=False).returncode == 0:  # nosec B603
        return
    if os.path.exists(os.path.join(hicolor, "icon-theme.cache")):
        os.utime(hicolor)


def main():
    args = sys.argv[1:]
    slug = "anstoss-2-gold"
    if args[:1] == ["--slug"] and len(args) > 1:
        slug, args = args[1], args[2:]
    if len(args) not in (2, 3) or args[1] not in ("none", "download", "file"):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    gamedir, mode = args[0], args[1]
    game = os.path.join(gamedir, "drive_c", "Spiele", "Anstoss 2 Gold")
    suffix = SUFFIXES.get(slug, " (GOG)")

    run = os.path.join(gamedir, "a2run.sh")
    with open(os.path.join(HERE, "a2run.sh")) as f:
        script = f.read()
    marker = "SLUG=anstoss-2-gold  #"
    if marker not in script:
        sys.exit("a2run.sh: SLUG line missing")
    with open(run, "w") as f:
        f.write(script.replace(marker, f"SLUG={slug}  #", 1))
    # The start script must be executable
    os.chmod(run, 0o755)  # nosec B103

    icons = os.path.join(DATA, "icons", "hicolor", "128x128", "apps")
    os.makedirs(icons, exist_ok=True)
    q = '"' + run.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'

    exe_icon(os.path.join(game, "Editor.exe"), os.path.join(icons, f"{slug}-editor.png"))
    print(
        "Written:",
        desktop_file(
            "Anstoss 2 Editor" + suffix,
            "Daten-Editor für Anstoss 2 Gold" + suffix,
            q + " editor",
            f"{slug}-editor",
            f"{slug}-editor",
        ),
    )

    with tempfile.TemporaryDirectory() as tmp:
        source = trainer_source(mode, args[2] if len(args) == 3 else None, tmp)
        trainer = install_trainer(source, os.path.join(gamedir, "drive_c", "Spiele", "A2G-Trainer")) if source else None

    if trainer:
        exe_icon(trainer, os.path.join(icons, f"{slug}-trainer.png"))
        print(
            "Written:",
            desktop_file(
                "A2G-Trainer" + suffix,
                "Trainer für Anstoss 2 Gold" + suffix + ", auch während das Spiel läuft",
                q + " trainer",
                f"{slug}-trainer",
                "a2g-trainer.exe",
            ),
        )
    else:
        # Without the trainer, an entry from an earlier installation would start nothing
        for old in (
            os.path.join(DATA, "applications", f"{slug}-trainer.desktop"),
            os.path.join(icons, f"{slug}-trainer.png"),
        ):
            if os.path.exists(old):
                os.remove(old)
                print("Removed:", old)
        print("A2G-Trainer not installed")
    refresh_icon_cache(os.path.join(DATA, "icons", "hicolor"))


if __name__ == "__main__":
    main()
