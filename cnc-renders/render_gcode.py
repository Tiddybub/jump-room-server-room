#!/usr/bin/env python3
"""Render a top-down picture of the finished part and the toolpaths from a G-code file."""
import math
import re
import sys

from PIL import Image, ImageDraw, ImageFont

SRC = sys.argv[1]
OUT_DIR = sys.argv[2]

TOOL_DIA = 6.0        # mm (inferred: dog-bone relief + helix radius -> R3.0)
STOCK_TOP = 17.145    # mm (hole lead-ins start here)
SCALE = 3.0           # px per mm
MARGIN = 40           # mm around toolpath extents (room for notes)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


# ---------------------------------------------------------------- parse
WORD = re.compile(r"([A-Z])(-?\d+\.?\d*)")


def parse(path):
    """Yield (op, gcode, x0,y0,z0, x1,y1,z1, i,j, feed)."""
    x = y = z = 0.0
    modal_g = 0
    op = "START"
    segs = []
    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line == "%":
                continue
            m = re.search(r"\((.*?)\)", line)
            if m:
                op = m.group(1).strip()
                continue
            words = dict()
            for k, v in WORD.findall(line):
                if k == "N":
                    continue
                words.setdefault(k, float(v))
            if "M" in words:
                continue
            if "G" in words:
                modal_g = int(words["G"])
            nx = words.get("X", x)
            ny = words.get("Y", y)
            nz = words.get("Z", z)
            if (nx, ny, nz) == (x, y, z):
                continue
            segs.append((op, modal_g, x, y, z, nx, ny, nz,
                         words.get("I", 0.0), words.get("J", 0.0)))
            x, y, z = nx, ny, nz
    return segs


def arc_points(x0, y0, x1, y1, i, j, cw, tol=0.15):
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    if r < 1e-9:
        return [(x0, y0), (x1, y1)]
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        while a1 >= a0 - 1e-9:
            a1 -= 2 * math.pi
        sweep = a1 - a0
    else:
        while a1 <= a0 + 1e-9:
            a1 += 2 * math.pi
        sweep = a1 - a0
    # full circle when start == end
    if math.hypot(x1 - x0, y1 - y0) < 1e-6:
        sweep = -2 * math.pi if cw else 2 * math.pi
    n = max(2, int(abs(sweep) * r / tol) + 1)
    n = min(n, 400)
    pts = []
    for k in range(n + 1):
        a = a0 + sweep * k / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts[-1] = (x1, y1)
    return pts


segs = parse(SRC)
ops = []
for s in segs:
    if s[0] not in ops:
        ops.append(s[0])

xs = [v for s in segs for v in (s[2], s[5])]
ys = [v for s in segs for v in (s[3], s[6])]
minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
W = int((maxx - minx + 2 * MARGIN) * SCALE)
H = int((maxy - miny + 2 * MARGIN) * SCALE)


def P(x, y):
    """mm -> px, Y up."""
    return ((x - minx + MARGIN) * SCALE, (maxy - y + MARGIN) * SCALE)


# ---------------------------------------------------------------- depth model
# Draw cutting moves shallow-first, deep-last, into a greyscale "depth" image
# where pixel value encodes remaining material height.
# value 255 = untouched stock, 0 = cut through.
def z_to_val(zv):
    zv = max(0.0, min(STOCK_TOP, zv))
    return int(round(zv / STOCK_TOP * 254)) + 1 if zv > 0.001 else 0


depth = Image.new("L", (W, H), 255)
ddraw = ImageDraw.Draw(depth)
tool_px = TOOL_DIA * SCALE

cut_moves = []  # (zmin, polyline pts)
rapid_moves = []
op_moves = {o: [] for o in ops}
for op, g, x0, y0, z0, x1, y1, z1, i, j in segs:
    if g == 0:
        rapid_moves.append([(x0, y0), (x1, y1)])
        continue
    if g in (2, 3):
        pts = arc_points(x0, y0, x1, y1, i, j, cw=(g == 2))
    else:
        pts = [(x0, y0), (x1, y1)]
    zmin = min(z0, z1)
    op_moves[op].append((zmin, pts))
    if zmin < STOCK_TOP - 1e-6:
        cut_moves.append((zmin, pts))

cut_moves.sort(key=lambda t: -t[0])  # shallow first


def stroke(draw, pts, width, fill):
    px = [P(*p) for p in pts]
    if len(px) >= 2:
        draw.line(px, fill=fill, width=int(round(width)), joint="curve")
    r = width / 2.0
    for (ax, ay) in (px[0], px[-1]):
        draw.ellipse([ax - r, ay - r, ax + r, ay + r], fill=fill)


for zmin, pts in cut_moves:
    stroke(ddraw, pts, tool_px, z_to_val(zmin))

# ---------------------------------------------------------------- part / skeleton / drops
# Material mask: anything thicker than the holding tabs (~2.8 mm) counts as solid.
TAB_VAL = z_to_val(3.0)
mask = depth.point(lambda v: 255 if v >= TAB_VAL else 0)
# Skeleton = solid material connected to the image border.
ImageDraw.floodfill(mask, (0, 0), 128)
# Label remaining solid components.
data = bytearray(mask.tobytes())
components = []  # (label value, pixel count)
label = 200
while True:
    idx = data.find(b"\xff")
    if idx < 0:
        break
    sx, sy = idx % W, idx // W
    ImageDraw.floodfill(mask, (sx, sy), label)
    newdata = bytearray(mask.tobytes())
    count = sum(1 for a, b in zip(data, newdata) if a != b) if False else None
    data = newdata
    components.append(label)
    label -= 1
    if label < 130:
        break

# count pixels per label
hist = mask.histogram()
comp_sizes = {lab: hist[lab] for lab in components}
part_label = max(comp_sizes, key=comp_sizes.get) if comp_sizes else None
print("components:", {k: v for k, v in sorted(comp_sizes.items(), key=lambda kv: -kv[1])})

# ---------------------------------------------------------------- render finished part
BG = (236, 238, 241)          # spoilboard / background
SKEL = (214, 216, 220)        # offcut skeleton (removed, shown faint)
TOP = (222, 184, 135)         # plywood face
EDGE = (120, 86, 50)

img = Image.new("RGB", (W, H), BG)
pix = img.load()
dpx = depth.load()
mpx = mask.load()


def wood(val):
    """Depth value -> colour: full height is light tan, deeper is darker."""
    t = val / 255.0  # 1 = full, 0 = through
    # darken as the pocket deepens
    r = int(TOP[0] * (0.55 + 0.45 * t))
    g = int(TOP[1] * (0.55 + 0.45 * t))
    b = int(TOP[2] * (0.55 + 0.45 * t))
    return (r, g, b)


for yy in range(H):
    for xx in range(W):
        m = mpx[xx, yy]
        d = dpx[xx, yy]
        if m == part_label:
            pix[xx, yy] = wood(d)
        elif m == 128:
            pix[xx, yy] = SKEL if d >= TAB_VAL else BG
        else:
            # drops (cutouts that fall away) and kerf
            pix[xx, yy] = BG

# subtle edge line where part meets a cut (helps thin features read)
edge = Image.new("L", (W, H), 0)
part_mask = mask.point(lambda v: 255 if v == part_label else 0)
from PIL import ImageFilter
outline = part_mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 0 else 0)
img.paste(Image.new("RGB", (W, H), EDGE), mask=outline)

# pocket floor edge (where depth steps down inside the part)
step = depth.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 8 else 0)
step_in_part = Image.composite(step, Image.new("L", (W, H), 0), part_mask)
step_in_part = Image.composite(Image.new("L", (W, H), 0), step_in_part, outline)
img.paste(Image.new("RGB", (W, H), (160, 120, 75)), mask=step_in_part)

# ---------------------------------------------------------------- annotate
draw = ImageDraw.Draw(img)
f_title = font(int(10 * SCALE), bold=True)
f_body = font(int(6.5 * SCALE))
f_small = font(int(5.5 * SCALE))
INK = (40, 40, 45)

part_w = maxx - minx - TOOL_DIA
part_h = maxy - miny - TOOL_DIA
title = "Tankside.MMG  -  finished part, top view"
draw.text((MARGIN * SCALE, 8 * SCALE), title, fill=INK, font=f_title)
sub = (f"Part approx. {part_w:.1f} x {part_h:.1f} mm  |  stock {STOCK_TOP:.3f} mm thick  |  "
       f"tool O{TOOL_DIA:.0f} mm (inferred)  |  ops: " + ", ".join(ops))
draw.text((MARGIN * SCALE, 22 * SCALE), sub, fill=INK, font=f_body)

# legend bottom-left
lx, ly = MARGIN * SCALE, H - 26 * SCALE
items = [
    (wood(255), "material, full thickness"),
    (BG, "cut through (holes, hexagons, pocket window, outline)"),
    (SKEL, "offcut / sheet remainder"),
]
for k, (col, txt) in enumerate(items):
    bx = lx + k * 0  # vertical list
    yy = ly + k * 7 * SCALE
    draw.rectangle([lx, yy, lx + 6 * SCALE, yy + 5 * SCALE], fill=col, outline=INK)
    draw.text((lx + 9 * SCALE, yy - 0.5 * SCALE), txt, fill=INK, font=f_small)

# dimension arrows (overall)
ax0, ay0 = P(minx + TOOL_DIA / 2, miny + TOOL_DIA / 2)
ax1, ay1 = P(maxx - TOOL_DIA / 2, maxy - TOOL_DIA / 2)
dy = ay0 + 10 * SCALE
draw.line([(ax0, dy), (ax1, dy)], fill=INK, width=2)
for ax in (ax0, ax1):
    draw.line([(ax, dy - 3 * SCALE), (ax, dy + 3 * SCALE)], fill=INK, width=2)
draw.text(((ax0 + ax1) / 2 - 20 * SCALE, dy + 1.5 * SCALE), f"{part_w:.1f} mm", fill=INK, font=f_body)
dx = ax1 + 10 * SCALE
draw.line([(dx, ay0), (dx, ay1)], fill=INK, width=2)
for ay in (ay0, ay1):
    draw.line([(dx - 3 * SCALE, ay), (dx + 3 * SCALE, ay)], fill=INK, width=2)
txt = Image.new("RGBA", (int(40 * SCALE), int(8 * SCALE)), (0, 0, 0, 0))
ImageDraw.Draw(txt).text((0, 0), f"{part_h:.1f} mm", fill=INK, font=f_body)
txt = txt.rotate(90, expand=True)
img.paste(txt, (int(dx + 2 * SCALE), int((ay0 + ay1) / 2 - 20 * SCALE)), txt)

img.save(f"{OUT_DIR}/tankside_finished_part.png", optimize=True)
print("saved finished part", img.size)

# ---------------------------------------------------------------- toolpath drawing
tp = Image.new("RGB", (W, H), (255, 255, 255))
tdraw = ImageDraw.Draw(tp)
palette = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189),
           (140, 86, 75), (227, 119, 194), (127, 127, 127)]
op_color = {o: palette[k % len(palette)] for k, o in enumerate(ops)}

# rapids faint
for pts in rapid_moves:
    tdraw.line([P(*p) for p in pts], fill=(215, 215, 215), width=1)
# cutting moves by op (only moves below stock top)
for o in ops:
    for zmin, pts in op_moves[o]:
        if zmin >= STOCK_TOP - 1e-6:
            continue
        tdraw.line([P(*p) for p in pts], fill=op_color[o], width=2)

tdraw.text((MARGIN * SCALE, 8 * SCALE), "Tankside.MMG  -  toolpath centerlines by operation", fill=INK, font=f_title)
tdraw.text((MARGIN * SCALE, 22 * SCALE), "grey = rapid moves above the material", fill=INK, font=f_body)
ly = H - 36 * SCALE
notes = {"ROUGHING 117": "outline rough pass, leaves 3.8 mm skin (hidden under OUTER CUTS)",
         "POCKET 119": "six slot pockets, 2 depth passes to Z 0",
         "HOLES 117": "helical bored holes, ~9.5 mm dia",
         "SLOTS 191": "eleven hexagon cutouts, ramped through",
         "OUTER CUTS 2 153": "final outline through cut with 4 holding tabs"}
for k, o in enumerate(ops):
    yy = ly + k * 6.5 * SCALE
    n = sum(1 for zmin, _ in op_moves[o] if zmin < STOCK_TOP - 1e-6)
    zs = [zmin for zmin, _ in op_moves[o] if zmin < STOCK_TOP - 1e-6]
    zlo = min(zs) if zs else 0
    tdraw.line([(lx, yy + 2.5 * SCALE), (lx + 8 * SCALE, yy + 2.5 * SCALE)], fill=op_color[o], width=6)
    tdraw.text((lx + 11 * SCALE, yy), f"{o}   (deepest Z {zlo:.2f} mm)  -  {notes.get(o, '')}", fill=INK, font=f_small)
tp.save(f"{OUT_DIR}/tankside_toolpaths.png", optimize=True)
print("saved toolpaths", tp.size)
