#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Copies a data set or save games into the game folder, from a zip file or a folder.

    a2import.py [--overwrite] [--title TEXT] zip|dir|none <game folder> [source]

Without a source, a zenity dialog asks for the zip file or folder; cancelling skips the import.
Names are matched against the game folder without regard to case (Wine ignores it, Linux does
not), so DATA.DEF in the source replaces data.def instead of ending up next to it. Without
--overwrite, existing files are kept. If everything in the source lies in one folder that the game
folder does not have (e.g. "Spielstaende/"), its contents are copied instead.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


def zenity(args):
    """Runs a zenity dialog; returns its output, or None if it was cancelled."""
    # Lutris passes its old runtime libraries (LD_LIBRARY_PATH) and the game's environment to
    # installer commands; zenity does not start with those libraries, and LD_PRELOAD,
    # GSETTINGS_SCHEMA_DIR and GSFIX_* are meant for Gamescope only.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("LD_LIBRARY_PATH", "GSETTINGS_SCHEMA_DIR", "LD_PRELOAD") and not k.startswith("GSFIX_")
    }
    try:
        r = subprocess.run(["zenity"] + args, capture_output=True, text=True, env=env)
    except FileNotFoundError:
        sys.exit("zenity is missing, please install it with your package manager")
    # 1 also means "cancelled", so look at the message as well
    if r.returncode not in (0, 1) or "required by" in r.stderr or "error while loading" in r.stderr:
        sys.exit(f"zenity failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else None


def pick(mode, title, file_filter="Zip (*.zip *.ZIP) | *.zip *.ZIP"):
    """A folder (mode "dir") or file chosen by the user, or "" if cancelled."""
    args = ["--file-selection", "--title", title]
    args += ["--directory"] if mode == "dir" else ["--file-filter", file_filter]
    return zenity(args) or ""


def match(folder, name):
    """name as it exists in folder (any case), or name itself."""
    if os.path.isdir(folder):
        lower = name.lower()
        for entry in os.listdir(folder):
            if entry.lower() == lower:
                return entry
    return name


def unwrap(src, game):
    entries = [e for e in os.listdir(src) if not e.startswith("__MACOSX")]
    if (
        len(entries) == 1
        and os.path.isdir(os.path.join(src, entries[0]))
        and not os.path.isdir(os.path.join(game, match(game, entries[0])))
    ):
        return os.path.join(src, entries[0])
    return src


def merge(src, dst, overwrite, counts):
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        d = os.path.join(dst, match(dst, name))
        if os.path.isdir(s):
            os.makedirs(d, exist_ok=True)
            merge(s, d, overwrite, counts)
        elif os.path.exists(d) and not overwrite:
            counts["kept"] += 1
        else:
            counts["replaced" if os.path.exists(d) else "added"] += 1
            shutil.copyfile(s, d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--title", default="Auswählen")
    ap.add_argument("mode", choices=["zip", "dir", "none"])
    ap.add_argument("game")
    ap.add_argument("source", nargs="?")
    a = ap.parse_args()
    if a.mode == "none":
        return
    source = a.source or pick(a.mode, a.title)
    if not source:
        print("Import skipped")
        return
    counts = {"added": 0, "replaced": 0, "kept": 0}
    with tempfile.TemporaryDirectory() as tmp:
        if a.mode == "zip":
            with zipfile.ZipFile(source) as z:
                for info in z.infolist():
                    parts = info.filename.replace("\\", "/").split("/")
                    if info.filename.startswith("/") or ".." in parts:
                        sys.exit(f"{source}: unsafe path in the zip file: {info.filename}")
                z.extractall(tmp)
            src = tmp
        else:
            src = source
        merge(unwrap(src, a.game), a.game, a.overwrite, counts)
    print(
        f"Imported from {source}: {counts['added']} added, {counts['replaced']} replaced, "
        f"{counts['kept']} kept (already present)"
    )


if __name__ == "__main__":
    main()
