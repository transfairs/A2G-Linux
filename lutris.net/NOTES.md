# Notes for the lutris.net moderators

These are the installers for Anstoss 2 Gold on the game page `anstoss-2-gold-edition`: the original 1999 CD (`anstoss-2-gold.yml`), the 2007 CD on the DVD "ANSTOSS 2007" (`anstoss-2-gold-2007.yml`) and the GOG release (`anstoss-2-gold-gog.yml`). I reworked all three after the last review:

1. **Lutris YAML only.** The scripts use `extract`, `insert-disc`, `create_prefix`, `merge`, `set_regedit`, `input_menu` and one `wineexec`. There is no `execute`, no `require-binaries`, no `disable_runtime` and no Bash or Python on the host.
2. **Nothing in `$HOME`.** Everything goes to `$GAMEDIR`, and temporary files go to `$CACHE`. The icon, banner and cover now belong on the game page, not in the script.
3. **Tested with the Flatpak of Lutris 0.5.23** (all three releases, with the Gamescope extension).

## The one `wineexec`

The game needs work that Lutris cannot do in YAML: binary patches of the game's executable (bug fixes ported from the Windows patch A2G-Patch, plus optional balancing patches asked for in the input menus), text and quiz changes in its data files, and the conversion of five Indeo 3 videos (Wine has no Indeo decoder). For the 1999 CD, it also runs the original setup silently from a copy of the CD that is mounted as drive D:. If the player asks for it in the input menus, it imports a data set or save games from a zip file or folder picked in Wine's own file dialog; nothing is written outside `$GAMEDIR`.

All of this runs inside the prefix as one Windows program, `src/a2patcher.exe`, so the host needs nothing. It is the Python source `src/a2patcher.py` and the scripts it calls, bundled with PyInstaller. The videos are converted by `src/ffmpeg.exe`, a minimal LGPL build (AVI, Indeo 3 decoder, MS Video 1 encoder) made by `.github/build-ffmpeg.sh` from the official ffmpeg 7.1.1 source tarball, checked by its SHA-256.

Neither file is in the repository. The release workflow (`.github/workflows/release.yml`) builds both on GitHub's runners for each tag and attaches a signed build provenance to them, to `src/gsfix.so`, to `src/gsdisplay.so` and to the archive. Anyone can check that a file was built by that workflow from this repository:

```
gh attestation verify A2G-Linux.tar.gz --repo transfairs/A2G-Linux
```

The scripts download `releases/latest/download/A2G-Linux.tar.gz`, so a new release reaches the scripts without a new submission. Each release runs the full test suite first (`.github/workflows/tests.yml`), and the tests check that the scripts, the patcher and the documentation agree.

## Launch options

The game has two `launch_configs`, both through the same `a2start.exe` in the 640×480 Wine desktop: the game's editor (`Editor.exe`), and for the 1999 CD "ANSTOSS 2: Verlängerung!" (`verl.exe`, the earlier release of the game, which continues its save games).

## Runner and system options

- **No `version`, so Lutris' default GE-Proton (through umu).** Wine Staging (`wine-staging-x86_64`) is no option: under Wine 11.19 the mouse stops reaching the game after the loading screen of a new game, also without Gamescope.
- **Gamescope** scales the 640×480 game up. Lutris leaves it out where it is not installed, and the game then runs in a 640×480 window.
- **`LD_PRELOAD` of `gsfix.so`** (source `src/gsfix.c`) only takes effect in the Gamescope process and removes itself from `LD_PRELOAD` there, so Wine never loads it. It keeps clicks on the window frame away from the game (otherwise the mouse stops working after the window is moved), sets the window title and app ID, and passes the desktop's keyboard layout to Gamescope's Xwayland (otherwise the game gets US English).
- **`gsdisplay.so`** (source `src/gsdisplay.c`, a constructor of four lines) is what `gsfix.so` puts into `LD_PRELOAD` for the game instead. In the Flatpak, umu runs Proton in the Steam Runtime, which pressure-vessel starts in a Flatpak sub-sandbox, and Flatpak sets `DISPLAY` there to the desktop's: a black Gamescope window with the game beside it (flathub/net.lutris.Lutris#514). `gsdisplay.so` copies `STEAM_GAME_DISPLAY_0`, which Gamescope sets to its own X server, back to `DISPLAY`. Since umu empties `LD_PRELOAD` when `XDG_CURRENT_DESKTOP` is `gamescope`, `gsfix.so` gives the game the desktop's value of it back.
- **Registry:** 96 DPI, window colours and the title bar font, DirectDraw through GDI, `UseTakeFocus`, the title bar height of Windows 98 (the game sizes its windows for it), and the codec name `vidc.cram` for MS Video 1 (the game looks for that name before it plays the video of the cup draw).

The full background is in the README, section "Installer scripts for lutris.net".
