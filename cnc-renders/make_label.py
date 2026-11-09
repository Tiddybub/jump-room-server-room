#!/usr/bin/env python3
"""Generate an engraved-text label program (Tankside.MMG style G-code) and a preview picture.

Units: millimetres (the Tankside.MMG sample is metric), Z0 = bottom of stock / spoilboard.
Usage: python3 make_label.py "hello world" out_dir
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TEXT = sys.argv[1] if len(sys.argv) > 1 else "hello world"
OUT = sys.argv[2] if len(sys.argv) > 2 else "."

IN = 25.4
STOCK_W = 20 * IN            # 508.0 mm
STOCK_H = 20 * IN
STOCK_T = 0.75 * IN          # 19.05 mm
DEPTH = 0.165 * IN           # 4.191 mm
TOOL_DIA = 0.125 * IN        # 1/8" end mill (assumed)
STEPOVER = 0.4 * TOOL_DIA
PASSES = 2                   # depth passes
TEXT_WIDTH = 12 * IN         # label width across the board
Z_RAPID = 32.385             # same safe height the Tankside program uses
Z_CLEAR = STOCK_T + 0.125 * IN
F_PLUNGE = 1270.0            # 50 ipm
F_CUT = 3810.0               # 150 ipm
RES = 0.1                    # mm per pixel for the glyph raster
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

Z_BOTTOM = STOCK_T - DEPTH
tool_r_px = int(round(TOOL_DIA / 2 / RES))

# ------------------------------------------------------------------ raster the text
font = ImageFont.truetype(FONT, 400)
l, t, r, b = font.getbbox(TEXT)
scale = (TEXT_WIDTH / RES) / (r - l)
font = ImageFont.truetype(FONT, int(400 * scale))
l, t, r, b = font.getbbox(TEXT)
pad = tool_r_px * 2 + 4
W, H = (r - l) + 2 * pad, (b - t) + 2 * pad
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).text((pad - l, pad - t), TEXT, fill=255, font=font)
mask = mask.point(lambda v: 255 if v >= 128 else 0)

# erode by the tool radius with a true disk: block out a circle around every boundary pixel
edges = mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v else 0)
block = Image.new("L", (W, H), 0)
bd = ImageDraw.Draw(block)
ed = edges.load()
for y in range(H):
    for x in range(W):
        if ed[x, y]:
            bd.ellipse([x - tool_r_px, y - tool_r_px, x + tool_r_px, y + tool_r_px], fill=255)
eroded = Image.composite(Image.new("L", (W, H), 0), mask, block)
px = eroded.load()

# raster pixel -> machine mm, text centred on the board
text_w_mm, text_h_mm = (r - l) * RES, (b - t) * RES
ox = STOCK_W / 2 - text_w_mm / 2 - pad * RES
oy = STOCK_H / 2 + text_h_mm / 2 + pad * RES


def M(x, y):
    return (ox + x * RES, oy - y * RES)


# ------------------------------------------------------------------ scanline pocket fill
step_px = max(1, int(round(STEPOVER / RES)))
rows = []
for y in range(tool_r_px, H, step_px):
    runs, x = [], 0
    while x < W:
        if px[x, y]:
            x0 = x
            while x < W and px[x, y]:
                x += 1
            runs.append((x0, x - 1, y))
        else:
            x += 1
    rows.append(runs)

chains, used = [], set()
for ri, runs in enumerate(rows):
    for k, run in enumerate(runs):
        if (ri, k) in used:
            continue
        used.add((ri, k))
        chain, cur, r2 = [run], run, ri
        while r2 + 1 < len(rows):
            nxt = [(kk, rr) for kk, rr in enumerate(rows[r2 + 1])
                   if (r2 + 1, kk) not in used and rr[0] <= cur[1] and rr[1] >= cur[0]]
            if not nxt:
                break
            kk, rr = min(nxt, key=lambda t: abs((t[1][0] + t[1][1]) - (cur[0] + cur[1])))
            used.add((r2 + 1, kk))
            chain.append(rr)
            cur, r2 = rr, r2 + 1
        chains.append(chain)

fill_paths = []
for chain in chains:
    pts, flip = [], False
    for x0, x1, y in chain:
        a, b2 = (x1, x0) if flip else (x0, x1)
        pts += [M(a, y), M(b2, y)]
        flip = not flip
    fill_paths.append(pts)

# ------------------------------------------------------------------ wall pass: trace the eroded outline
# marching squares on pixel centres -> closed loops
segs = {}
def val(x, y):
    return 1 if 0 <= x < W and 0 <= y < H and px[x, y] else 0
for y in range(-1, H):
    for x in range(-1, W):
        a, b2, c, d = val(x, y), val(x + 1, y), val(x + 1, y + 1), val(x, y + 1)
        code = a * 8 + b2 * 4 + c * 2 + d
        if code in (0, 15):
            continue
        top, right, bottom, left = (x + 0.5, y), (x + 1, y + 0.5), (x + 0.5, y + 1), (x, y + 0.5)
        table = {1: [(left, bottom)], 2: [(bottom, right)], 3: [(left, right)], 4: [(right, top)],
                 5: [(left, top), (right, bottom)], 6: [(bottom, top)], 7: [(left, top)],
                 8: [(top, left)], 9: [(top, bottom)], 10: [(top, right), (bottom, left)],
                 11: [(top, right)], 12: [(right, left)], 13: [(right, bottom)], 14: [(bottom, left)]}
        for p, q in table[code]:
            segs.setdefault(p, []).append(q)
            segs.setdefault(q, []).append(p)

loops = []
while segs:
    start = next(iter(segs))
    loop, cur = [start], start
    while True:
        nxts = segs.get(cur)
        if not nxts:
            break
        nxt = nxts.pop()
        if not nxts:
            del segs[cur]
        back = segs.get(nxt)
        if back is not None and cur in back:
            back.remove(cur)
            if not back:
                del segs[nxt]
        loop.append(nxt)
        cur = nxt
        if cur == start:
            break
    loops.append(loop)


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1e-9
    imax, dmax = 0, 0.0
    for i in range(1, len(pts) - 1):
        d = abs(dy * (pts[i][0] - x0) - dx * (pts[i][1] - y0)) / L
        if d > dmax:
            imax, dmax = i, d
    if dmax > eps:
        return rdp(pts[:imax + 1], eps)[:-1] + rdp(pts[imax:], eps)
    return [pts[0], pts[-1]]


wall_paths = []
for loop in loops:
    mm = [M(x, y) for x, y in loop]
    mid = len(mm) // 2
    mm = rdp(mm[:mid + 1], 0.03)[:-1] + rdp(mm[mid:], 0.03)
    if len(mm) >= 3:
        wall_paths.append(mm)

# ------------------------------------------------------------------ emit G-code
lines, n = [], [0]
def emit(s):
    n[0] += 10
    lines.append(f"N{n[0]}{s}")

def fmt(v):
    return f"{v:.3f}"

emit("M03")
lines.append(f"({TEXT.upper()} LABEL {DEPTH / IN:.3f}IN DEEP)")
emit(f"G0X{fmt(STOCK_W / 2)}Y{fmt(STOCK_H / 2)}Z{fmt(Z_RAPID)}")
emit(f"G0Z{fmt(Z_CLEAR)}")

def cut_path(pts, z):
    (x, y) = pts[0]
    emit(f"G0X{fmt(x)}Y{fmt(y)}")
    emit(f"G1Z{fmt(z)}F{F_PLUNGE:.1f}")
    first = True
    for (x, y) in pts[1:]:
        emit(f"G1X{fmt(x)}Y{fmt(y)}" + (f"F{F_CUT:.1f}" if first else ""))
        first = False
    emit(f"G0Z{fmt(Z_CLEAR)}")

for p in range(1, PASSES + 1):
    z = STOCK_T - DEPTH * p / PASSES
    lines.append(f"(PASS {p} Z{fmt(z)})")
    for pts in fill_paths:
        cut_path(pts, z)
    for pts in wall_paths:
        cut_path(pts, z)

emit(f"G0Z{fmt(Z_RAPID)}")
emit("M05")
emit("M30")
lines.append("%")

name = TEXT.replace(" ", "_")
with open(f"{OUT}/{name}.MMG", "w", newline="") as fh:
    fh.write("\r\n".join(lines) + "\r\n")

# ------------------------------------------------------------------ preview picture
S = 4.0  # px per mm
PW, PH = int(STOCK_W * S) + 260, int(STOCK_H * S) + 200
img = Image.new("RGB", (PW, PH), (236, 238, 241))
d = ImageDraw.Draw(img)
bx, by = 100, 110
def P(x, y):
    return (bx + x * S, by + (STOCK_H - y) * S)
d.rectangle([P(0, STOCK_H), P(STOCK_W, 0)], fill=(222, 184, 135), outline=(120, 86, 50), width=3)
for paths in (fill_paths, wall_paths):
    for pts in paths:
        pp = [P(*q) for q in pts]
        d.line(pp, fill=(128, 92, 52), width=int(TOOL_DIA * S), joint="curve")
        for (ax, ay) in (pp[0], pp[-1]):
            rr = TOOL_DIA * S / 2
            d.ellipse([ax - rr, ay - rr, ax + rr, ay + rr], fill=(128, 92, 52))

f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
d.text((bx, 24), f"{name}.MMG  -  engraved label, top view", fill=(40, 40, 45), font=f1)
d.text((bx, 66), f"stock 20 x 20 x 0.75 in  |  text pocketed {DEPTH / IN:.3f} in deep in {PASSES} passes  |  "
       f"tool 1/8 in end mill (assumed)  |  text {text_w_mm / IN:.1f} x {text_h_mm / IN:.1f} in, centred",
       fill=(40, 40, 45), font=f2)
# dimension lines
y0 = P(0, 0)[1] + 30
d.line([(bx, y0), (bx + STOCK_W * S, y0)], fill=(40, 40, 45), width=2)
d.text((bx + STOCK_W * S / 2 - 40, y0 + 6), "20.0 in", fill=(40, 40, 45), font=f2)
x0 = bx + STOCK_W * S + 30
d.line([(x0, by), (x0, by + STOCK_H * S)], fill=(40, 40, 45), width=2)
d.text((x0 + 8, by + STOCK_H * S / 2 - 14), "20.0 in", fill=(40, 40, 45), font=f2)
img.save(f"{OUT}/{name}.png", optimize=True)

total_len = sum(math.dist(p[i], p[i + 1]) for paths in (fill_paths, wall_paths) for p in paths for i in range(len(p) - 1))
print(f"text {text_w_mm:.1f} x {text_h_mm:.1f} mm, Z bottom {Z_BOTTOM:.3f}, {len(fill_paths)} fill chains, "
      f"{len(wall_paths)} wall loops, {len(lines)} lines, cut length/pass {total_len / 1000:.1f} m")
