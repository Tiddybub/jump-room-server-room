#!/usr/bin/env python3
"""Generate an engraved-text label program (Tankside.MMG style G-code) and a preview picture.

Units: millimetres (the Tankside.MMG sample is metric), Z0 = bottom of stock / spoilboard.
Usage: python3 make_label.py "hello world" out_dir

Smooth-running version:
  * fill scans along Y (down the letter stems) so runs are long and reversals are few
  * wall pass is fitted to G2/G3 arcs and long lines instead of thousands of 0.1 mm segments
  * one full-depth pass, 50% stepover, nearest-neighbour ordering -> about half the cut time
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TEXT = sys.argv[1] if len(sys.argv) > 1 else "hello world"
OUT = sys.argv[2] if len(sys.argv) > 2 else "."

IN = 25.4
STOCK_W = 20 * IN            # 508.0 mm
STOCK_H = 20 * IN
STOCK_T = 18.0               # 18 mm (0.71 in) stock
DEPTH = 0.165 * IN           # 4.191 mm
TOOL_DIA = 0.125 * IN        # 1/8" end mill (assumed)
STEPOVER = 0.5 * TOOL_DIA
PASSES = 1                   # depth passes (full depth in one pass)
TEXT_WIDTH = 12 * IN         # label width across the board
Z_RAPID = 32.385             # same safe height the Tankside program uses
Z_CLEAR = STOCK_T + 0.125 * IN
F_PLUNGE = 1270.0            # 50 ipm
F_CUT = 3810.0               # 150 ipm
RES = 0.1                    # mm per pixel for the glyph raster
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LINE_TOL = 0.06              # mm, polyline simplification
ARC_TOL = 0.08               # mm, arc fitting
SMOOTH = 4                   # +/- points of moving average on the raw raster contour

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


# ------------------------------------------------------------------ pocket fill: scan along Y (down the stems)
step_px = max(1, int(round(STEPOVER / RES)))
cols = []
for x in range(tool_r_px, W, step_px):
    runs, y = [], 0
    while y < H:
        if px[x, y]:
            y0 = y
            while y < H and px[x, y]:
                y += 1
            runs.append((y0, y - 1, x))
        else:
            y += 1
    cols.append(runs)

chains, used = [], set()
for ci, runs in enumerate(cols):
    for k, run in enumerate(runs):
        if (ci, k) in used:
            continue
        used.add((ci, k))
        chain, cur, c2 = [run], run, ci
        while c2 + 1 < len(cols):
            nxt = [(kk, rr) for kk, rr in enumerate(cols[c2 + 1])
                   if (c2 + 1, kk) not in used and rr[0] <= cur[1] and rr[1] >= cur[0]]
            if not nxt:
                break
            kk, rr = min(nxt, key=lambda t: abs((t[1][0] + t[1][1]) - (cur[0] + cur[1])))
            used.add((c2 + 1, kk))
            chain.append(rr)
            cur, c2 = rr, c2 + 1
        chains.append(chain)

fill_paths = []
for chain in chains:
    pts, flip = [], False
    for y0, y1, x in chain:
        a, b2 = (y1, y0) if flip else (y0, y1)
        pts += [M(x, a), M(x, b2)]
        flip = not flip
    fill_paths.append(pts)

# ------------------------------------------------------------------ wall pass: trace the eroded outline
segs = {}


def val(x, y):
    return 1 if 0 <= x < W and 0 <= y < H and px[x, y] else 0


TABLE = {1: [("l", "b")], 2: [("b", "r")], 3: [("l", "r")], 4: [("r", "t")],
         5: [("l", "t"), ("r", "b")], 6: [("b", "t")], 7: [("l", "t")],
         8: [("t", "l")], 9: [("t", "b")], 10: [("t", "r"), ("b", "l")],
         11: [("t", "r")], 12: [("r", "l")], 13: [("r", "b")], 14: [("b", "l")]}
for y in range(-1, H):
    for x in range(-1, W):
        a, b2, c, d = val(x, y), val(x + 1, y), val(x + 1, y + 1), val(x, y + 1)
        code = a * 8 + b2 * 4 + c * 2 + d
        if code in (0, 15):
            continue
        side = {"t": (x + 0.5, y), "r": (x + 1, y + 0.5), "b": (x + 0.5, y + 1), "l": (x, y + 0.5)}
        for p, q in TABLE[code]:
            P1, Q1 = side[p], side[q]
            segs.setdefault(P1, []).append(Q1)
            segs.setdefault(Q1, []).append(P1)

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


def circle3(p, q, s):
    ax, ay = p
    bx, by = q
    cx, cy = s
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy, math.hypot(ax - ux, ay - uy))


def arc_ok(pts, i, j, tol):
    """Circle through pts[i], middle, pts[j]; valid if all points sit on it and sweep is monotonic."""
    c = circle3(pts[i], pts[(i + j) // 2], pts[j])
    if c is None:
        return None
    cx, cy, rad = c
    if rad < 0.4 or rad > 300:
        return None
    for k in range(i, j + 1):
        if abs(math.hypot(pts[k][0] - cx, pts[k][1] - cy) - rad) > tol:
            return None
    sweep, sign = 0.0, 0
    for k in range(i, j):
        a0 = math.atan2(pts[k][1] - cy, pts[k][0] - cx)
        a1 = math.atan2(pts[k + 1][1] - cy, pts[k + 1][0] - cx)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        if abs(da) < 1e-9:
            return None
        s = 1 if da > 0 else -1
        if sign and s != sign:
            return None
        sign = s
        sweep += da
    if abs(sweep) > 1.9 * math.pi:
        return None
    return (cx, cy, sign)  # sign +1 = CCW (G3) in a Y-up frame


def fit_moves(pts, tol):
    """Return list of moves: ('L', x, y) or ('A', x, y, i, j, cw) from a polyline."""
    moves, i, n = [], 0, len(pts)
    while i < n - 1:
        best = None
        j = i + 2
        while j < n:
            res = arc_ok(pts, i, j, tol)
            if res is None:
                break
            best = (j, res)
            j += 1
        if best and best[0] >= i + 3:
            j, (cx, cy, sign) = best
            moves.append(("A", pts[j][0], pts[j][1], cx - pts[i][0], cy - pts[i][1], sign < 0))
            i = j
        else:
            moves.append(("L", pts[i + 1][0], pts[i + 1][1]))
            i += 1
    return moves


def smooth_loop(pts, k):
    """Circular moving average to take the raster staircase out of the contour."""
    if len(pts) < 2 * k + 3:
        return pts
    core = pts[:-1] if pts[0] == pts[-1] else pts
    n = len(core)
    out = []
    for i in range(n):
        sx = sy = 0.0
        for o in range(-k, k + 1):
            qx, qy = core[(i + o) % n]
            sx += qx
            sy += qy
        out.append((sx / (2 * k + 1), sy / (2 * k + 1)))
    out.append(out[0])
    return out


wall_paths = []
for loop in loops:
    mm = [M(x, y) for x, y in smooth_loop(loop, SMOOTH)]
    mid = len(mm) // 2
    mm = rdp(mm[:mid + 1], LINE_TOL)[:-1] + rdp(mm[mid:], LINE_TOL)
    if len(mm) >= 3:
        wall_paths.append(mm)

# ------------------------------------------------------------------ order everything nearest-neighbour
jobs = [("fill", p) for p in fill_paths] + [("wall", p) for p in wall_paths]
ordered, cur = [], (STOCK_W / 2, STOCK_H / 2)
while jobs:
    k = min(range(len(jobs)), key=lambda q: math.dist(cur, jobs[q][1][0]))
    kind, pts = jobs.pop(k)
    ordered.append((kind, pts))
    cur = pts[-1]

# ------------------------------------------------------------------ emit G-code
lines, n = [], [0]


def emit(s):
    n[0] += 10
    lines.append(f"N{n[0]}{s}")


def fmt(v):
    return f"{v:.3f}"


cut_len, n_plunge, n_arcs, n_lines_out = 0.0, 0, 0, 0
emit("M03")
lines.append(f"({TEXT.upper()} LABEL {DEPTH / IN:.3f}IN DEEP)")
emit(f"G0X{fmt(STOCK_W / 2)}Y{fmt(STOCK_H / 2)}Z{fmt(Z_RAPID)}")
emit(f"G0Z{fmt(Z_CLEAR)}")

for p in range(1, PASSES + 1):
    z = STOCK_T - DEPTH * p / PASSES
    lines.append(f"(PASS {p} Z{fmt(z)})")
    for kind, pts in ordered:
        (x, y) = pts[0]
        emit(f"G0X{fmt(x)}Y{fmt(y)}")
        emit(f"G1Z{fmt(z)}F{F_PLUNGE:.1f}")
        n_plunge += 1
        feed = f"F{F_CUT:.1f}"
        if kind == "wall":
            moves = fit_moves(pts, ARC_TOL)
        else:
            moves = [("L", q[0], q[1]) for q in pts[1:]]
        last = pts[0]
        for mv in moves:
            if mv[0] == "L":
                emit(f"G1X{fmt(mv[1])}Y{fmt(mv[2])}{feed}")
                cut_len += math.dist(last, (mv[1], mv[2]))
                n_lines_out += 1
            else:
                _, ex, ey, ii, jj, cw = mv
                emit(f"{'G2' if cw else 'G3'}X{fmt(ex)}Y{fmt(ey)}I{fmt(ii)}J{fmt(jj)}{feed}")
                rad = math.hypot(ii, jj)
                a0 = math.atan2(-jj, -ii)
                a1 = math.atan2(ey - (last[1] + jj), ex - (last[0] + ii))
                da = (a1 - a0) % (2 * math.pi)
                if cw:
                    da = 2 * math.pi - da
                cut_len += rad * da
                n_arcs += 1
            last = (mv[1], mv[2])
            feed = ""
        emit(f"G0Z{fmt(Z_CLEAR)}")

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
for kind, pts in ordered:
    pp = [P(*q) for q in pts]
    d.line(pp, fill=(128, 92, 52), width=int(TOOL_DIA * S), joint="curve")
    for (ax, ay) in (pp[0], pp[-1]):
        rr = TOOL_DIA * S / 2
        d.ellipse([ax - rr, ay - rr, ax + rr, ay + rr], fill=(128, 92, 52))

est_min = cut_len / F_CUT + n_plunge * ((Z_CLEAR - Z_BOTTOM) / F_PLUNGE + 0.02)
f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
d.text((bx, 24), f"{name}.MMG  -  engraved label, top view", fill=(40, 40, 45), font=f1)
d.text((bx, 66), f"stock 20 x 20 in x 18 mm (0.71 in)  |  text pocketed {DEPTH / IN:.3f} in deep in {PASSES} pass  |  "
       f"tool 1/8 in end mill (assumed)  |  text {text_w_mm / IN:.1f} x {text_h_mm / IN:.1f} in, centred  |  "
       f"~{est_min:.1f} min cutting",
       fill=(40, 40, 45), font=f2)
y0 = P(0, 0)[1] + 30
d.line([(bx, y0), (bx + STOCK_W * S, y0)], fill=(40, 40, 45), width=2)
d.text((bx + STOCK_W * S / 2 - 40, y0 + 6), "20.0 in", fill=(40, 40, 45), font=f2)
x0 = bx + STOCK_W * S + 30
d.line([(x0, by), (x0, by + STOCK_H * S)], fill=(40, 40, 45), width=2)
d.text((x0 + 8, by + STOCK_H * S / 2 - 14), "20.0 in", fill=(40, 40, 45), font=f2)
img.save(f"{OUT}/{name}.png", optimize=True)

print(f"text {text_w_mm:.1f} x {text_h_mm:.1f} mm, Z bottom {Z_BOTTOM:.3f}, {len(fill_paths)} fill chains, "
      f"{len(wall_paths)} wall loops, {len(lines)} lines, {n_lines_out} G1 + {n_arcs} arcs, "
      f"{n_plunge} plunges, cut length {cut_len / 1000:.2f} m, ~{est_min:.1f} min at feed")
