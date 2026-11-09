#!/usr/bin/env python3
"""3D-style picture of the finished parts, built from the program's cut (height map + oblique view).

Usage: python3 render_3d.py PROGRAM.MMG OUT_PREFIX
Writes OUT_PREFIX_3d.png (all parts) and OUT_PREFIX_closeup.png (one strip end).
"""
import math, sys
sys.path.insert(0, '/home/user/jump-room-server-room/.claude/skills/mmg-clean-cut/scripts')
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from gcode import read_lines, parse, move_pts

PROG, OUT = sys.argv[1], sys.argv[2]
TOP, R = 18.415, 3.0
feats, _ = parse(read_lines(PROG), retract_z=29.0)
moves = [m for f in feats for m in f['cut'] if min(m[4], m[7]) < TOP]
xs = [v for m in moves for v in (m[2], m[5])]; ys = [v for m in moves for v in (m[3], m[6])]
X0, X1, Y0, Y1 = min(xs) - 15, max(xs) + 15, min(ys) - 15, max(ys) + 15


def heightmap(box, res):
    x0, y0, x1, y1 = box
    W, H = int((x1 - x0) / res), int((y1 - y0) / res)
    im = Image.new('F', (W, H), TOP); d = ImageDraw.Draw(im); r = R / res
    for m in sorted(moves, key=lambda m: -min(m[4], m[7])):          # deepest drawn last
        z = min(m[4], m[7])
        pp = [((p[0] - x0) / res, (y1 - p[1]) / res) for p in move_pts(m)]
        d.line(pp, fill=z, width=max(1, int(round(2 * r))))
        for q in (pp[0], pp[-1]):
            d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=z)
    h = np.clip(np.array(im), 0, TOP)
    # keep the parts only: solid above the 3 mm tabs and not connected to the sheet border
    solid = Image.fromarray(((h > 3.5) * 255).astype(np.uint8)).copy()   # writable copy for floodfill
    ImageDraw.floodfill(solid, (0, 0), 128)
    parts = np.array(solid) == 255
    return np.where(parts, h, 0.0)


def render(h, res, scale, tilt_deg, hs, title, sub, path):
    """oblique view: rows drawn back to front; each solid pixel is a column of height h"""
    H, W = h.shape
    t = math.radians(tilt_deg)
    sy = math.sin(t)                 # ground foreshortening
    zpx = hs * math.cos(t) / res     # screen px per mm of height
    cw = int(W * scale) + 40
    chh = int(H * sy * scale + TOP * zpx * scale) + 160
    canvas = np.zeros((chh, cw, 3), np.uint8); canvas[:] = (236, 238, 241)
    # lighting from the top-left for the top faces
    gy, gx = np.gradient(h)
    light = np.clip(1.0 - 0.35 * (gx + gy) / max(res, 1e-6) * 0.0, 0.7, 1.15)
    wood = np.array([222, 186, 138], float); floor = np.array([206, 168, 118], float)
    side = np.array([168, 126, 82], float); edge = np.array([120, 86, 52], float)
    ox, oy = 20, 120 + int(TOP * zpx * scale)
    cols = (np.arange(W) * scale + ox).astype(int)
    for row in range(H):                         # back (top of the image = far) to front
        hr = h[row]; on = hr > 0
        if not on.any():
            continue
        base = int(oy + row * sy * scale)
        tops = (base - hr * zpx * scale).astype(int)
        ci = cols[on]; ti = tops[on]; hv = hr[on]
        # side wall: only where the next row in front is lower (a visible front face)
        nxt = h[row + 1] if row + 1 < H else np.zeros(W)
        front = (hr > nxt + 0.01)[on]
        for k in range(int(TOP * zpx * scale) + 2):
            yy = ti + k
            m = front & (yy <= base - (nxt[on] * zpx * scale)) & (yy < chh)
            if m.any():
                shade = side * (0.85 + 0.15 * (k / (TOP * zpx * scale + 1)))
                for dx in range(max(1, int(math.ceil(scale)))):
                    canvas[yy[m], np.minimum(ci[m] + dx, cw - 1)] = shade
        topc = np.where((hv < TOP - 0.5)[:, None], floor, wood)
        for dx in range(max(1, int(math.ceil(scale)))):
            for dy in range(max(1, int(math.ceil(sy * scale)))):
                canvas[np.minimum(ti + dy, chh - 1), np.minimum(ci + dx, cw - 1)] = topc
    img = Image.fromarray(canvas)
    d = ImageDraw.Draw(img)
    f1 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 30)
    f2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    d.text((20, 18), title, fill=(30, 30, 35), font=f1)
    d.text((20, 60), sub, fill=(30, 30, 35), font=f2)
    img.save(path, optimize=True)
    print('saved', path, img.size)


# whole layout
res = 0.5
h = heightmap((X0, Y0, X1, Y1), res)
render(h, res, 1.5, 38, 1.6, 'Joey Slant Window Frame - finished parts',
       '4 parts out of the sheet, tabs broken off. Darker steps at every end: 3 in long, 9 mm deep half-lap pockets.',
       OUT + '_3d.png')
# close-up of the left end of Part 3 (the strip in your photo)
res2 = 0.1
box = (10, 75, 130, 140)
h2 = heightmap(box, res2)
render(h2, res2, 1.0, 35, 1.0, 'Close-up: end of a strip',
       'Pocket 3 in (76.2 mm) long, full width, 9 mm deep; the other 9.4 mm of the board stays.',
       OUT + '_closeup.png')
