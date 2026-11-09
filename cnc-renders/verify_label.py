#!/usr/bin/env python3
"""Check an engraved-label G-code program against the true font letters.

Reads the program, sweeps the bit along every move below the stock top, and compares the
cut area with the letter shapes rendered straight from the font file.

Usage: python3 verify_label.py PROGRAM.MMG "text" FONT_FILE TOOL_DIA_MM STOCK_T_MM [out.png]

Reports:
  overcut  - wood removed OUTSIDE the letters (the letter shape got bigger: must be ~0)
  coverage - share of the letter area that actually gets cut
"""
import math
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

PROG, TEXT, FONT = sys.argv[1], sys.argv[2], sys.argv[3]
TOOL_DIA = float(sys.argv[4])
STOCK_T = float(sys.argv[5])
OUT_PNG = sys.argv[6] if len(sys.argv) > 6 else None

IN = 25.4
STOCK_W = STOCK_H = 20 * IN
TEXT_WIDTH = 12 * IN
RES = 0.05                     # mm per pixel (finer than the generator)
PAD = int(10 / RES)

# ------------------------------------------------------------------ true letters, same placement as make_label.py
font = ImageFont.truetype(FONT, 400)
l, t, r, b = font.getbbox(TEXT)
scale = (TEXT_WIDTH / 0.1) / (r - l)            # generator sizes the font at 0.1 mm/px
font = ImageFont.truetype(FONT, int(400 * scale))
l, t, r, b = font.getbbox(TEXT)
tw, th = (r - l) * 0.1, (b - t) * 0.1           # mm
font2 = ImageFont.truetype(FONT, int(400 * scale) * 2)   # 0.05 mm/px rendering
l2, t2, r2, b2 = font2.getbbox(TEXT)
W, H = (r2 - l2) + 2 * PAD, (b2 - t2) + 2 * PAD
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).text((PAD - l2, PAD - t2), TEXT, fill=255, font=font2)
mask = mask.point(lambda v: 255 if v >= 128 else 0)
x_left = STOCK_W / 2 - tw / 2
y_top = STOCK_H / 2 + th / 2


def to_px(x, y):
    return ((x - x_left) / RES + PAD, (y_top - y) / RES + PAD)


# ------------------------------------------------------------------ sweep the bit along the program
cut = Image.new("L", (W, H), 0)
cd = ImageDraw.Draw(cut)
rpx = TOOL_DIA / 2 / RES
x = y = z = 0.0
modal = 0
n_moves = 0
for raw in open(PROG, errors="replace"):
    line = raw.strip()
    if not line or line.startswith("(") or line == "%":
        continue
    w = {}
    for k, v in re.findall(r"([A-Z])(-?\d+\.?\d*)", line):
        w.setdefault(k, float(v))
    if "M" in w:
        continue
    if "G" in w:
        modal = int(w["G"])
    nx, ny, nz = w.get("X", x), w.get("Y", y), w.get("Z", z)
    if modal in (1, 2, 3) and min(z, nz) < STOCK_T - 0.01 and (nx, ny) != (x, y):
        if modal == 1:
            pts = [(x, y), (nx, ny)]
        else:
            cx, cy = x + w.get("I", 0.0), y + w.get("J", 0.0)
            rad = math.hypot(x - cx, y - cy)
            a0 = math.atan2(y - cy, x - cx)
            a1 = math.atan2(ny - cy, nx - cx)
            if modal == 2:
                while a1 >= a0:
                    a1 -= 2 * math.pi
            else:
                while a1 <= a0:
                    a1 += 2 * math.pi
            n = max(2, int(abs(a1 - a0) * rad / 0.05))
            pts = [(cx + rad * math.cos(a0 + (a1 - a0) * k / n), cy + rad * math.sin(a0 + (a1 - a0) * k / n))
                   for k in range(n + 1)]
        pp = [to_px(*p) for p in pts]
        cd.line(pp, fill=255, width=max(1, int(round(2 * rpx))))
        for (px_, py_) in pp:
            cd.ellipse([px_ - rpx, py_ - rpx, px_ + rpx, py_ + rpx], fill=255)
        n_moves += 1
    x, y, z = nx, ny, nz

# ------------------------------------------------------------------ compare
over = ImageChops.subtract(cut, mask)                       # cut but not letter
inside = ImageChops.multiply(cut, mask)
area_letters = mask.histogram()[255]
area_over = over.histogram()[255]
area_cut_in = inside.histogram()[255]

max_over = 0.0
if area_over:
    grown = mask
    for k in range(1, 400):
        grown = grown.filter(ImageFilter.MaxFilter(3))
        left = ImageChops.subtract(over, grown).histogram()[255]
        if left == 0:
            max_over = k * RES
            break

print(f"moves {n_moves}  coverage {100 * area_cut_in / area_letters:.1f}% of letter area  "
      f"overcut area {area_over * RES * RES:.1f} mm2  max overcut {max_over:.2f} mm")

if OUT_PNG:
    img = Image.new("RGB", (W, H), (222, 184, 135))          # untouched wood
    img.paste((128, 92, 52), mask=inside)                    # correctly cut
    img.paste((70, 120, 200), mask=ImageChops.subtract(mask, cut))   # letter the bit can't reach
    img.paste((220, 30, 30), mask=over)                      # overcut
    img.save(OUT_PNG, optimize=True)
