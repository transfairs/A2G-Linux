#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Builds the wide font and collects the Lutris images at installation time, so the repository
holds no third-party files.

    a2assets.py fonts <Wine fonts folder> <output folder>
    a2assets.py media <CD copy> <banner.jpg> <coverart.jpg>
    a2assets.py media-gog <GOG product id> <banner.jpg> <coverart.jpg>
    a2assets.py icon-check
    a2assets.py icon <game|repo|file> <anstoss2.ico> <hicolor folder> <icon name> [<desktop.bmp>]

fonts: writes a2wide20.fnt (mkwide.py, from Wine's MS Sans Serif) to <output folder>. All fonts of
  the game are Wine's or Proton's.
media: banner and cover, cut out of the box art that AUTORUN.EXE on the CD shows.
media-gog: banner and cover from the images GOG shows for the game (box art and logo), fetched from
  GOG's public product API. Without a connection, Lutris shows its default images.
icon-check: exit status 0 if the icon of the repository A2G-Icon can be fetched and is usable, so
  the installer offers it only then.
icon: <icon name>.png (128x128, for Lutris) and <icon name>.svg (scalable, for the dock and the
  application menu), as the player chose in the installer: "game" the game's own 32x32 icon,
  scaled with sharp pixels; "repo" the icon of the repository A2G-Icon, a redrawing of the game's
  icon kept apart from this repository (see its README); "file" a PNG and/or SVG picked in a
  dialog (such as the files of A2G-Icon). If A2G-Icon can't be fetched or nothing usable is picked,
  the game's own icon is used. With <desktop.bmp>, A2G-Icon's or the picked icon is also written
  there as background picture of the virtual desktop (256x256 on the desktop color, which Wine
  shows centred); with the game's own icon, <desktop.bmp> is removed, the desktop stays plain.
"""

import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkwide  # noqa: E402
from a2extras import pe_resources  # noqa: E402
from a2import import zenity  # noqa: E402

GOG_API = "https://api.gog.com/v2/games/{}?locale=de-DE"
USER_AGENT = "anstoss2-linux-installer"
ICON_URL = "https://raw.githubusercontent.com/transfairs/A2G-Icon/main/anstoss2-icon.{}"
# Background of the virtual desktop: the "Background" color the Lutris scripts set, the icon's size on it
DESKTOP_COLOR = "rgb(41,56,74)"
DESKTOP_ICON = 256


def find(folder, name):
    """Path of name in folder or one of its subfolders, any case, or None."""
    lower = name.lower()
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower() == lower:
                return os.path.join(root, f)
    return None


def fonts(wine_fonts, out):
    """Writes a2wide20.fnt to out, made from sserife.fon in wine_fonts; removes fonts of older versions."""
    shutil.rmtree(os.path.join(out, "fonts"), ignore_errors=True)  # left over from older versions
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "a2wide*.fnt")):
        os.remove(old)
    # Wine's MS Sans Serif has no 24 px size, so only a2wide20.fnt is built from it
    mkwide.main(os.path.join(wine_fonts, "sserife.fon"), os.path.join(out, "a2wide"))


def autorun_cover(cd, tmp):
    """The box art from AUTORUN.EXE on the CD as a BMP file, or None."""
    exe = find(cd, "autorun.exe")
    if not exe:
        return None
    try:
        bitmaps = pe_resources(exe)
        # RT_BITMAP 130 (1999 CD) or 129 (2007 CD, the same picture): the Anstoss 2 Gold box
        data = (bitmaps.get((2, 130)) or bitmaps.get((2, 129)) or [None])[0]
    except (OSError, ValueError, struct.error):
        return None
    if not data:
        return None
    hsize, w, h, _, bpp = struct.unpack_from("<IiiHH", data)
    colors = struct.unpack_from("<I", data, 32)[0] or (1 << bpp if bpp <= 8 else 0)
    if (w, h, bpp) != (300, 386, 8):
        return None
    bmp = os.path.join(tmp, "cover.bmp")
    with open(bmp, "wb") as f:
        f.write(b"BM" + struct.pack("<IHHI", 14 + len(data), 0, 0, 14 + hsize + 4 * colors) + data)
    return bmp


def media(cd, banner, cover):
    """Writes banner and cover, cut out of the box art on the CD; writes nothing if the CD has none."""
    im = shutil.which("magick") or shutil.which("convert")
    os.makedirs(os.path.dirname(banner), exist_ok=True)
    os.makedirs(os.path.dirname(cover), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        bmp = autorun_cover(cd, tmp)
        if not bmp:
            print("No box art on the CD, Lutris shows its default images")
            return
        for key, dest in (("banner", banner), ("cover", cover)):
            if key == "cover":
                # inside the frame: 255x335 from (24, 0), Lutris size 264x352
                subprocess.run(
                    [im, bmp, "-crop", "255x335+24+0", "+repage", "-resize", "264x352!", "-quality", "92", dest],
                    check=True,
                )
            else:
                # the logo, widened to 8:3 with a dark, blurred copy of itself behind it
                logo = os.path.join(tmp, "logo.png")
                subprocess.run([im, bmp, "-crop", "255x150+24+0", "+repage", logo], check=True)
                background = ["(", logo, "-resize", "400x150!", "-blur", "0x8", "-brightness-contrast", "-40x0", ")"]
                result = ["-resize", "368x138", "-quality", "92", dest]
                subprocess.run([im, *background, logo, "-gravity", "center", "-composite", *result], check=True)
            print(f"{key}: from the box art on the CD")


def download(url, dest):
    """Saves url to dest; raises URLError if url is not an https URL."""
    # The image links come from GOG's API response: only https, no file: or other schemes
    if not isinstance(url, str) or not url.startswith("https://"):
        raise urllib.error.URLError(f"not an https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # nosec B310
        shutil.copyfileobj(r, f)


def media_gog(product, banner, cover):
    """Writes banner and cover from GOG's box art and logo of product; writes nothing if they can't be fetched."""
    im = shutil.which("magick") or shutil.which("convert")
    os.makedirs(os.path.dirname(banner), exist_ok=True)
    os.makedirs(os.path.dirname(cover), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        box, logo = os.path.join(tmp, "box.jpg"), os.path.join(tmp, "logo.png")
        try:
            api = os.path.join(tmp, "game.json")
            download(GOG_API.format(product), api)
            with open(api) as f:
                links = json.load(f)["_links"]
            download(links["boxArtImage"]["href"], box)
            download(links["logo"]["href"], logo)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"Images from GOG not available ({e}), Lutris shows its default images")
            return
        # cover: the box art, cut to Lutris' 264x352
        subprocess.run(
            [im, box, "-resize", "264x352^", "-gravity", "center", "-extent", "264x352", "-quality", "92", cover],
            check=True,
        )
        # banner: the logo (transparent) on the sky at the top of the box art, 368x138
        sky = [box, "-resize", "368x", "-crop", "368x138+0+20", "+repage", "-brightness-contrast", "-15x0"]
        title = ["(", logo, "-trim", "+repage", "-resize", "340x122", ")"]
        subprocess.run([im, *sky, *title, "-gravity", "center", "-composite", "-quality", "92", banner], check=True)
        print("banner, cover: from GOG's images of the game")


def fetch_icon(tmp):
    """(png, svg) of A2G-Icon downloaded to tmp, or None if they can't be fetched or aren't a
    128x128 PNG and an SVG."""
    png, svg = os.path.join(tmp, "icon.png"), os.path.join(tmp, "icon.svg")
    try:
        download(ICON_URL.format("png"), png)
        download(ICON_URL.format("svg"), svg)
        with open(png, "rb") as f:
            head = f.read(24)
        with open(svg, "rb") as f:
            text = f.read()
    except OSError as e:
        print(f"Icon of A2G-Icon not available ({e})")
        return None
    if not is_png(head) or head[16:24] != struct.pack(">II", 128, 128) or not is_svg(text):
        print("Icon of A2G-Icon not usable")
        return None
    return png, svg


def is_png(head):
    """Whether head (the first bytes of a file) starts a PNG."""
    return head[:8] == b"\x89PNG\r\n\x1a\n"


def is_svg(head):
    """Whether head (the first bytes of a file) is the start of an SVG, where icon loaders look for it."""
    return b"<svg" in head[:200]


def own_icon():
    """(png, svg) the user picks as icon in a file dialog, either may be None; (None, None) if they
    cancel or there is no display for the dialog."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None, None
    chosen = zenity(
        [
            "--file-selection",
            "--multiple",
            "--separator",
            "\n",
            "--title",
            "Eigenes Icon: ein PNG (für Lutris) und/oder ein SVG (für Dock und Anwendungsmenü), mehrere mit Strg",
            "--file-filter",
            "Icon (*.png *.PNG *.svg *.SVG) | *.png *.PNG *.svg *.SVG",
        ]
    )
    png = svg = None
    for path in (chosen or "").splitlines():
        try:
            with open(path, "rb") as f:
                head = f.read(200)
        except OSError as e:
            print(f"{path}: {e}")
            continue
        if is_png(head):
            png = png or path
        elif is_svg(head):
            svg = svg or path
        else:
            print(f"{path}: neither PNG nor SVG, ignored")
    return png, svg


def render_svg(svg, png, size=128):
    """Renders svg as a size x size PNG with librsvg, through rsvg-convert or else GdkPixbuf (there
    wherever Lutris runs); whether that worked. ImageMagick's own SVG renderer leaves out lines."""
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        subprocess.run([rsvg, "-w", str(size), "-h", str(size), svg, "-o", png], check=True)
        return True
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        GdkPixbuf.Pixbuf.new_from_file_at_size(svg, size, size).savev(png, "png", [], [])
        return True
    except Exception as e:  # no PyGObject, no SVG loader for GdkPixbuf or a broken SVG
        print(f"SVG could not be rendered for Lutris: {e}")
        return False


def desktop_picture(png, svg, bmp):
    """Writes the icon (svg rendered with librsvg, else png) as DESKTOP_ICON square 24-bit BMP to bmp,
    its transparency filled with DESKTOP_COLOR; Wine's virtual desktop shows it centred on that color.
    Whether that worked."""
    im = shutil.which("magick") or shutil.which("convert")
    os.makedirs(os.path.dirname(os.path.abspath(bmp)), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        big = os.path.join(tmp, "icon.png")
        src = big if svg and render_svg(svg, big, DESKTOP_ICON) else png
        if not src:
            return False
        size = f"{DESKTOP_ICON}x{DESKTOP_ICON}"
        fit = ["-resize", size, "-background", DESKTOP_COLOR, "-gravity", "center", "-extent", size]
        subprocess.run([im, src, *fit, "-alpha", "remove", "-alpha", "off", "BMP3:" + bmp], check=True)
    return True


def icon_check():
    """Whether A2G-Icon's icon can be fetched and is usable."""
    with tempfile.TemporaryDirectory() as tmp:
        return fetch_icon(tmp) is not None


def icon(choice, ico, hicolor, name, desktop=None):
    """Installs the icon name to the icon theme folder hicolor, as chosen: "repo" A2G-Icon's drawing,
    "file" an icon the user picks, else (and if those fail) ico. With desktop, writes the first two
    also as desktop picture there (see desktop_picture) and removes it for ico."""
    png = os.path.join(hicolor, "128x128", "apps", name + ".png")
    svg = os.path.join(hicolor, "scalable", "apps", name + ".svg")
    os.makedirs(os.path.dirname(png), exist_ok=True)
    if choice == "repo":
        with tempfile.TemporaryDirectory() as tmp:
            fetched = fetch_icon(tmp)
            if fetched:
                os.makedirs(os.path.dirname(svg), exist_ok=True)
                shutil.copyfile(fetched[0], png)
                shutil.copyfile(fetched[1], svg)
                print("icon: from A2G-Icon")
                if desktop and desktop_picture(*fetched, desktop):
                    print("desktop: A2G-Icon's icon")
                return
    own_png, own_svg = own_icon() if choice == "file" else (None, None)
    # The SVG for the dock; one left from an earlier installation would hide the new icon
    if own_svg:
        os.makedirs(os.path.dirname(svg), exist_ok=True)
        shutil.copyfile(own_svg, svg)
    elif os.path.exists(svg):
        os.remove(svg)
    im = shutil.which("magick") or shutil.which("convert")
    picked = True
    if own_png:
        # A picture that is not square is centred on a transparent square
        fit = ["-resize", "128x128", "-background", "none", "-gravity", "center", "-extent", "128x128"]
        subprocess.run([im, own_png, *fit, "PNG32:" + png], check=True)
        print("icon: picked by the user")
    elif own_svg and render_svg(own_svg, png):
        print("icon: picked by the user")
    else:
        # The game's icon, scaled with sharp pixels
        subprocess.run([im, ico, "-filter", "point", "-resize", "128x128", "PNG32:" + png], check=True)
        print("icon: the game's own" + (" (dock: the SVG picked by the user)" if own_svg else ""))
        picked = False
    if not desktop:
        return
    if picked and desktop_picture(own_png, own_svg, desktop):
        print("desktop: the icon picked by the user")
    elif os.path.exists(desktop):
        # left from an earlier installation; the game's own icon is not shown on the desktop
        os.remove(desktop)


def main():
    """Runs the subcommand on the command line; exits with the usage lines for any other arguments."""
    if len(sys.argv) == 4 and sys.argv[1] == "fonts":
        fonts(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 5 and sys.argv[1] == "media":
        media(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 5 and sys.argv[1] == "media-gog":
        media_gog(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 2 and sys.argv[1] == "icon-check":
        sys.exit(0 if icon_check() else 1)
    elif len(sys.argv) in (6, 7) and sys.argv[1] == "icon" and sys.argv[2] in ("game", "repo", "file"):
        icon(*sys.argv[2:])
    else:
        sys.exit("\n".join(__doc__.strip().splitlines()[3:8]))


if __name__ == "__main__":
    main()
