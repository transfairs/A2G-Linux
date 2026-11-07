#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Full installation of Anstoss 2 Gold via Lutris, from the original 1999 CD, the 2007 CD (DVD
# "ANSTOSS 2007") or the GOG installer.
#
#   ./install.sh --cd <mount point of the CD, DVD or ISO> [--cd-copy ~/Games/anstoss2-cd]
#   ./install.sh --gog <setup_anstoss_2_gold_...exe>
#
# 1. CD: copies the CD to --cd-copy and converts the Indeo 3.2 videos to Microsoft Video 1.
#    2007 CD (recognized by ANSTOSS_2_GOLD/Setup.exe): nothing is copied beforehand.
# 2. Generates a Lutris install script and runs it. Lutris creates the prefix, sets up
#    registry settings and Gamescope (640x480, scaled), then
#    CD:  mounts the copy as CD drive D: and runs the original setup silently (target folder
#         C:\Spiele\Anstoss 2 Gold, response file a2setup.iss on the CD copy, src/a2setup.c);
#    GOG: unpacks the installer with innoextract to C:\Spiele\Anstoss 2 Gold and converts the videos
#         there and applies patch 1.01 (program: src/a2v101.S; data: src/a2data101.py, src/a2movelist.py) and the
#         dialog styles of 1999 (src/a2resdll.py). The GOG version
#         gets its own Lutris entry (slug anstoss-2-gold-gog, folder ~/Games/gog/anstoss-2-gold-gog),
#         so both can be installed side by side.
#    2007 CD: unpacks ANSTOSS_2_GOLD/Setup.exe with innoextract to C:\Spiele\Anstoss 2 Gold, takes run.exe
#         out of its copy protection shell (src/a2unpack.py), mounts the folder CD there as drive D:,
#         converts the videos and applies patch 1.01 as for GOG. Own Lutris entry (slug
#         anstoss-2-gold-2007, folder ~/Games/anstoss-2-gold-2007).
# 3. Builds the wide font from Wine's MS Sans Serif and puts banner, cover (from the box art on
#    the CD) and the game's icon into Lutris (src/a2assets.py). For GOG, banner and cover come from GOG's images of the game.
#    Lutris then optionally imports a data set and save games and lifts the goal limits.
#
# Requires: lutris (native, not Flatpak), ffmpeg, ffprobe, gamescope, imagemagick, python3, zenity.
# Without src/gsfix.so (in the release archive, not in the git repository): gcc and the Wayland headers.
# GOG and 2007 CD: innoextract (Lutris brings its own in ~/.local/share/lutris/runtime). Missing ones
# are installed with apt, dnf, pacman or zypper (with sudo); a missing GE-Proton11-12 is downloaded.
set -euo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTON="GE-Proton11-12"
CD=""; GOG=""; DVD=""; CDCOPY="$HOME/Games/anstoss2-cd"

die() { echo "ERROR: $*" >&2; exit 1; }

convert_videos() {  # $1 = directory, recursive
  # Indeo 3.2: Wine has no decoder, convert to MS Video 1 with 16 bit (RGB555).
  # The other MS Video 1 videos (8 bit with palette) stay unchanged, Wine plays them itself.
  local n=0 f info bak
  while IFS= read -r -d '' f; do
    info="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt -of csv=p=0 "$f" < /dev/null || true)"
    case "$info" in
      indeo3*)          bak="$f.indeo3.bak" ;;
      *) continue ;;
    esac
    echo "Converting: $f ($info)"
    ffmpeg -nostdin -v error -y -i "$f" -map 0 -c:v msvideo1 -pix_fmt rgb555le -c:a copy -f avi "$f.tmp"
    [[ -e "$bak" ]] || mv "$f" "$bak"
    mv "$f.tmp" "$f"
    n=$((n+1))
  done < <(find "$1" -iname '*.avi' -print0)
  echo "$n video(s) converted in $1"
}

make_schemas() {  # $1 = target folder; GNOME 50 removed font keys that GTK3 in Gamescope still reads
  local src=/usr/share/glib-2.0/schemas
  mkdir -p "$1"
  cp "$src/org.gnome.settings-daemon.enums.xml" "$1/"
  python3 - "$src/org.gnome.settings-daemon.plugins.xsettings.gschema.xml" "$1" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
main = re.search(r'(<schema [^>]*id="org.gnome.settings-daemon.plugins.xsettings"[^>]*>)(.*?)</schema>', src, re.S)
dep = re.search(r'<schema id="org.gnome.settings-daemon.plugins.xsettings.deprecated">(.*?)</schema>', src, re.S)
body = main.group(2) + (dep.group(1) if dep and "antialiasing" not in main.group(2) else "")
open(sys.argv[2] + "/org.gnome.settings-daemon.plugins.xsettings.gschema.xml", "w").write(
    '<?xml version="1.0" encoding="UTF-8"?>\n<schemalist>\n  ' + main.group(1) + body + '</schema>\n</schemalist>\n')
PY
  glib-compile-schemas "$1"
}

if [[ "${1:-}" == "--make-schemas" ]]; then
  make_schemas "$2"
  exit 0
fi

if [[ "${1:-}" == "--convert-only" ]]; then
  [[ -d "${2:-}" ]] && convert_videos "$2"
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cd)      CD="$2"; shift 2 ;;
    --cd-copy) CDCOPY="$2"; shift 2 ;;
    --gog)     GOG="$2"; shift 2 ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$CD" || -n "$GOG" ]] || die "--cd (e.g. /run/media/$USER/ANSTOSS2) or --gog <setup.exe> is missing"
[[ -z "$CD" || -z "$GOG" ]] || die "--cd and --gog cannot be combined"
[[ -z "$CD" || -d "$CD" ]] || die "$CD not found"
for f in a2start.exe a2setup.exe; do
  [[ -f "$PKG/src/$f" ]] || die "src/$f is missing next to install.sh"
done
LUTRIS_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
# The "ANSTOSS 2007" DVD: Anstoss 2 Gold of 2007 is an Inno Setup installer in ANSTOSS_2_GOLD
[[ -z "$CD" ]] || DVD="$(find "$(cd "$CD" && pwd)" -maxdepth 2 -ipath '*/anstoss_2_gold/setup.exe' 2>/dev/null | head -1)"

# --- Dependencies ---------------------------------------------------------------
# Missing programs are installed with the package manager (sudo asks for the password, the package
# manager for confirmation). Package per need: apt (Debian, Ubuntu), dnf (Fedora), pacman (Arch),
# zypper (openSUSE); dnf and zypper also take file paths, for packages named differently by version.
DEPS='
need                  apt             dnf                 pacman       zypper
lutris                lutris          lutris              lutris       lutris
ffmpeg                ffmpeg          /usr/bin/ffmpeg     ffmpeg       /usr/bin/ffmpeg
gamescope             gamescope       gamescope           gamescope    gamescope
imagemagick           imagemagick     ImageMagick         imagemagick  ImageMagick
python3               python3         python3             python       python3
zenity                zenity          zenity              zenity       zenity
glib-compile-schemas  libglib2.0-bin  glib2               glib2        glib2-tools
gcc                   gcc             gcc                 gcc          gcc
wayland               libwayland-dev  wayland-devel       wayland      wayland-devel
innoextract           innoextract     innoextract         innoextract  innoextract
curl                  curl            curl                curl         curl
'

find_proton() {  # the folder of GE-Proton11-12, or nothing
  local d
  for d in "$LUTRIS_DATA/lutris/runners/wine/$PROTON" \
           "$HOME"/.local/share/Steam/compatibilitytools.d/"$PROTON"{,-x86_64} \
           "$HOME"/.steam/root/compatibilitytools.d/"$PROTON"{,-x86_64}; do
    [[ -f "$d/proton" ]] && { echo "$d"; return; }
  done
  return 0
}

find_innoextract() {  # Lutris' own innoextract (static build) first, then the system's
  local inno
  for inno in "$LUTRIS_DATA"/lutris/runtime/innoextract*/innoextract; do
    [[ -f "$inno" ]] && { echo "$inno"; return; }
  done
  command -v innoextract || true
}

missing_deps() {  # the needs (first column of DEPS) that are not met
  local t
  for t in lutris ffmpeg gamescope python3 zenity glib-compile-schemas; do
    command -v "$t" >/dev/null || echo "$t"
  done
  command -v magick >/dev/null || command -v convert >/dev/null || echo imagemagick
  if [[ ! -f "$PKG/src/gsfix.so" ]]; then  # not in the git repository, only in the release archive
    command -v gcc >/dev/null || echo gcc
    printf '#include <wayland-client-core.h>\n#include <wayland-client-protocol.h>\n' |
      gcc -fsyntax-only -x c - 2>/dev/null || echo wayland
  fi
  if [[ -n "$GOG" || -n "$DVD" ]] && [[ -z "$(find_innoextract)" ]]; then echo innoextract; fi
  if [[ -z "$(find_proton)" ]]; then command -v curl >/dev/null || echo curl; fi
}

install_deps() {
  local needs pm col pkgs=() n
  mapfile -t needs < <(missing_deps | sort -u)
  [[ ${#needs[@]} -gt 0 ]] || return 0
  for pm in apt-get dnf pacman zypper; do command -v "$pm" >/dev/null && break; pm=""; done
  [[ -n "$pm" ]] || die "missing: ${needs[*]}. Please install them with your package manager."
  case "$pm" in apt-get) col=2 ;; dnf) col=3 ;; pacman) col=4 ;; zypper) col=5 ;; esac
  for n in "${needs[@]}"; do
    pkgs+=("$(awk -v n="$n" -v c="$col" '$1 == n { print $c }' <<< "$DEPS")")
  done
  echo "Missing: ${needs[*]}"
  echo "Installing the packages ${pkgs[*]} with $pm ..."
  if [[ " ${needs[*]} " == *" lutris "* ]] && command -v flatpak >/dev/null &&
     flatpak info net.lutris.Lutris >/dev/null 2>&1; then
    echo "(Lutris is installed as a Flatpak; the installation needs the distribution package as well.)"
  fi
  local sudo=(); [[ $EUID -eq 0 ]] || sudo=(sudo)
  case "$pm" in
    apt-get) "${sudo[@]}" apt-get update && "${sudo[@]}" apt-get install "${pkgs[@]}" ;;
    dnf)     "${sudo[@]}" dnf install "${pkgs[@]}" ;;
    pacman)  "${sudo[@]}" pacman -S --needed "${pkgs[@]}" ;;
    zypper)  "${sudo[@]}" zypper install "${pkgs[@]}" ;;
  esac || die "the installation of ${pkgs[*]} failed"
  mapfile -t needs < <(missing_deps | sort -u)
  [[ ${#needs[@]} -eq 0 ]] || die "still missing after the installation: ${needs[*]}"
}

install_deps
command -v ffprobe >/dev/null || die "ffprobe is missing (it comes with ffmpeg)"
# Fedora's ffmpeg-free may lack codecs; the Indeo videos need these two (RPM Fusion's ffmpeg has them)
codecs="$(ffmpeg -hide_banner -decoders 2>/dev/null; ffmpeg -hide_banner -encoders 2>/dev/null)"
[[ "$codecs" == *" indeo3 "* && "$codecs" == *" msvideo1 "* ]] ||
  die "ffmpeg cannot convert the videos (Indeo 3 decoder or Microsoft Video 1 encoder missing). On Fedora, install ffmpeg from RPM Fusion."
if [[ ! -f "$PKG/src/gsfix.so" ]]; then
  gcc -O2 -Wall -shared -fPIC -o "$PKG/src/gsfix.so" "$PKG/src/gsfix.c" -ldl || die "could not build gsfix.so"
fi

# --- Inno Setup installers (GOG, 2007 CD) -----------------------------------------
inno_prepare() {
  INNO="$(find_innoextract)"
  [[ -n "$INNO" ]] || die "innoextract is missing, please install it with your package manager"
  TMPX="$(mktemp -d)"; trap 'rm -rf "$TMPX"' EXIT
}

gog_prepare() {
  [[ -f "$GOG" ]] || die "$GOG not found"
  GOG="$(cd "$(dirname "$GOG")" && pwd)/$(basename "$GOG")"
  inno_prepare
  "$INNO" -q -l "$GOG" | grep '"run.exe"' >/dev/null || die "$GOG is not the GOG installer of Anstoss 2 Gold (no run.exe in it)"
  # The game's icon, Anstoss2.ico, as for the CD version
  "$INNO" -s -I Anstoss2.ico -d "$TMPX" "$GOG" || die "could not unpack Anstoss2.ico from $GOG"
  ICO="$(find "$TMPX" -iname 'anstoss2.ico' | head -1)"
  [[ -n "$ICO" ]] || die "No Anstoss2.ico in $GOG"
  # GOG product id, for banner and cover from GOG's images of the game
  GOG_ID="$("$INNO" --gog-game-id "$GOG" 2>/dev/null | grep -o '[0-9]\{6,\}' | head -1 || true)"
  GOG_ID="${GOG_ID:-1808817480}"
  SETUP="$GOG"
}

dvd_prepare() {
  # The DVD is read in place (setup, icon and box art); nothing is copied beforehand
  inno_prepare
  "$INNO" -q -l "$DVD" | grep -i '"app/run.exe"' >/dev/null || die "$DVD: no run.exe in it"
  "$INNO" -q -l "$DVD" | grep -i '"app/CD/ARCHIVES/COMMENTS.CPR"' >/dev/null || die "$DVD: no CD files in it"
  "$INNO" -s -I app/anstoss2.ico -I app/CD/AUTORUN.EXE -d "$TMPX" "$DVD" || die "could not unpack the icon from $DVD"
  ICO="$(find "$TMPX" -iname 'anstoss2.ico' | head -1)"
  [[ -n "$ICO" ]] || die "No anstoss2.ico in $DVD"
  SETUP="$DVD"
}

cd_prepare() {
  # --- Copy the CD and convert videos -----------------------------------------
  if [[ ! -d "$CDCOPY" ]]; then
    echo "Copying CD to $CDCOPY ..."
    mkdir -p "$CDCOPY"; cp -r "$CD"/. "$CDCOPY"/; chmod -R u+w "$CDCOPY"
  fi
  convert_videos "$CDCOPY"

  SETUP="$(cd "$CDCOPY" && find . -maxdepth 1 -iname 'setup.exe' -printf '%P\n' | head -1)"
  [[ -n "$SETUP" ]] || die "No setup.exe found in the root folder of the CD"
  # Response file for the silent setup: the CD's SETUP.ISS with the target folder C:\Spiele\Anstoss 2 Gold
  # (szPath, szDir), with CRLF line endings as tested
  ISS="$(find "$CDCOPY" -maxdepth 1 -iname 'setup.iss' | head -1)"
  [[ -n "$ISS" ]] || die "No SETUP.ISS found in the root folder of the CD"
  sed -e 's/\r$//' -e 's/^\(sz\(Path\|Dir\)=\).*/\1C:\\Spiele\\Anstoss 2 Gold/' -e 's/$/\r/' "$ISS" > "$CDCOPY/a2setup.iss"
  [[ "$(grep -c 'Anstoss 2 Gold' "$CDCOPY/a2setup.iss")" == 2 ]] || die "$ISS: unexpected content"
  rm -f "$CDCOPY/a2setup.log"  # from an earlier run, it would vouch for this one

  ICO="$(find "$CDCOPY" -maxdepth 1 -iname 'anstoss2.ico' | head -1)"
  [[ -n "$ICO" ]] || die "No anstoss2.ico found in the root folder of the CD"
}

if [[ -n "$GOG" ]]; then
  # "GOG" in the version makes Lutris treat it as a game of its GOG service (folder ~/Games/gog/<slug>)
  SLUG="anstoss-2-gold-gog"; NAME="Anstoss 2 Gold (GOG)"; VERSION="GOG 1.0 fix2"; EXE="run.exe"; FIXES="--disc-check --v101"; VARIANT=GOG
  gog_prepare
elif [[ -n "$DVD" ]]; then
  SLUG="anstoss-2-gold-2007"; NAME="Anstoss 2 Gold (2007)"; VERSION="CD 2007"; EXE="run.exe"; FIXES="--disc-check --v101"; VARIANT=DVD
  # Drive D: is the folder CD inside the game folder (Lutris replaces $GAMEDIR)
  # shellcheck disable=SC2016
  CDCOPY='$GAMEDIR/drive_c/Spiele/Anstoss 2 Gold/CD'
  dvd_prepare
else
  SLUG="anstoss-2-gold"; NAME="Anstoss 2 Gold"; VERSION="Original-CD"; EXE="anstoss2.exe"; FIXES=""; VARIANT=CD
  cd_prepare
fi

# --- Banner, cover and icon for Lutris ---------------------------------------
mkdir -p "$LUTRIS_DATA/lutris/banners" "$LUTRIS_DATA/lutris/coverart" "$LUTRIS_DATA/icons/hicolor/128x128/apps"
if [[ -n "$DVD" ]]; then
  python3 "$PKG/src/a2assets.py" media "$TMPX" "$LUTRIS_DATA/lutris/banners/$SLUG.jpg" \
      "$LUTRIS_DATA/lutris/coverart/$SLUG.jpg" || die "could not create banner and cover"
elif [[ -n "$GOG" ]]; then
  python3 "$PKG/src/a2assets.py" media-gog "$GOG_ID" "$LUTRIS_DATA/lutris/banners/$SLUG.jpg" \
      "$LUTRIS_DATA/lutris/coverart/$SLUG.jpg" || die "could not create banner and cover"
else
  python3 "$PKG/src/a2assets.py" media "$CDCOPY" "$LUTRIS_DATA/lutris/banners/$SLUG.jpg" \
      "$LUTRIS_DATA/lutris/coverart/$SLUG.jpg" || die "could not create banner and cover"
fi
IM="$(command -v magick || command -v convert)"  # ffmpeg would lose the icon's transparency
"$IM" "$ICO" -filter point -resize 128x128 "PNG32:$LUTRIS_DATA/icons/hicolor/128x128/apps/lutris_$SLUG.png" \
    || die "could not convert $ICO"

# --- Proton for Lutris ----------------------------------------------------------
# Missing GE-Proton11-12 is downloaded from GitHub (checked against its SHA-512) to Steam's folder
# for compatibility tools. Lutris drops "-x86_64" from GE-Proton names and would then look for (and
# try to download) "GE-Proton11-12". A link with that name in its own runner folder points it there.
WINE_DIR="$LUTRIS_DATA/lutris/runners/wine"
if [[ -z "$(find_proton)" ]]; then
  url="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/$PROTON/$PROTON-x86_64"
  tools="$HOME/.local/share/Steam/compatibilitytools.d"
  dl="$(mktemp -d)"
  echo "Downloading $PROTON (about 570 MB) ..."
  curl -fL --progress-bar -o "$dl/$PROTON-x86_64.tar.gz" "$url.tar.gz" || die "could not download $PROTON"
  curl -fsSL -o "$dl/$PROTON-x86_64.sha512sum" "$url.sha512sum" || die "could not download the checksum of $PROTON"
  (cd "$dl" && sha512sum -c --quiet "$PROTON-x86_64.sha512sum") || die "$PROTON: checksum does not match"
  mkdir -p "$tools"
  tar -xzf "$dl/$PROTON-x86_64.tar.gz" -C "$tools" || die "could not unpack $PROTON"
  rm -rf "$dl"
fi
if [[ ! -f "$WINE_DIR/$PROTON/proton" ]]; then
  d="$(find_proton)"
  [[ -n "$d" ]] || die "$PROTON not found. Extract $PROTON-x86_64.tar.gz from https://github.com/GloriousEggroll/proton-ge-custom/releases to ~/.local/share/Steam/compatibilitytools.d/"
  mkdir -p "$WINE_DIR"; ln -sfn "$d" "$WINE_DIR/$PROTON"
fi

# --- Fonts --------------------------------------------------------------------
# build/a2wide*.fnt goes next to the game (see README)
WINE_FONTS="$WINE_DIR/$PROTON/files/share/wine/fonts"
[[ -f "$WINE_FONTS/sserife.fon" ]] || die "$WINE_FONTS/sserife.fon not found"
python3 "$PKG/src/a2assets.py" fonts "$WINE_FONTS" "$PKG/build" || die "could not build the wide font"

# --- Generate and run the Lutris installer ----------------------------------
YML="$PKG/$SLUG.yml"
sedq() { printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'; }  # for the right side of s|...|...|
# Keeps the blocks "# @BEGIN <variants>" ... "# @END" that list $VARIANT, drops the others and the markers
awk -v variant="$VARIANT" '
  /^# @BEGIN / { skip = 1; for (i = 3; i <= NF; i++) if ($i == variant) skip = 0; next }
  /^# @END/ { skip = 0; next }
  !skip' "$PKG/anstoss2.yml.in" |
sed -e "s|@PKG@|$(sedq "$PKG")|g" -e "s|@CDCOPY@|$(sedq "$CDCOPY")|g" -e "s|@SETUP@|$(sedq "$SETUP")|g" \
    -e "s|@INNOEXTRACT@|$(sedq "${INNO:-}")|g" -e "s|@SLUG@|$SLUG|g" -e "s|@NAME@|$NAME|g" \
    -e "s|@VERSION@|$VERSION|g" -e "s|@EXE@|$EXE|g" -e "s| @FIXES@|${FIXES:+ $FIXES}|g" > "$YML"
! grep -n '@[A-Z]*@' "$YML" || die "$YML: placeholder left"
chmod +x "$PKG/install.sh"
echo "Starting Lutris installation ($YML) ..."
lutris -i "$YML"
