#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Makes ARCHIVES/MoveList.dat, new in patch 1.01: the animation of a sign flying into a video window
(probably the cup draw), 34 frames.

    a2movelist.py <output file>

The game draws a 128x32 picture (made at run time) into each frame through a lookup table: for every
pixel of the frame, the byte offset of a pixel of the picture (16 bit per pixel, 256 bytes per row);
0 leaves the pixel out. File: u16 count, then per frame u16 number, x, y, width, height and
width x height u16 offsets.

This module does not contain those tables. It holds the path of the sign: per frame its number,
position and size on the screen and the four corners of the picture in the frame (in 1/16 pixel),
and computes each table as the perspective projection of the picture onto that quadrilateral
(points outside it take the nearest edge of the picture). Inside the sign the result differs from
the file of patch 1.01 by at most one pixel (rounding); the thin edge around the sign shows the
edge of the picture.
"""

import struct
import sys

TEXTURE_W, TEXTURE_H = 128, 32
# number, x, y, width, height, corners of the picture (top left, top right, bottom right, bottom
# left) in 1/16 pixel relative to the frame, or None for an empty frame
PATH = (
    (27, 0, 0, 1, 1, None),
    (28, 99, 284, 11, 11, ((-414, 0), (143, -5), (145, 156), (-425, 152))),
    (29, 99, 284, 23, 11, ((-223, -4), (345, -6), (345, 155), (-224, 153))),
    (30, 99, 284, 35, 11, ((-26, -5), (541, -5), (541, 154), (-27, 154))),
    (31, 110, 284, 37, 11, ((-3, -5), (566, -5), (566, 154), (-3, 154))),
    (32, 122, 284, 37, 11, ((4, -5), (572, -5), (572, 154), (4, 155))),
    (33, 125, 287, 39, 12, ((-3, -3), (601, -2), (600, 168), (-3, 168))),
    (34, 125, 292, 43, 13, ((3, -1), (657, -1), (658, 184), (3, 184))),
    (35, 124, 299, 47, 14, ((-10, -2), (717, -2), (716, 204), (-9, 204))),
    (36, 119, 308, 54, 16, ((4, 7), (828, 7), (828, 239), (4, 239))),
    (37, 112, 321, 62, 18, ((8, 0), (960, 0), (961, 271), (7, 271))),
    (38, 103, 337, 73, 22, ((-3, 6), (1119, 6), (1117, 323), (-1, 323))),
    (39, 90, 358, 87, 25, ((6, 0), (1338, 0), (1337, 374), (7, 374))),
    (40, 76, 381, 102, 30, ((6, 3), (1578, 5), (1578, 448), (5, 449))),
    (41, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (42, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (43, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (44, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (45, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (46, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (47, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (48, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (49, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (50, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (51, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (52, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (53, 64, 402, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (54, 64, 409, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (55, 64, 416, 117, 35, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (56, 64, 423, 117, 33, ((10, 8), (1806, 8), (1805, 520), (10, 520))),
    (57, 64, 430, 117, 26, ((10, 8), (1806, 8), (1805, 520), (11, 520))),
    (58, 64, 437, 117, 19, ((10, 8), (1806, 8), (1805, 520), (11, 520))),
    (59, 64, 444, 117, 12, ((9, 11), (1806, 11), (1801, 492), (15, 492))),
    (60, 64, 450, 117, 6, ((10, 24), (1806, 24), (1785, 525), (30, 525))),
)


def solve(a, b):
    """Solves the 8x8 system a x = b (Gaussian elimination with pivoting)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(corners):
    """Coefficients mapping a frame pixel (x, y) to picture coordinates (u, v)."""
    src = ((-0.5, -0.5), (TEXTURE_W - 0.5, -0.5), (TEXTURE_W - 0.5, TEXTURE_H - 0.5), (-0.5, TEXTURE_H - 0.5))
    a, b = [], []
    for (u, v), (x, y) in zip(src, ((cx / 16, cy / 16) for cx, cy in corners)):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return solve(a, b)


def frame(width, height, corners):
    if corners is None:
        return [0] * (width * height)
    a, b, c, d, e, f, g, h = homography(corners)
    out = []
    for y in range(height):
        for x in range(width):
            den = g * x + h * y + 1
            u = min(max(int((a * x + b * y + c) / den + 0.5 + 1e6) - 1000000, 0), TEXTURE_W - 1)
            v = min(max(int((d * x + e * y + f) / den + 0.5 + 1e6) - 1000000, 0), TEXTURE_H - 1)
            out.append(v * TEXTURE_W * 2 + u * 2)
    return out


def build():
    data = [struct.pack("<H", len(PATH))]
    for number, x, y, width, height, corners in PATH:
        data.append(struct.pack("<5H", number, x, y, width, height))
        data.append(struct.pack(f"<{width * height}H", *frame(width, height, corners)))
    return b"".join(data)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[3].strip())
    with open(sys.argv[1], "wb") as f:
        f.write(build())


if __name__ == "__main__":
    main()
