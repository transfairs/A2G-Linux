#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Builds the wide font and collects the Lutris images at installation time, so the repository
holds no third-party files.

    a2assets.py fonts <Wine fonts folder> <output folder>
    a2assets.py media <CD copy> <banner.jpg> <coverart.jpg>
    a2assets.py media-gog <GOG product id> <banner.jpg> <coverart.jpg>

fonts: writes a2wide20.fnt (mkwide.py, from Wine's MS Sans Serif) to <output folder>. All fonts of
  the game are Wine's or Proton's.
media: banner and cover, cut out of the box art that AUTORUN.EXE on the CD shows.
media-gog: banner and cover from the images GOG shows for the game (box art and logo), fetched from
  GOG's public product API. Without a connection, Lutris shows its default images.
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

GOG_API = "https://api.gog.com/v2/games/{}?locale=de-DE"
USER_AGENT = "anstoss2-linux-installer"


def find(folder, name):
    """Path of name in folder or one of its subfolders, any case, or None."""
    lower = name.lower()
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower() == lower:
                return os.path.join(root, f)
    return None


def fonts(wine_fonts, out):
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
    # The image links come from GOG's API response: only https, no file: or other schemes
    if not isinstance(url, str) or not url.startswith("https://"):
        raise urllib.error.URLError(f"not an https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # nosec B310
        shutil.copyfileobj(r, f)


def media_gog(product, banner, cover):
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


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "fonts":
        fonts(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 5 and sys.argv[1] == "media":
        media(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 5 and sys.argv[1] == "media-gog":
        media_gog(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit("\n".join(__doc__.strip().splitlines()[3:6]))


if __name__ == "__main__":
    main()
