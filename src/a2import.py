#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Copies a data set or save games into the game folder, from a zip file or a folder.

    a2import.py [--overwrite] [--saves] [--title TEXT] zip|dir|none <game folder> [source]

Without a source, a zenity dialog asks for the zip file or folder; cancelling skips the import.
Names are matched against the game folder without regard to case (Wine ignores it, Linux does
not), so DATA.DEF in the source replaces data.def instead of ending up next to it. Without
--overwrite, existing files are kept. If everything in the source lies in one folder that the game
folder does not have (e.g. "Spielstaende/"), its contents are copied instead. With --saves, only
save games are copied: those of the game (*.gld) and of "ANSTOSS 2: Verlängerung!" (*.ver), with the
game systems (*.syt) and training weeks (*.woc) saved next to them.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

# Save games of Anstoss 2 Gold (*.gld) and of "ANSTOSS 2: Verlängerung!" (*.ver), game systems and
# training weeks
SAVES = (".gld", ".ver", ".syt", ".woc")


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
    """The only entry of src (__MACOSX aside) if it is a folder the game folder has not, else src."""
    entries = [e for e in os.listdir(src) if not e.startswith("__MACOSX")]
    if (
        len(entries) == 1
        and os.path.isdir(os.path.join(src, entries[0]))
        and not os.path.isdir(os.path.join(game, match(game, entries[0])))
    ):
        return os.path.join(src, entries[0])
    return src


def merge(src, dst, overwrite, counts, only=None):
    """Copies src into dst recursively, names matched without regard to case; existing files are kept unless
    overwrite. With only (lower-case extensions), other files are left out, and so are folders without
    such files. Counts the added, replaced and kept files in counts."""
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        d = os.path.join(dst, match(dst, name))
        if os.path.isdir(s):
            if only and not any(f.lower().endswith(only) for _, _, fs in os.walk(s) for f in fs):
                continue
            os.makedirs(d, exist_ok=True)
            merge(s, d, overwrite, counts, only)
        elif only and not name.lower().endswith(only):
            continue
        elif os.path.exists(d) and not overwrite:
            counts["kept"] += 1
        else:
            counts["replaced" if os.path.exists(d) else "added"] += 1
            shutil.copyfile(s, d)


def copy_in(mode, source, game, overwrite=False, only=None):
    """Merges the zip file (mode "zip") or folder source into the game folder and returns the counts; a zip
    file is extracted first and refused (SystemExit) if it holds an absolute path or ".."."""
    counts = {"added": 0, "replaced": 0, "kept": 0}
    with tempfile.TemporaryDirectory() as tmp:
        if mode == "zip":
            with zipfile.ZipFile(source) as z:
                for info in z.infolist():
                    parts = info.filename.replace("\\", "/").split("/")
                    if info.filename.startswith("/") or ".." in parts:
                        sys.exit(f"{source}: unsafe path in the zip file: {info.filename}")
                z.extractall(tmp)
            src = tmp
        else:
            src = source
        merge(unwrap(src, game), game, overwrite, counts, only)
    return counts


def report(source, counts):
    """The line printed after an import."""
    return (
        f"Imported from {source}: {counts['added']} added, {counts['replaced']} replaced, "
        f"{counts['kept']} kept (already present)"
    )


def main():
    """Merges the source (given, or chosen in a dialog) into the game folder and prints the counts."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--saves", action="store_true", help="copy only save games (%s)" % ", ".join(SAVES))
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
    print(report(source, copy_in(a.mode, source, a.game, a.overwrite, SAVES if a.saves else None)))


if __name__ == "__main__":
    main()
