# Anstoss 2 Gold on Linux (Lutris)

Runs the German football manager *Anstoss 2 Gold* on Linux with Lutris, Proton and Gamescope, looking and behaving as it does on Windows. Supported are the original 1999 CD release, the 2007 CD release on the DVD "ANSTOSS 2007" (see [2007 CD](#2007-cd-dvd-anstoss-2007)) and the GOG release (see [GOG version](#gog-version)).

This repository contains no files from the game, from Microsoft or other third parties. The Lutris images are cut out of the box art on your CD during the installation; for the fonts, see [Fonts](#fonts).

## Requirements

- Lutris as a regular distribution package, not the Flatpak
- GE-Proton11-12 (see below)
- `ffmpeg`, `gamescope`, `imagemagick`, `python3`, `zenity`, `glib-compile-schemas` and `gcc` from your package manager, plus the Wayland headers for building `gsfix.so` (Debian/Ubuntu `libwayland-dev`, Fedora `wayland-devel`; on Arch they come with `wayland`)
- optional: the Microsoft core fonts package of your distribution (e.g. `ttf-mscorefonts-installer`) for the original Impact in headings (see [Fonts](#fonts))
- the original CD or the DVD "ANSTOSS 2007" (inserted) or an ISO image of it (mount it by double-clicking in the file manager or with `udisksctl loop-setup -f anstoss2.iso`), or the GOG installer `setup_anstoss_2_gold_der_fuballmanager_1.0_fix2_(german)_(48434).exe`
- for the GOG installer and the 2007 DVD: `innoextract` (Lutris brings its own under `~/.local/share/lutris/runtime/`; otherwise from your package manager)

## Installation

1. Copy this folder to your Linux machine, e.g. to `~/a2g-linux`.
2. In a terminal:
   ```bash
   cd ~/a2g-linux
   chmod +x install.sh
   ./install.sh --cd /run/media/$USER/<CD label>
   ```
3. The script copies the CD to `~/Games/anstoss2-cd`, converts the 5 Indeo videos (intro, outro, European Championship, World Cup, final), puts banner, cover (cut out of the box art on the CD) and icon into Lutris and opens the Lutris installer.
4. Confirm the install folder in Lutris. The original setup then runs without dialogs (about two minutes) and installs the game to `C:\Spiele\Anstoss 2 Gold`.
5. Lutris then asks four optional questions: whether to import a data set and save games (each from a zip file or a folder), whether to lift the goal limits and, last, whether to install A2G-Trainer.
6. Unmount the CD after setup. From then on the game uses the copy as drive D:.

Apart from the optional A2G-Trainer and, for the GOG version, GOG's images of the game, nothing is downloaded during the installation. For the trainer, the installer offers "No", "download the latest release from GitHub" or "from a local file" (the release zip `A2G-Trainer-Latest.zip` or `A2G-Trainer.exe`, e.g. for an installation without internet). If the download fails, the game is installed without the trainer. The game runs with GE-Proton11-12, which must be installed in `~/.local/share/Steam/compatibilitytools.d/` (folder `GE-Proton11-12` or `GE-Proton11-12-x86_64`). Lutris drops the `-x86_64` from GE-Proton names and would then try to download the version, so `install.sh` links the folder as `~/.local/share/lutris/runners/wine/GE-Proton11-12`. Without a fixed version, Lutris would let umu fetch every new GE-Proton release.

## GOG version

```bash
./install.sh --gog ~/Downloads/setup_anstoss_2_gold_der_fuballmanager_1.0_fix2_\(german\)_\(48434\).exe
```

GOG sells the 2007 CD release by Kalypso, not the 1999 one: `run.exe` is the game of that release (built anew from the same source and taken out of its PECRYPT32 copy protection), and `RESDLL.dll`, `Editor.exe` and the data in `DATA.VER` differ from the 1999 CD as well. The 1999 `anstoss2.exe` is not in the GOG installer, so it cannot be made into the CD version. What the installer does instead:

- **Own Lutris entry:** slug `anstoss-2-gold-edition` ("Anstoss 2 Gold (GOG)"). Lutris treats it as a game of its GOG service and installs it to `~/Games/gog/anstoss-2-gold-edition`, next to the CD version. The application menu entries are "Anstoss 2 Editor (GOG)" and "A2G-Trainer (GOG)" (`anstoss-2-gold-edition-editor.desktop`, `-trainer.desktop`); A2G-Trainer supports `run.exe`.
- **Only the game:** the GOG installer is not run but unpacked with innoextract to `C:\Spiele\Anstoss 2 Gold`. Left out are DirectX, GOG's DirectDraw wrapper `ddraw.dll`, the Windows compatibility database `game.sdb` and the `goggame-*` files. `rest.sav`, which GOG keeps under `__support/save`, goes to the game folder (without it a new game crashes and loading a save game returns to the main menu), `ExSpiel.sav` from `app/` to `DATA.DEF` and `DATA.VER`. The registry gets what the GOG installer writes (`HKLM\Software\Wow6432Node\ASCARON\ANSTOSS 2\1.00`: `InstalledTo`, `InstalledFrom`, `Language`). The game reads everything from its folder, no CD drive is needed.
- **Same setup as the CD version:** fonts, registry settings, Gamescope window (scalable, 640×480 Wine desktop), the 5 Indeo videos converted in `VIDEOS`, `a2start.exe` and the patches in `run.exe` (`--sound`, optionally `--goals`; backup `run.exe.vor-a2g-patch`).
- **CD checks of the 2007 release (`--disc-check`, always):** the 2007 CD release checks its CD in 11 places of the game; without the CD it sabotages the game (from the second season all teams are called "Raubkopie", players drop to strength 1). Each check calls one signature routine and subtracts the expected value, zero or more means "original CD". GOG's "1.0 fix2" replaced these subtractions with NOPs, which leaves the raw signature and makes every check fail. `src/a2patch.py --disc-check` puts `xor reg,reg` there, the result of a passed check. The 1999 CD version has none of these checks. Applied only if exactly these 11 places are found.
- **Integrity checks of the 2007 release (automatic):** besides the 11 CD checks, the 2007 program checks itself: five places compute a CRC32 of `run.exe` on disk (offset 0x80 to the end) and compare it with the value at offset 0x7c, five others a CRC32 of a stretch of their own code against a value stored in front of it. GOG's unpacked `run.exe` fails all ten. GOG disabled four of the code checks; the others are active in GOG's release: a function then skips its work (0x5cc9d0, 0x63f320) or doubles negative values (0x418ca0, via `[0xcb0b30]`). Whenever `src/a2patch.py` writes the GOG `run.exe`, it stores the correct values, so all ten checks pass as with the untouched original (also after a later `--goals`). The memory patches of `a2start.exe` lie outside the checked code.
- **What else was checked:** all places that use the hidden API calls of the protection were followed (GetDriveTypeA, GetModuleFileNameA, LoadLibraryA, timeGetTime). Besides the checks above there are two sums of directory sizes (0x41b560, 0x5f488c) whose results are never used, and `timeGetTime` only fills junk buffers (no timing checks). The penalties found (players set to strength 1, overwritten manager data, random events, skipped work, doubled negative values) all sit on the failure paths of these checks.
- **Patch 1.01, program (`--v101`, always):** `run.exe` is built from the 1.00 source. The changes of 1.01 were found by comparing it with the 1.01 program and with the 1999 CD release, which contains them; differences that only concern the copy protection, GOG's own changes or the compiler were left out. They are written anew in `src/a2v101.S` (GNU assembler, own code). `src/a2patch.py --v101` assembles it for a new section `.a2v101` at the end of `run.exe` (in place of GOG's signature, which no longer matches after any patch) and makes 12 places jump there, each only if its bytes match exactly (a 13th place is changed in place, see the last item):
  - player lists with a count per position (`0x412dd0`): players are stored one after the other with their real count instead of at their list index
  - message 0xc7 only if a value of the object is above 47 (`0x415da0`, two places)
  - message 0xa41 is gone (`0x501dcf`)
  - a block of counters is cleared, and a counter grows by one instead of by another value (`0x557e30`)
  - five counters of an entry stay below 1,000,000, negative amounts are ignored (`0x568ca0`)
  - a dialog returns its result into the team data (`0x5a0b70`)
  - new players get a second position in 20 % of the cases (`0x5a2690`)
  - traits of new goalkeepers as in 1.01 (`0x5a2fc0`)
  - when the human managers are reordered, a data block of 0x160 bytes per manager is reordered with them (`0x5bd540`)
  - the cup draw loads `archives/movelist.dat` from the game folder instead of the CD (`0x468a4e`, as in [A2G-Patch](https://github.com/transfairs/A2G-Patcher)); the file comes with 1.01 (see the next item) and is not on any CD. For GOG both paths point to the game folder, for the 2007 CD the CD path is drive D:.
  The new functions were checked in an x86 emulator against the 1.01 originals with thousands of random inputs (same results); they need GNU binutils (`as`, `ld`, `objcopy`, `nm`, installed with `gcc`).
- **Patch 1.01, data:** 1.01 changes three data files; `src/a2data101.py` makes all of them from the GOG files and own code, without files of the patch. In the event texts (`TEXTE/EreigGold.saq`, the name `run.exe` reads, also written as `EreigGld.saq`, the 1.01 name) two texts end with "." instead of ":" (the file is decrypted, changed and encrypted again; identical to 1.01). In `LAENDER.SAV` (`DATA.DEF` and `DATA.VER`) one value changes from 3 to 4 (identical to 1.01). `ARCHIVES/MoveList.dat` is the animation of a sign flying into a video window (probably the cup draw): per frame a table that maps the screen pixels to a 128x32 picture the game draws at run time. `src/a2movelist.py` holds only the path of the sign (position, size and the four corners per frame) and computes the tables as perspective projections; inside the sign they differ from the file of 1.01 by at most one pixel. All results are checked against their SHA-256; originals are kept as `*.vor-1.01`.
- **Dialogs (`src/a2resdll.py`, always):** all dialogs of the game are templates in `RESDLL.dll`. In GOG's file they lack styles the 1999 file has: the title bar (`WS_CAPTION`, 342 dialogs; the game centers dialogs with a title bar over its window itself, GOG's file uses `DS_CENTER` instead), `DS_MODALFRAME`, the sunken frame (`WS_EX_CLIENTEDGE`) around 68 controls, e.g. the choices that look like buttons ("Frei (Vorsaison voreingestellt)"), `WS_EX_TRANSPARENT` on 16 radio buttons and the character set of the dialog font. The script sets the values of 1999 in place (own table from comparing both files, the file keeps its size), checked against SHA-256 before and after; the original is kept as `RESDLL.dll.vor-dialoge`. Not changed are texts and pictures the 2007 release changed on purpose (version "1.0" in the info dialog, "Championsleague", "Managerkarriere", four pictures).
- **Memory patches:** `run.exe` contains the same code as the 1999 `anstoss2.exe` at other addresses. `a2start.exe` knows both (table `versions` in `src/a2start.c`; GOG's and the 2007 CD's `run.exe` only differ in the addresses of their import slots) and writes the detected version to `a2start.log`.
- **Banner and cover:** made from the images GOG shows for the game (box art and logo, from GOG's public product API `api.gog.com/v2/games/1808817480`); without a connection, Lutris shows its default images. The icon is `Anstoss2.ico` from the GOG installer.
- Not set up: "ANSTOSS 2: Verlängerung!" (`vrun.exe`), as on the CD version (`verl.exe`).

## 2007 CD (DVD "ANSTOSS 2007")

```bash
./install.sh --cd "/run/media/$USER/ANSTOSS 2007"
```

The DVD "ANSTOSS 2007" by Kalypso holds several games; Anstoss 2 Gold is the Inno Setup installer `ANSTOSS_2_GOLD/Setup.exe`. `install.sh --cd` recognizes it by that file. Its `run.exe` is the program GOG sells (see [GOG version](#gog-version)), but still inside its PECRYPT32 copy protection shell, and its `RESDLL.dll` has the dialogs of 1999. What the installer does:

- **Own Lutris entry:** slug `anstoss-2-gold-2007` ("Anstoss 2 Gold (2007)"), folder `~/Games/anstoss-2-gold-2007`, next to the other versions. Menu entries "Anstoss 2 Editor (2007)" and "A2G-Trainer (2007)".
- **Files as Kalypso's setup installs them:** the setup is unpacked with innoextract (not run) to `C:\Spiele\Anstoss 2 Gold`, including the folder `CD` with the CD's files (`ARCHIVES`, `SOUNDS`, `VIDEOS`). Registry as the 1999 setup writes it (`InstalledTo`, `InstalledFrom` = `D:\`, `Language`). The DVD is only needed during the installation.
- **Drive D:** Kalypso's launcher `anstoss2.exe` injects `compatibility.dll`, which fakes a CD drive for the folder `CD`. Here, Wine mounts that folder as CD-ROM drive D: instead, as for the 1999 CD; the launcher stays unused and the game starts through `a2start.exe` as `run.exe`. The 5 Indeo videos in `CD/VIDEOS` are converted.
- **Unpacking `run.exe` (`src/a2unpack.py`):** the loader of the shell would unpack the program in memory. The script does the same on disk, with own code and without running anything: the three sections are LZW streams (9 to 12 bit codes; `.text` and `.data` with 0x78 added to each byte), the program's own import table is intact inside them. The result has the original entry point and a normal import directory; code and data are the same bytes the loader leaves in memory (checked in an x86 emulator). Input and result are checked against their SHA-256; the original is kept as `run.exe.vor-entpacken`.
- **CD and integrity checks:** the 11 CD checks still have their subtraction (GOG NOPed it); a copy of the CD gives another signature, so they would fail as well. `src/a2patch.py --disc-check` puts in the passed result as for GOG. The other places of the copy protection (drive type, CD path) work with drive D: as written. The integrity values are stored as for GOG.
- **Same as GOG:** the patches in `run.exe` (`--sound`, `--v101`, optionally `--goals`), the data of 1.01 (`src/a2data101.py`; the data files are identical to GOG's), banner and cover cut out of the box art in `CD/AUTORUN.EXE`, the icon `anstoss2.ico`. Not needed: `src/a2resdll.py`.
- Tested: intro from drive D:, loading a save game and playing into the next season (team names and player strengths intact, cup draw).

## What gets set up

- **Lutris media:** banner and cover go to `~/.local/share/lutris/banners/` and `coverart/`, cut out of the box art that `AUTORUN.EXE` on the CD shows (`src/a2assets.py`). The icon is `ANSTOSS2.ICO` from the CD, scaled to 128×128 (`~/.local/share/icons/hicolor/128x128/apps/lutris_anstoss-2-gold.png`).
- **Data set (optional):** a zip file or folder whose contents are copied into the game folder and replace the game's files. File names are matched without regard to case, so `DATA.DEF` replaces `data.def` instead of ending up next to it. If everything lies in one folder the game doesn't have, its contents are copied (`src/a2import.py`).
- **Save games (optional):** the same, but save games already in the game folder are kept.
- **Patches in `anstoss2.exe`:** `src/a2patch.py` ports two patches from [A2G-Patch](https://github.com/transfairs/A2G-Patcher) (GPLv3) and changes the exe on disk. It writes the same backup `anstoss2.exe.vor-a2g-patch` first, so A2G-Patch recognizes the changes and can take them back; restoring the backup undoes them as well. Each patch is applied only if its places match exactly.
  - **Sound device (always):** The game keeps the last sound device it finds instead of the default one, so with several outputs (speakers, Bluetooth headphones, HDMI) the sound may go to the wrong one. The patch makes it use the default device of the system (`--sound`).
  - **Goal limits (optional):** Unpatched, the match engine lets a team score only while it has fewer than 6 goals up to minute 45 and fewer than 10 after, and halves its chances from 7 goals on. The patch raises the limit to 15 and drops the halving (`--goals`).
  - Both can also be applied later, e.g. `python3 src/a2patch.py --goals ~/Games/anstoss-2-gold/drive_c/Spiele/Anstoss\ 2\ Gold/anstoss2.exe`.
- **A2G-Trainer (optional) and editor:** [A2G-Trainer](https://github.com/transfairs/A2G-Trainer) goes to `C:\Spiele\A2G-Trainer`. The application menu gets the entries "Anstoss 2 Editor" and, with the trainer, "A2G-Trainer" (`~/.local/share/applications/anstoss-2-gold-trainer.desktop`, `-editor.desktop`, icons taken from the exes). Both call `a2run.sh` in the prefix folder (source `src/a2run.sh`), which starts them with the same Proton and settings as Lutris uses for the game. They can be started before, after or while the game runs: with `PROTON_VERB=runinprefix`, they join the game's wineserver instead of waiting for it to end, so the trainer reads the game's memory. The editor needs 16 bit like the game ("läuft nur in HICOLOR!") and runs like it in a 640×480 Wine desktop via `a2start.exe`, in its own Gamescope window. Uninstalling the game in Lutris leaves the two `.desktop` files and their icons behind. At the end, `a2extras.py` rebuilds the icon cache in `~/.local/share/icons/hicolor` (`gtk-update-icon-cache`): Lutris writes that cache when it starts, and GNOME would not find icons added after it (generic icon in the dock and menu).
- **Fonts:** 96 DPI and no font smoothing. MS Sans Serif (bitmap, game and dialogs) and Small Fonts (bitmap, editor) are Wine's own. Arial, Tahoma and Microsoft Sans Serif come from Proton. Impact (headings) only if it is installed on the system (see [Fonts](#fonts)).
- **Animations:** DirectDraw through Wine's GDI renderer, videos from the converted CD copy.
- **Silent setup:** The CD contains InstallShield's response file `SETUP.ISS`. `install.sh` writes a copy with the target folder `C:\Spiele\Anstoss 2 Gold` to the CD copy (`a2setup.iss`), and Lutris runs `SETUP.EXE -s` with it, so the setup shows no dialogs; its result goes to `a2setup.log` next to it. At the end, the setup opens its Start menu group in a Wine Explorer window, which would keep the installation waiting until closed by hand. The setup is therefore started through `src/a2setup.exe` (source `src/a2setup.c`), which waits for the setup and the processes it starts and closes such folder windows.
- **16 bit:** Lutris starts `explorer.exe /desktop=A2,640x480 "C:/Spiele/Anstoss 2 Gold/a2start.exe" anstoss2.exe /f`. The small launcher (source in `src/a2start.c`) switches to 640×480×16 first; otherwise the game refuses to start ("Windows muß sich im Hicolormodus befinden"). Wine emulates this mode internally and passes 32-bit images to Gamescope.
- **Indeo check:** At startup the game looks for a video codec named "IR32" (Indeo 3.2), which Wine does not have. `a2start.exe` therefore changes the search term in the game's memory to "MS-CRAM", Wine's built-in MS Video 1 decoder, which matches the converted videos. `anstoss2.exe` itself stays unchanged.
- **Font width:** The game requests the bitmap font MS Sans Serif with a fixed character width. Wine then spreads the letters apart (headings, tables and statistics get cut off). `a2start.exe` sets this width to "natural width" in memory, for the menu fonts and for the 10 px font of the list and table windows.
- **Mascot in dialogs:** The animations are larger than their control. Windows shows the overhang (window class with `CS_PARENTDC`), Wine clips it. `a2start.exe` enlarges the control to the image size when it is created.
- **Club names (large font, e.g. the match announcement):** The game requests MS Sans Serif at 20 or 24 px with a given width. Windows then doubles the characters horizontally, Wine only widens the gaps. `src/mkwide.py` builds the font "A2 Sans Serif Wide" with double-width characters from Wine's MS Sans Serif (`a2wide20.fnt` in `C:\Spiele\Anstoss 2 Gold`). `a2start.exe` makes the game load it at startup and use it for the large font sizes. Wine's MS Sans Serif has no 24 px size, so that size stays as Wine draws it (`a2start.exe` would also use an `a2wide24.fnt` built from Microsoft's `sserife.fon`).
- **Crests and flags:** The game passes a negative destination size to `DrawDibDraw`. Windows then uses the image size, Wine draws mirrored and stretched (a huge upside-down flag in the top left). `a2start.exe` sets negative values to -1 before the call.
- **Videos with an 8-bit palette** (e.g. "Torschütze des Monats", goal of the month): The game requests the frames with an empty palette. Windows still uses the video's palette, Wine takes the empty one and the video stays black. `a2start.exe` makes the game request the video's own format instead (same format, correct palette).
- **Cup draw (club names on the sign in the video):** The game draws the names with GDI into a bitmap compatible with the screen and reads it with `GetBitmapBits`, expecting 16 bit per pixel. Under Wine this bitmap has 32 bit per pixel even in the 16-bit mode, so the names came out twice as wide, half as high and dotted. `a2start.exe` makes the game fetch the picture with `GetDIBits` as a 16-bit image (5-5-5, since Wine ignores other color masks there; white text came out black) and converts it to the 5-6-5 format of the game's surface (`MoveList.dat`, which maps this picture onto the sign, is not involved).
- **Preseason calculation:** The constructor of the calculation screen ("ANSTOSS2 - Kalkulation") sets the selection of "Ermittlung der Zahlen" to 0 but leaves that of "Darstellung" as it comes from the heap. On Windows that memory is 0 ("Reine Kalkulation"); under Wine it can hold any value, depending on what was freed before (e.g. a career without Italy as a bonus country). With a large value, drawing the list reads past its entries, the access violation inside `WM_INITDIALOG` is swallowed by the window callback, and the screen stays hidden and half set up while the game waits for it. `a2start.exe` makes the constructor clear both selections (CD `0x4a513f`, GOG `0x4a733f`, outside the code `run.exe` checks).
- **Picture buttons (e.g. "A/B" and "i" in the team lineup before a match):** The constructor of the game's picture button class leaves the image size fields as they come from the heap; they are only filled when a picture is loaded. The lineup moves "A/B" and "i" to their place before loading their pictures and then aligns them to the bottom right corner of that window. On Windows that memory is 0 and the buttons land where they belong. Under Wine it can hold old pixel data: the window gets a huge size, its corner ends up at 32767, and the button is missing until the lineup is opened again. `a2start.exe` makes the constructor clear these fields (CD `0x5bc43a`, GOG `0x5bf16a`, outside the code `run.exe` checks).
- All changes made by `a2start.exe` happen in memory only; the game files stay unchanged. They are applied only if the bytes match the 1999 version or the GOG version exactly. The result is written to `C:\Spiele\Anstoss 2 Gold\a2start.log`.
- **Window:** Gamescope runs as a regular window (initially 1280×960) that can be resized freely. The image is fitted with its aspect ratio preserved (filter `pixel`: sharp even at non-integer factors).
- **Virtual desktop:** The game runs in a 640×480 Wine virtual desktop (via `explorer.exe /desktop=…`; Proton ignores the registry setting for this). Gamescope scales only this desktop, so dialogs (e.g. "Spiel beenden?") appear inside it at their original size.
- **Mouse after resizing:** Gamescope also forwards clicks on the window frame and title bar to the game. When you drag the frame, GNOME takes over the mouse and the button release never arrives, so for the game the left button stays pressed and every further click is lost. `gsfix.so` in the prefix folder (source in `src/gsfix.c`) is loaded into Gamescope only, via `LD_PRELOAD`, and passes mouse buttons through only while the pointer is over the game image.
- **Title bars of game windows:** Under Gamescope, Proton removes the title bar and frame from all windows (meant for the Steam Deck, detected by the window manager name "steamcompmgr"). With `GSFIX_WMNAME=gamescope`, `gsfix.so` makes Gamescope register under a different name, and Wine draws title bars as on Windows. The main window gets its "ANSTOSS 2 …" title bar back too; the game is designed for it (play area 636×457), and the black strip at the bottom disappears.
- **Title bar colors:** modeled on the Windows XP theme Royale Noir: white text on slate blue (active), light gray text on gray blue (inactive). The original has a vertical glossy gradient; Wine only draws horizontal ones, so the bar uses an almost flat tone close to the original's average. Gloss, rounded corners and the red close button cannot be reproduced. The title font is bold Tahoma (`CaptionFont` under `HKCU\Control Panel\Desktop\WindowMetrics`). Proton's default would be black on light blue. The background of the virtual desktop uses the active title bar color. Configurable under `HKCU\Control Panel\Colors` (`ActiveTitle`, `GradientActiveTitle`, `TitleText`, `InactiveTitle`, `GradientInactiveTitle`, `InactiveTitleText`, `Background`, each as "R G B").
- **Window title and icon:** `GSFIX_TITLE` sets the title of the Gamescope window ("Anstoss 2 Gold"). `GSFIX_APPID` links the window to its menu entry in GNOME (name and icon in the dock); otherwise Gamescope reports itself as "gamescope", and GNOME shows a generic icon once the window appears. For the game the value is the pattern `net.lutris.<slug>-[0-9]*`, since the Lutris game ID in the name of the `.desktop` file is not known at install time; `gsfix.so` replaces it with the first matching file in the applications folders. Without a matching file (no menu entry created in Lutris) it has no effect. The editor uses `<slug>-editor`. Gamescope sometimes commits its window without content; GNOME then replaces the window by a new one without title and app ID, so `gsfix.so` sends both again after each such commit.
- **GNOME 50:** Gamescope would crash at startup (missing key "antialiasing"). The prefix folder therefore contains an adjusted schema copy under `gschemas/`, which `GSETTINGS_SCHEMA_DIR` points to.

## Fonts

The game uses the Windows fonts MS Sans Serif, Small Fonts and Impact, which may not be passed on with this installer. The installer adds none of them:

- **MS Sans Serif and Small Fonts:** Wine's own versions are used. They lack the 24, 29 and 37 px sizes, and some characters have other widths, so texts are laid out slightly differently than on Windows.
- **Impact** (headings): Proton also sees the fonts installed on your system, so the game uses Impact if it is installed there (e.g. by `ttf-mscorefonts-installer`). Otherwise Wine draws the headings with a replacement font (Arial, which Proton provides as Liberation Sans).

## Changing window mode and scaling

Right-click the game → Configure → System options (enable "Advanced" at the top):

- **Window mode:** "Windowed" (default), "Fullscreen" or "Borderless"
- **Gamescope output resolution:** initial window size, e.g. `1280x960`; in fullscreen, your monitor resolution
- **Custom Gamescope settings:**
  - `-S fit -F pixel`: fit to window, sharp, pixels stay even (default)
  - `-S fit -F linear`: fit to window, smooth
  - `-S fit -F nearest`: fit to window with hard pixels (uneven at non-integer factors)
  - `-S integer -F nearest`: sharp pixels, integer scaling only, otherwise with borders

## Troubleshooting

- **Black screen only, game does not start (GNOME 50 / Ubuntu 26.04):** Gamescope crashes at startup (`Settings schema ... does not contain a key named 'antialiasing'`). Under Configure → System options → Environment variables, `GSETTINGS_SCHEMA_DIR` must point to the `gschemas` folder in the prefix (enter the full path). Recreate it with `./install.sh --make-schemas ~/Games/anstoss-2-gold/gschemas`.
- **The game stops reacting after clicking another window:** The registry must contain `UseTakeFocus` = `N` under `HKCU\Software\Wine\X11 Driver` (the installer sets it).
- **Mouse clicks stop arriving after resizing the window or clicking the title bar (keyboard still works):** Under Configure → System options → Environment variables, `LD_PRELOAD` must point to `gsfix.so` in the prefix folder (enter the full path). Rebuild it with `gcc -O2 -Wall -shared -fPIC -o gsfix.so src/gsfix.c -ldl`.
- **Dialogs without a title bar:** `GSFIX_WMNAME` = `gamescope` (or `LD_PRELOAD`) is missing from the environment variables.
- **Animations still black:** The next step would be cnc-ddraw with `fixchilds`.
- **"Bitcount 32 not supported" or "Hicolormodus":** Under Configure → Game options, the executable must be `drive_c/windows/explorer.exe` in the prefix and the arguments `/desktop=A2,640x480 "C:/Spiele/Anstoss 2 Gold/a2start.exe" anstoss2.exe /f` (GOG version and 2007 CD: `run.exe` instead of `anstoss2.exe`).
- **"kein Intel Indeo 3.2-Videodekompressor":** The game was not started through `a2start.exe`, or it is a different program version. `C:\Spiele\Anstoss 2 Gold\a2start.log` shows whether the patch was applied.
- **Undo:** The original videos are kept as `*.indeo3.bak` in `~/Games/anstoss2-cd/VIDEOS`. The prefix can simply be uninstalled in Lutris.

## Installer scripts for lutris.net

`lutris.net/anstoss-2-gold.yml` (CD), `lutris.net/anstoss-2-gold-2007.yml` (2007 CD on the DVD "ANSTOSS 2007") and `lutris.net/anstoss-2-gold-gog.yml` (GOG) are drafts of installer scripts for the Lutris website. They do what `install.sh` and `anstoss2.yml.in` do, without anything run beforehand: they download a release of this repository, copy the CD (`insert-disc`), unpack `ANSTOSS_2_GOLD/Setup.exe` from the DVD (`insert-disc`, read in place) or unpack the GOG installer, and convert the videos and build the wide font and `gsfix.so` during the installation. Differences from `install.sh`:

- **Proton:** no Wine version in the script, so Lutris uses its default "GE-Proton (Latest)" (umu) instead of the fixed GE-Proton11-12, since a script cannot rely on the link `install.sh` makes. Writing `version: ge-proton` does not work: Lutris 0.5.22 turns it into `ge-proton-x86_64` and aborts with "Failed to retrieve wine (ge-proton-x86_64) information". `a2run.sh` then uses the same.
- **CD copy:** in the game folder (`$GAMEDIR/cd`) instead of `~/Games/anstoss2-cd`.
- **Menu entries of editor and trainer:** own names (`anstoss-2-cd-*.desktop`, `anstoss-2-2007-*`, `anstoss-2-gog-*`), so an installation from lutris.net never replaces or removes the entries of an `install.sh` installation.
- **Banner, cover and icon:** made during the installation like `install.sh` does (CD and 2007 CD: from the box art of `AUTORUN.EXE` and `anstoss2.ico`; GOG: from GOG's images and `Anstoss2.ico`), named after the game slug `anstoss-2`, since lutris.net has only a cover for that page.
- **Lutris as a Flatpak** is not supported: several steps use programs of the system (`disable_runtime`). `require-binaries` stops the installation early if one is missing.

Before submitting:

1. Push a release tag (e.g. `git tag v0.1.0 && git push origin v0.1.0`). The workflow `.github/workflows/release.yml` then publishes a release with the repository attached as `A2G-Linux.tar.gz`, and the three files download it from `https://github.com/transfairs/A2G-Linux/releases/latest/download/A2G-Linux.tar.gz`, i.e. always from the newest release.
2. Test each with `lutris -i lutris.net/<file>.yml`.
3. Submit all three scripts on the game page `anstoss-2` (there is no `anstoss-2-gold`). For GOG this matters: lutris.net links the GOG product 1808817480 to that page, and only then does Lutris offer the script for the game in its GOG library and download the GOG installer itself (with `gogid` in the script; Lutris must run in German, since GOG only has a German installer).
4. On the game page, choose "Add installer", runner Wine, version "Original-CD", "CD 2007" or "GOG 1.0 fix2", and paste everything below `script:` (one indentation level less) into the script field. Under notes: needs Lutris as a distribution package, the listed programs (including GNU binutils for GOG and the 2007 CD); link to this README.

## Building the helper programs

`src/a2start.exe` and `src/a2setup.exe` are included prebuilt, so `install.sh` needs no cross compiler. To build them yourself from `src/a2start.c` and `src/a2setup.c`, install MinGW-w64 (Debian/Ubuntu `gcc-mingw-w64-x86-64`, Fedora `mingw64-gcc`, Arch `mingw-w64-gcc`) and run in the repository folder:

```bash
x86_64-w64-mingw32-gcc -O2 -Wall -mwindows -o src/a2start.exe src/a2start.c -lgdi32
x86_64-w64-mingw32-gcc -O2 -Wall -o src/a2setup.exe src/a2setup.c
```

`a2start.exe` is a Windows program without a console (`-mwindows`), `a2setup.exe` a console program. `install.sh` builds `src/gsfix.so` itself with the system `gcc` if it is missing.

## Development and tests

Tests and checks run with [tox](https://tox.wiki), all tools from a virtual environment in the repository folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/tox              # everything
.venv/bin/tox -e lint      # one environment; -p auto runs them in parallel
```

| Environment | What it does |
|---|---|
| `py312`, `py313`, `py314` | pytest (`tests/`); Python versions that are not installed are skipped |
| `lint` | isort, black, flake8 for `src/` and `tests/`, shellcheck for `install.sh` and `src/a2run.sh` |
| `bandit` | security checks of `src/` (settings in `pyproject.toml`) |
| `coverage` | the tests with branch coverage, HTML report in `logs/coverage/` |
| `build` | builds `a2start.exe`, `a2setup.exe` and `gsfix.so` with warnings as errors into a scratch folder (needs MinGW-w64 and `gcc`) |

The tests use synthetic data only, no files of the game. The test of the 1.01 changes assembles `src/a2v101.S` and is skipped without GNU binutils. GitHub Actions runs `tox` on every push (`.github/workflows/tests.yml`).

Python code is formatted with black and isort (120 characters, `pyproject.toml`). Hand-aligned tables (addresses, dialog IDs, hashes) stay as written between `# fmt: off` and `# fmt: on`. Commits that only reformat are listed in `.git-blame-ignore-revs`; to have `git blame` skip them locally as GitHub does:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## License

GNU General Public License version 3 (GPL-3.0-only), see [LICENSE](LICENSE). `src/a2patch.py` ports patches from [A2G-Patch](https://github.com/transfairs/A2G-Patcher), which is under the same license. *Anstoss 2 Gold* itself, its CD, box art and the Windows fonts are not part of this repository and belong to their respective owners.
