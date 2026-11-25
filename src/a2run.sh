#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Starts A2G-Trainer or the Anstoss 2 editor in the game's Wine prefix, with the same Proton
# and settings as Lutris uses for the game. Works while the game runs (same wineserver, so the
# trainer can read the game's memory) and on its own.
#
#   a2run.sh trainer|editor
#
# Installed into the prefix folder by the Lutris installer; the .desktop files call it.
set -euo pipefail

SLUG=anstoss-2-gold  # set by a2extras.py (slug of the menu entries, see there)
FLATPAK=0  # set by a2extras.py: 1 if the game was installed with Lutris' Flatpak
GAMEDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Lutris' Flatpak runs the game inside the Flatpak, so the editor and the trainer run there as well:
# with its Proton, umu and Gamescope, and with the game's wineserver (Flatpak shares /tmp, where the
# wineserver's socket lies, between the instances of one app)
if [[ "$FLATPAK" == 1 && ! -f /.flatpak-info ]]; then
  exec flatpak run --command=bash net.lutris.Lutris "$GAMEDIR/a2run.sh" "$@"
fi
LUTRIS="${XDG_DATA_HOME:-$HOME/.local/share}/lutris"
GAME="$GAMEDIR/drive_c/Spiele/Anstoss 2 Gold"
TRAINER="$GAMEDIR/drive_c/Spiele/A2G-Trainer"

export WINEPREFIX="$GAMEDIR" WINEARCH=win64 GAMEID=umu-default
PROTONPATH="$LUTRIS/runners/wine/GE-Proton11-12"  # linked by install.sh
# Installed with the lutris.net script: the newest GE-Proton, as umu fetches it for the game
[[ -f "$PROTONPATH/proton" ]] || PROTONPATH=GE-Proton
export PROTONPATH
# As Lutris sets them for the game. esync/fsync must match the game's, since both share one wineserver.
export WINEDEBUG=-all WINEESYNC=0 WINEFSYNC=0 PROTON_NO_ESYNC=1 PROTON_NO_FSYNC=1
export PROTON_USE_WINED3D=1 PROTON_DXVK_D3D8=0 WINEDLLOVERRIDES="ddraw=b;dsound=b"
# Without this, Proton would wait until the running game has ended.
export PROTON_VERB=runinprefix
UMU="$LUTRIS/runtime/umu/umu-run"

case "${1:-}" in
  trainer)
    # Native Wayland window: through Xwayland, Wine misses moves made by GNOME and then places
    # clicks at the old window position. Only this process is affected; the game stays on X11.
    export PROTON_ENABLE_WAYLAND=1
    [[ -f "$TRAINER/A2G-Trainer.exe" ]] || { echo "A2G-Trainer is not installed ($TRAINER)" >&2; exit 1; }
    cd "$TRAINER"
    exec "$UMU" "$TRAINER/A2G-Trainer.exe"
    ;;
  editor)
    # Like the game: 640x480 Wine desktop, 16 bit via a2start.exe ("läuft nur in HICOLOR!"),
    # scaled by Gamescope; gsfix.so (Gamescope only) as for the game, see README.
    # In the Flatpak: Gamescope of its extension (gsfix.so knows it), the schemas of its runtime,
    # gsdisplay.so next to gsfix.so; without the extension the editor runs in a 640x480 window.
    cd "$GAME"
    export GSFIX_TITLE="Anstoss 2 Editor" GSFIX_APPID="$SLUG-editor" GSFIX_WMNAME=gamescope
    [[ -f /.flatpak-info ]] || export GSETTINGS_SCHEMA_DIR="$GAMEDIR/gschemas"
    editor=("$UMU" "$GAMEDIR/drive_c/windows/explorer.exe" "/desktop=A2Editor,640x480"
            "C:/Spiele/Anstoss 2 Gold/a2start.exe" Editor.exe)
    if [[ -f /.flatpak-info ]] && ! command -v gamescope >/dev/null; then exec "${editor[@]}"; fi
    exec env LD_PRELOAD="$GAMEDIR/gsfix.so" gamescope -w 640 -h 480 -W 1280 -H 960 -S fit -F pixel -- "${editor[@]}"
    ;;
  *)
    echo "Usage: $0 trainer|editor" >&2
    exit 2
    ;;
esac
