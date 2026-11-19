#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Draws the editor's icon, a football, as src/editor-icon.svg (or the file given).

    python3 .github/editor-icon.py [out.svg]
    rsvg-convert -w 128 -h 128 src/editor-icon.svg -o src/editor-icon.png

The ball is a truncated icosahedron (12 black pentagons, 20 white hexagons) blown up to a sphere:
each seam is a great circle arc, seen from the front with a hexagon facing the viewer and a
pentagon straight above it. Seams behind the ball are laid onto its outline, then everything is
clipped to the circle and shaded towards the lower right. The pentagon at the lower right gets a
dark blue glint.
"""

import itertools
import math
import sys

PHI = (1 + 5**0.5) / 2
R, C = 61.0, 64.0  # radius and centre of the ball in the 128 x 128 icon
STEPS = 8  # points per seam


def norm(v):
    length = math.sqrt(sum(a * a for a in v))
    return tuple(a / length for a in v)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def points(*bases):
    """All sign changes of the cyclic permutations of bases, on the unit sphere, sorted."""
    out = set()
    for x, y, z in bases:
        for p in ((x, y, z), (y, z, x), (z, x, y)):
            for s in itertools.product((1, -1), repeat=3):
                out.add(tuple(a * b for a, b in zip(p, s)))
    return sorted(norm(v) for v in out)


CORNERS = points((0, 1, 3 * PHI), (1, 2 + PHI, 2 * PHI), (PHI, 2, PHI**3))  # 60 corners of the ball
PENTAGONS = points((0, 1, PHI))  # their centres: the 12 corners of an icosahedron
HEXAGONS = sorted(  # their centres: the 20 faces of the icosahedron, with the face's corners
    (norm(tuple(map(sum, zip(a, b, c)))), (a, b, c))
    for a, b, c in itertools.combinations(PENTAGONS, 3)
    if all(abs(dot(p, q) - 5**-0.5) < 1e-9 for p, q in ((a, b), (b, c), (a, c)))
)
assert len(CORNERS) == 60 and len(PENTAGONS) == 12 and len(HEXAGONS) == 20

# The view: the first hexagon's centre towards the viewer (z), one of its pentagons straight up (y)
FRONT, (UP, _, _) = HEXAGONS[0]
Y = norm(tuple(u - dot(UP, FRONT) * f for u, f in zip(UP, FRONT)))
X = cross(Y, FRONT)


def view(v):
    return (dot(v, X), dot(v, Y), dot(v, FRONT))


def face(centre, n):
    """The n corners around centre, in order."""
    near = sorted(CORNERS, key=lambda v: -dot(v, centre))[:n]
    u = norm(cross(centre, (0.3, 0.5, 0.8)))
    w = cross(centre, u)
    return sorted(near, key=lambda v: math.atan2(dot(v, w), dot(v, u)))


def seen(corners):
    """The edge of a face as seen, as points in the icon: great circle arcs, the hidden parts laid
    onto the ball's outline."""
    pts = []
    for a, b in zip(corners, corners[1:] + corners[:1]):
        for i in range(STEPS):
            x, y, z = view(norm(tuple(p + (q - p) * i / STEPS for p, q in zip(a, b))))
            if z < 0:
                length = math.hypot(x, y)
                x, y = x / length, y / length
            pts.append((C + R * x, C - R * y))
    return pts


def outline(corners):
    """SVG path of a face as seen."""
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in seen(corners)) + " Z"


def at(centre, dx=0.0, dy=0.0):
    """cx and cy of a point dx, dy away from where centre is seen."""
    x, y, _ = view(centre)
    return f'cx="{C + R * x + dx:.1f}" cy="{C - R * y + dy:.1f}"'


def visible(corners):
    return any(view(v)[2] > 0.02 for v in corners)


def svg():
    pentagons = [outline(face(c, 5)) for c in PENTAGONS if visible(face(c, 5))]
    hexagons = [outline(face(c, 6)) for c, _ in HEXAGONS if visible(face(c, 6))]
    # the pentagon at the lower right: its centre seen right of and below the middle, facing the viewer
    lower_right = max(PENTAGONS, key=lambda c: view(c)[0] - view(c)[1] + view(c)[2])
    ball = f'cx="{C:g}" cy="{C:g}" r="{R:g}"'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <!-- SPDX-License-Identifier: GPL-3.0-only -->
  <!-- Icon of the data editor: a football, drawn by .github/editor-icon.py (do not edit by hand).
       src/editor-icon.png is this picture at 128x128, rendered with rsvg-convert. -->
  <defs>
    <clipPath id="ball"><circle {ball}/></clipPath>
    <!-- Darker towards the rim, most at the lower right -->
    <radialGradient id="shade" cx="0.42" cy="0.38" r="0.62">
      <stop offset="0.55" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000" stop-opacity="0.38"/>
    </radialGradient>
    <!-- The glint in the lower right pentagon: dark blue in the middle, fading to its black -->
    <clipPath id="lower-right"><path d="{outline(face(lower_right, 5))}"/></clipPath>
    <radialGradient id="glint">
      <stop offset="0" stop-color="#2626c8" stop-opacity="0.9"/>
      <stop offset="0.4" stop-color="#101070" stop-opacity="0.5"/>
      <stop offset="1" stop-color="#000060" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <g clip-path="url(#ball)" stroke="#8c8c8c" stroke-width="1.4" stroke-linejoin="round">
    <circle {ball} fill="#ffffff" stroke="none"/>
    <!-- White hexagons, then black pentagons, with grey seams -->
    <path fill="#ffffff" d="{' '.join(hexagons)}"/>
    <path fill="#1c1c1c" d="{' '.join(pentagons)}"/>
    <ellipse {at(lower_right)} rx="13" ry="10" fill="url(#glint)" stroke="none" clip-path="url(#lower-right)"/>
    <circle {ball} fill="url(#shade)" stroke="none"/>
  </g>
  <circle cx="{C:g}" cy="{C:g}" r="{R - 0.6:g}" fill="none" stroke="#555555" stroke-width="1.2"/>
</svg>
"""


if __name__ == "__main__":
    with open(sys.argv[1] if len(sys.argv) > 1 else "src/editor-icon.svg", "w") as f:
        f.write(svg())
