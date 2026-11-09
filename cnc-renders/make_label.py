#!/usr/bin/env python3
"""Generate an engraved-text label program (Tankside.MMG style G-code) and a verified preview.

Units: millimetres, Z0 = bottom of stock / spoilboard.
Usage: python3 make_label.py "hello world" out_dir [font_file]

Toolpath:
  * tool-centre region = letters shrunk by exactly the tool radius, so the bit never leaves the letter
  * fill runs down the stems (long strokes); a link between strokes is only made if it stays
    inside that region, otherwise the tool lifts
  * wall pass follows the true letter edge, written as G2/G3 arcs and long lines; every fitted
    move is checked against the dense traced edge (FIT_TOL) so straight edges cannot bulge
  * after writing, verify_label.py sweeps the bit along the program and compares the cut with the
    font; the run fails if anything is cut outside the letters by more than MAX_OVERCUT
"""
import math
import os
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = sys.argv[1] if len(sys.argv) > 1 else "hello world"
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
FONT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, "fonts", "PirataOne.woff")
FONT_NAME = os.path.splitext(os.path.basename(FONT))[0]

IN = 25.4
STOCK_W = 20 * IN            # 508.0 mm
STOCK_H = 20 * IN
STOCK_T = 0.71 * IN          # 18.034 mm Baltic birch
DEPTH = 0.165 * IN           # 4.191 mm
TOOL_DIA = 6.0               # 6 mm compression bit
STEPOVER = 0.5 * TOOL_DIA
PASSES = 1                   # full 0.165 in in one pass: compression bit needs its down-cut flutes at the top face for clean edges
TEXT_WIDTH = 12 * IN         # label width across the board (font size is set from this; do not change)
Z_RAPID = 32.385             # same safe height the Tankside program uses
Z_CLEAR = STOCK_T + 0.125 * IN
F_PLUNGE = 1270.0            # 50 ipm
F_CUT = 3810.0               # 150 ipm
RES = 0.05                   # mm per pixel for the toolpath raster
FIT_TOL = 0.02               # mm, max distance between a fitted line/arc and the traced edge
MAX_OVERCUT = 0.10           # mm, verification limit

Z_BOTTOM = STOCK_T - DEPTH
R_TOOL = TOOL_DIA / 2

# ------------------------------------------------------------------ letters (same sizing as every earlier version)
font = ImageFont.truetype(FONT, 400)
l, t, r, b = font.getbbox(TEXT)
scale = (TEXT_WIDTH / 0.1) / (r - l)
size01 = int(400 * scale)                       # font size at 0.1 mm/px; text size is fixed by this
font = ImageFont.truetype(FONT, size01)
l, t, r, b = font.getbbox(TEXT)
text_w_mm, text_h_mm = (r - l) * 0.1, (b - t) * 0.1
fontR = ImageFont.truetype(FONT, int(round(size01 * 0.1 / RES)))
lR, tR, rR, bR = fontR.getbbox(TEXT)
pad = int(R_TOOL / RES) + 20
W, H = (rR - lR) + 2 * pad, (bR - tR) + 2 * pad
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).text((pad - lR, pad - tR), TEXT, fill=255, font=fontR)
mask = mask.point(lambda v: 255 if v >= 128 else 0)

x_left = STOCK_W / 2 - text_w_mm / 2
y_top = STOCK_H / 2 + text_h_mm / 2


def M(x, y):
    """raster pixel (centre = integer) -> machine mm, Y up"""
    return (x_left + (x - pad) * RES, y_top - (y - pad) * RES)


# ------------------------------------------------------------------ tool-centre region: letter shrunk by the tool radius
# A pixel may hold the tool centre only if no background pixel centre is within R + half a pixel.
bg_edge = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(3)), mask)
block = Image.new("L", (W, H), 0)
bd = ImageDraw.Draw(block)
rr = R_TOOL / RES + 1.5          # +1 px safety margin
data = bg_edge.tobytes()
i = data.find(b"\xff")
while i >= 0:
    x, y = i % W, i // W
    bd.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)
    i = data.find(b"\xff", i + 1)
eroded = ImageChops.subtract(mask, block)
px = eroded.load()


def inside(x, y):
    xi, yi = int(round(x)), int(round(y))
    return 0 <= xi < W and 0 <= yi < H and px[xi, yi] == 255


def segment_inside(p, q):
    n = int(math.dist(p, q)) + 1
    return all(inside(p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(n + 1))


# ------------------------------------------------------------------ fill: strokes down the stems
step_px = max(1, int(round(STEPOVER / RES)))
cols = []
for x in range(pad, W - pad, step_px):
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

fill_paths, used = [], set()
for ci, runs in enumerate(cols):
    for k, run in enumerate(runs):
        if (ci, k) in used:
            continue
        used.add((ci, k))
        pts = [(run[2], run[0]), (run[2], run[1])]
        cur, c2 = run, ci
        while c2 + 1 < len(cols):
            best = None
            for kk, rr2 in enumerate(cols[c2 + 1]):
                if (c2 + 1, kk) in used or rr2[0] > cur[1] or rr2[1] < cur[0]:
                    continue
                end = pts[-1]
                # start the next stroke at the end nearest to where we are
                a, b2 = (rr2[0], rr2[1]) if abs(rr2[0] - end[1]) <= abs(rr2[1] - end[1]) else (rr2[1], rr2[0])
                if segment_inside(end, (rr2[2], a)):
                    best = (kk, rr2, a, b2)
                    break
            if best is None:
                break
            kk, rr2, a, b2 = best
            used.add((c2 + 1, kk))
            pts += [(rr2[2], a), (rr2[2], b2)]
            cur, c2 = rr2, c2 + 1
        fill_paths.append([M(*p) for p in pts])

# ------------------------------------------------------------------ wall: trace the edge of the tool-centre region
TABLE = {1: [("l", "b")], 2: [("b", "r")], 3: [("l", "r")], 4: [("r", "t")],
         5: [("l", "t"), ("r", "b")], 6: [("b", "t")], 7: [("l", "t")],
         8: [("t", "l")], 9: [("t", "b")], 10: [("t", "r"), ("b", "l")],
         11: [("t", "r")], 12: [("r", "l")], 13: [("r", "b")], 14: [("b", "l")]}
segs = {}
bbox = eroded.getbbox() or (0, 0, 0, 0)
for y in range(max(-1, bbox[1] - 2), min(H, bbox[3] + 2)):
    for x in range(max(-1, bbox[0] - 2), min(W, bbox[2] + 2)):
        a = 1 if (0 <= x < W and 0 <= y < H and px[x, y]) else 0
        b2 = 1 if (0 <= x + 1 < W and 0 <= y < H and px[x + 1, y]) else 0
        c = 1 if (0 <= x + 1 < W and 0 <= y + 1 < H and px[x + 1, y + 1]) else 0
        d = 1 if (0 <= x < W and 0 <= y + 1 < H and px[x, y + 1]) else 0
        code = a * 8 + b2 * 4 + c * 2 + d
        if code in (0, 15):
            continue
        side = {"t": (x + 0.5, y), "r": (x + 1, y + 0.5), "b": (x + 0.5, y + 1), "l": (x, y + 0.5)}
        for p, q in TABLE[code]:
            segs.setdefault(side[p], []).append(side[q])
            segs.setdefault(side[q], []).append(side[p])

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
    if len(loop) > 8:
        loops.append(loop)


def smooth(loop, k=2):
    core = loop[:-1] if loop[0] == loop[-1] else loop
    n = len(core)
    out = []
    for i in range(n):
        sx = sum(core[(i + o) % n][0] for o in range(-k, k + 1))
        sy = sum(core[(i + o) % n][1] for o in range(-k, k + 1))
        out.append((sx / (2 * k + 1), sy / (2 * k + 1)))
    return out + [out[0]]


def line_fits(P, i, j):
    (x0, y0), (x1, y1) = P[i], P[j]
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return False
    for k in range(i + 1, j):
        t_ = max(0.0, min(1.0, ((P[k][0] - x0) * dx + (P[k][1] - y0) * dy) / L2))
        if math.hypot(P[k][0] - x0 - t_ * dx, P[k][1] - y0 - t_ * dy) > FIT_TOL:
            return False
    return True


def circle3(p, q, s):
    ax, ay = p
    bx, by = q
    cx, cy = s
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def arc_fits(P, i, j):
    """Arc through P[i], P[mid], P[j]; every dense point between must lie within FIT_TOL of it,
    in order, all turning the same way. Returns (cx, cy, ccw) or None."""
    c = circle3(P[i], P[(i + j) // 2], P[j])
    if c is None:
        return None
    cx, cy, rad = c
    if rad < 0.2 or rad > 2000:
        return None
    sweep, sign = 0.0, 0
    prev = math.atan2(P[i][1] - cy, P[i][0] - cx)
    for k in range(i + 1, j + 1):
        if abs(math.hypot(P[k][0] - cx, P[k][1] - cy) - rad) > FIT_TOL:
            return None
        ang = math.atan2(P[k][1] - cy, P[k][0] - cx)
        da = (ang - prev + math.pi) % (2 * math.pi) - math.pi
        prev = ang
        if abs(da) < 1e-12:
            continue
        s = 1 if da > 0 else -1
        if sign and s != sign:
            return None
        sign = s
        sweep += da
    if sign == 0 or abs(sweep) > 1.8 * math.pi:
        return None
    return cx, cy, sign > 0


def furthest(P, i, ok, lo):
    """largest j >= lo with ok(j); grows by doubling then bisects"""
    n = len(P) - 1
    if lo > n or not ok(lo):
        return None
    good, step = lo, 1
    while good + step <= n and ok(good + step):
        good += step
        step *= 2
    bad = min(n + 1, good + step)
    while bad - good > 1:
        mid = (good + bad) // 2
        if ok(mid):
            good = mid
        else:
            bad = mid
    return good


def fit(P):
    moves, i, n = [], 0, len(P) - 1
    while i < n:
        jl = furthest(P, i, lambda j: line_fits(P, i, j), i + 1) or i + 1
        ja = furthest(P, i, lambda j: arc_fits(P, i, j) is not None, i + 4) if i + 4 <= n else None
        if ja and ja > jl:
            cx, cy, ccw = arc_fits(P, i, ja)
            moves.append(("A", P[ja][0], P[ja][1], cx - P[i][0], cy - P[i][1], not ccw))
            i = ja
        else:
            moves.append(("L", P[jl][0], P[jl][1]))
            i = jl
    return moves


wall_paths = []
for loop in loops:
    P = [M(x, y) for x, y in smooth(loop)]
    wall_paths.append((P, fit(P)))


def bbox_mm(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# a wall loop with no fill stroke inside it is cut at every depth pass (never full depth in one go)
fill_pts = [p for path in fill_paths for p in path]
orphan = []
for P, _ in wall_paths:
    x0, y0, x1, y1 = bbox_mm(P)
    orphan.append(not any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in fill_pts))


# ------------------------------------------------------------------ order: nearest neighbour
def order(jobs):
    out, cur = [], (STOCK_W / 2, STOCK_H / 2)
    jobs = list(jobs)
    while jobs:
        k = min(range(len(jobs)), key=lambda q: math.dist(cur, jobs[q][1]))
        job = jobs.pop(k)
        out.append(job)
        cur = job[2]
    return out


# ------------------------------------------------------------------ emit G-code
lines, nno = [], [0]


def emit(s):
    nno[0] += 10
    lines.append(f"N{nno[0]}{s}")


def fmt(v):
    return f"{v:.3f}"


cut_len, n_plunge = 0.0, 0
emit("M03")
lines.append(f"({TEXT.upper()} LABEL {DEPTH / IN:.3f}IN DEEP IN 0.71IN BALTIC BIRCH 6MM COMPRESSION BIT, SINGLE PASS)")
emit(f"G0X{fmt(STOCK_W / 2)}Y{fmt(STOCK_H / 2)}Z{fmt(Z_RAPID)}")
emit(f"G0Z{fmt(Z_CLEAR)}")

for p in range(1, PASSES + 1):
    z = STOCK_T - DEPTH * p / PASSES
    lines.append(f"(PASS {p} Z{fmt(z)})")
    jobs = [("fill", pts[0], pts[-1], [("L", q[0], q[1]) for q in pts[1:]]) for pts in fill_paths]
    for (P, mv), orph in zip(wall_paths, orphan):
        if p == PASSES or orph:
            jobs.append(("wall", P[0], P[-1], mv))
    for kind, start, end, moves in order(jobs):
        emit(f"G0X{fmt(start[0])}Y{fmt(start[1])}")
        emit(f"G1Z{fmt(z)}F{F_PLUNGE:.1f}")
        n_plunge += 1
        feed, last = f"F{F_CUT:.1f}", start
        for mv in moves:
            if mv[0] == "L":
                emit(f"G1X{fmt(mv[1])}Y{fmt(mv[2])}{feed}")
                cut_len += math.dist(last, (mv[1], mv[2]))
            else:
                _, ex, ey, ii, jj, cw = mv
                emit(f"{'G2' if cw else 'G3'}X{fmt(ex)}Y{fmt(ey)}I{fmt(ii)}J{fmt(jj)}{feed}")
                cx, cy = last[0] + ii, last[1] + jj
                a0, a1 = math.atan2(last[1] - cy, last[0] - cx), math.atan2(ey - cy, ex - cx)
                da = (a1 - a0) % (2 * math.pi)
                cut_len += math.hypot(ii, jj) * ((2 * math.pi - da) if cw else da)
            last, feed = (mv[1], mv[2]), ""
        emit(f"G0Z{fmt(Z_CLEAR)}")

emit(f"G0Z{fmt(Z_RAPID)}")
emit("M05")
emit("M30")
lines.append("%")

name = TEXT.replace(" ", "_")
prog = os.path.join(OUT, f"{name}.MMG")
with open(prog, "w", newline="") as fh:
    fh.write("\r\n".join(lines) + "\r\n")

est_min = cut_len / F_CUT + n_plunge * ((Z_CLEAR - Z_BOTTOM) / F_PLUNGE + 0.02)
print(f"text {text_w_mm:.1f} x {text_h_mm:.1f} mm, Z bottom {Z_BOTTOM:.3f}, {len(fill_paths)} fill strokes, "
      f"{len(wall_paths)} wall loops ({sum(orphan)} cut every pass), {len(lines)} lines, "
      f"{n_plunge} plunges, cut length {cut_len / 1000:.2f} m, ~{est_min:.1f} min at feed")

# ------------------------------------------------------------------ verify against the font, build preview from the verified sweep
sweep_png = os.path.join(OUT, f".{name}_verify.png")
res = subprocess.run([sys.executable, "-I", os.path.join(HERE, "verify_label.py"), prog, TEXT, FONT,
                      str(TOOL_DIA), str(STOCK_T), sweep_png], capture_output=True, text=True)
print("verify:", res.stdout.strip() or res.stderr.strip())
max_over = float(res.stdout.split("max overcut")[1].split("mm")[0]) if "max overcut" in res.stdout else 99.0
coverage = res.stdout.split("coverage")[1].split("%")[0].strip() if "coverage" in res.stdout else "?"

S = 4.0  # preview px per mm
PW, PH = int(STOCK_W * S) + 260, int(STOCK_H * S) + 300
img = Image.new("RGB", (PW, PH), (236, 238, 241))
d = ImageDraw.Draw(img)
bx, by = 100, 110
d.rectangle([bx, by, bx + STOCK_W * S, by + STOCK_H * S], fill=(222, 184, 135), outline=(120, 86, 50), width=3)
if os.path.exists(sweep_png):
    sw = Image.open(sweep_png)
    k = 0.05 * S                                         # verify image is 0.05 mm/px with a 10 mm pad
    sw = sw.resize((int(sw.width * k), int(sw.height * k)), Image.LANCZOS)
    img.paste(sw, (int(bx + (x_left - 10) * S), int(by + (STOCK_H - y_top - 10) * S)))
    os.remove(sweep_png)

f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
INK = (40, 40, 45)
d.text((bx, 24), f"{name}.MMG  -  engraved label, top view (simulated from the program)", fill=INK, font=f1)
d.text((bx, 66), f"stock 20 x 20 x 0.71 in Baltic birch  |  {DEPTH / IN:.3f} in deep, {PASSES} pass{'es' if PASSES > 1 else ''}  |  "
       f"font {FONT_NAME}  |  6 mm compression bit  |  text {text_w_mm / IN:.1f} x {text_h_mm / IN:.1f} in, centred  |  "
       f"~{est_min:.1f} min", fill=INK, font=f2)
y0 = by + STOCK_H * S + 30
d.line([(bx, y0), (bx + STOCK_W * S, y0)], fill=INK, width=2)
d.text((bx + STOCK_W * S / 2 - 40, y0 + 6), "20.0 in", fill=INK, font=f2)
x0 = bx + STOCK_W * S + 30
d.line([(x0, by), (x0, by + STOCK_H * S)], fill=INK, width=2)
d.text((x0 + 8, by + STOCK_H * S / 2 - 14), "20.0 in", fill=INK, font=f2)
ly = y0 + 50
for col, txt in [((128, 92, 52), f"cut by the program ({coverage}% of the letter area)"),
                 ((70, 120, 200), "letter detail finer than a 6 mm bit can reach (left uncut)"),
                 ((220, 30, 30), f"cut outside the letters (max {max_over:.2f} mm)")]:
    d.rectangle([bx, ly, bx + 26, ly + 22], fill=col, outline=INK)
    d.text((bx + 36, ly - 2), txt, fill=INK, font=f2)
    ly += 34
img.save(os.path.join(OUT, f"{name}.png"), optimize=True)

if max_over > MAX_OVERCUT:
    sys.exit(f"FAILED: program cuts {max_over:.2f} mm outside the letters (limit {MAX_OVERCUT} mm)")
print("PASS: nothing cut outside the letters beyond", MAX_OVERCUT, "mm")
