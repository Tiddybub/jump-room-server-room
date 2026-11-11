#!/usr/bin/env python3
"""Preview: the 48 x 96 in sheet with the job cut out on it, seen from above at the machine
(X0 Y0 zero corner bottom-left). Adds a close-up when the job uses a small part of the sheet.

usage: python3 sheet_preview.py FILE.MMG OUT.png [--tool-mm 6] [--title "..."]
"""
import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sheet import SHEET_W, SHEET_L, load, in_wood, edge_bounds, through_features, final_lap, inch, THROUGH_Z
from gcode import move_pts

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_B = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
BG = (238, 240, 243)
SCRAP = (232, 229, 196)      # sheet left over (pale, like the CAM screen)
PART = (128, 96, 52)         # cut-out parts (brown, like the CAM screen)
POCKET = (224, 145, 58)      # labels / pockets (orange, like the CAM screen)
THRU = (58, 49, 40)          # through cuts: you see the spoilboard
TAB = (224, 49, 49)          # tabs
ZERO = (25, 113, 194)        # zero corner
INK = (33, 37, 41)
MUTED = (90, 98, 108)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def depth_map(feats, top, view, res, r_tool):
    """lowest Z the bit reaches at each pixel (inf = not cut). view = (x0, y0, x1, y1) mm"""
    vx0, vy0, vx1, vy1 = view
    w, h = int(math.ceil((vx1 - vx0) * res)), int(math.ceil((vy1 - vy0) * res))
    im = Image.new('F', (w, h), 1e9)
    d = ImageDraw.Draw(im)
    rp = r_tool * res

    def px(p):
        return ((p[0] - vx0) * res, (vy1 - p[1]) * res)
    moves = sorted(in_wood(feats, top), key=lambda m: -min(m[4], m[7]))
    for m in moves:
        z = float(min(m[4], m[7]))
        pts = [px(p) for p in move_pts(m)]
        if len(pts) > 1 and pts[0] != pts[-1] or len(pts) > 2:
            d.line(pts, fill=z, width=max(1, int(round(2 * rp))))
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - rp, y - rp, x + rp, y + rp), fill=z)
    return np.array(im), px


def paint(feats, top, th, view, res, r_tool):
    zmap, px = depth_map(feats, top, view, res, r_tool)
    h, w = zmap.shape
    # part areas: fill each part outline, then cutouts inside parts, by nesting level
    region = Image.new('L', (w, h), 0)
    rd = ImageDraw.Draw(region)
    for t in sorted(th, key=lambda t: t['level']):
        pts = [px(p) for p in final_lap(t['f'])]
        if len(pts) > 2:
            rd.polygon(pts, fill=255 if t['kind'] == 'part' else 0)
    region = np.array(region) > 0
    img = np.empty((h, w, 3), np.uint8)
    img[:] = SCRAP
    img[region] = PART
    pocket = (zmap < top - 0.05) & (zmap > THROUGH_Z)
    frac = np.clip((top - zmap) / max(top, 1), 0, 1)
    for c in range(3):  # orange for shallow labels, darker the deeper it goes
        k = np.clip((frac - 0.25) / 0.75, 0, 1)
        shade = POCKET[c] * (1 - k) + THRU[c] * k
        img[..., c] = np.where(pocket, shade, img[..., c])
    img[zmap <= THROUGH_Z] = THRU
    out = Image.fromarray(img)
    d = ImageDraw.Draw(out)
    for t in th:  # tabs: solid red over the kerf
        for tb in t['tabs']:
            d.line([px(p) for p in tb['pts']], fill=TAB, width=max(2, int(round(2 * r_tool * res))))
    return out, px


def arrow(d, a, b, col, w=3):
    d.line([a, b], fill=col, width=w)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (2.6, -2.6):
        d.line([b, (b[0] - 12 * math.cos(ang + s / 6), b[1] - 12 * math.sin(ang + s / 6))], fill=col, width=w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('out')
    ap.add_argument('--tool-mm', type=float, default=6.0)
    ap.add_argument('--title')
    a = ap.parse_args()
    r = a.tool_mm / 2
    lines, feats, top = load(a.file)
    th = through_features(feats, top)
    parts = [t for t in th if t['kind'] == 'part']
    ntabs = sum(len(t['tabs']) for t in parts)
    ex0, ey0, ex1, ey1 = edge_bounds(in_wood(feats, top), a.tool_mm)

    # board panel
    BRES = 0.42
    board, bpx = paint(feats, top, th, (0, 0, SHEET_W, SHEET_L), BRES, r)
    bd = ImageDraw.Draw(board)
    bd.rectangle((0, 0, board.width - 1, board.height - 1), outline=(120, 110, 90), width=2)
    for t in parts:  # mark tabs so they show at this size
        for tb in t['tabs']:
            x, y = bpx(tb['pts'][len(tb['pts']) // 2])
            bd.ellipse((x - 7, y - 7, x + 7, y + 7), outline=TAB, width=3)

    small = (ex1 - ex0) * (ey1 - ey0) < 0.45 * SHEET_W * SHEET_L
    if small:
        pad = 40
        view = (max(0, ex0 - pad), max(0, ey0 - pad), min(SHEET_W, ex1 + pad), min(SHEET_L, ey1 + pad))
        cres = min(620 / (view[2] - view[0]), 1040 / (view[3] - view[1]))
        close, cpx = paint(feats, top, th, view, cres, r)
        cd = ImageDraw.Draw(close)
        cd.rectangle((0, 0, close.width - 1, close.height - 1), outline=(120, 110, 90), width=2)
        for t in parts:
            for tb in t['tabs']:
                x, y = cpx(tb['pts'][len(tb['pts']) // 2])
                cd.ellipse((x - 11, y - 11, x + 11, y + 11), outline=TAB, width=3)

    # layout
    LM, TOP_H, GAP = 70, 150, 60
    W = max(LM + board.width + (GAP + close.width if small else 0) + 40, 900)
    H = TOP_H + max(board.height, close.height if small else 0) + 150
    can = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(can)
    title = a.title or os.path.basename(a.file)
    d.text((24, 18), title, font=font(30, True), fill=INK)
    d.text((24, 60), f'48 x 96 in sheet, seen from above at the machine. Zero X0 Y0 = bottom-left.',
           font=font(18), fill=MUTED)
    d.text((24, 84), f'{len(parts)} part{"s" if len(parts) != 1 else ""}, {ntabs} tabs. '
           f'Job starts {inch(ex0):.2f} in from the left edge, {inch(ey0):.2f} in from the bottom.',
           font=font(18), fill=MUTED)
    bx, by = LM, TOP_H
    can.paste(board, (bx, by))
    # sheet dimensions
    d.text((bx + board.width / 2, by + board.height + 12), '48 in (X)', font=font(18, True), fill=INK, anchor='mt')
    lbl = Image.new('RGBA', (200, 30), (0, 0, 0, 0))
    ImageDraw.Draw(lbl).text((100, 15), '96 in (Y)', font=font(18, True), fill=INK, anchor='mm')
    lbl = lbl.rotate(90, expand=True)
    can.paste(lbl, (bx - 46, by + board.height // 2 - 100), lbl)
    # zero corner
    zx, zy = bx, by + board.height
    d.ellipse((zx - 9, zy - 9, zx + 9, zy + 9), fill=ZERO)
    arrow(d, (zx, zy + 40), (zx + 70, zy + 40), ZERO)
    arrow(d, (zx - 40, zy), (zx - 40, zy - 70), ZERO)
    d.text((zx + 78, zy + 40), 'X', font=font(16, True), fill=ZERO, anchor='lm')
    d.text((zx - 40, zy - 78), 'Y', font=font(16, True), fill=ZERO, anchor='mb')
    d.text((zx, zy + 62), 'X0 Y0  zero / start', font=font(16, True), fill=ZERO)
    # part size on the board
    for t in parts:
        x0, y0, x1, y1 = t['bbox']
        cx, cy = bpx(((x0 + x1) / 2, (y0 + y1) / 2))
        txt = f'{inch(x1 - x0 + 2 * r):.1f} x {inch(y1 - y0 + 2 * r):.1f} in'
        tw = d.textlength(txt, font=font(14, True))
        if tw < (x1 - x0) * BRES - 6:
            d.text((bx + cx, by + cy), txt, font=font(14, True), fill=(255, 255, 255), anchor='mm')
    if small:
        cx0 = bx + board.width + GAP
        can.paste(close, (cx0, by))
        d.text((cx0, by - 8), 'Close-up', font=font(18, True), fill=INK, anchor='lb')
        # dashed link box on the board
        p0, p1 = bpx((view[0], view[3])), bpx((view[2], view[1]))
        d.rectangle((bx + p0[0], by + p0[1], bx + p1[0], by + p1[1]), outline=ZERO, width=2)
        for t in parts:
            x0, y0, x1, y1 = t['bbox']
            px0, py0 = cpx((x0 - r, y0 - r))
            px1, _ = cpx((x1 + r, y0 - r))
            d.text((cx0 + (px0 + px1) / 2, by + close.height + 12),
                   f'{inch(x1 - x0 + 2 * r):.2f} in wide x {inch(y1 - y0 + 2 * r):.2f} in long',
                   font=font(16, True), fill=INK, anchor='mt')
    # legend
    ly = H - 52
    lx = 24
    for col, name in ((PART, 'part'), (SCRAP, 'sheet left over'), (POCKET, 'label / pocket'),
                      (THRU, 'cut through'), (TAB, 'tab'), (ZERO, 'zero corner')):
        d.rectangle((lx, ly, lx + 22, ly + 22), fill=col, outline=(120, 120, 120))
        d.text((lx + 30, ly + 11), name, font=font(16), fill=INK, anchor='lm')
        lx += 30 + d.textlength(name, font=font(16)) + 28
    can.save(a.out)
    print(f'wrote {a.out} ({W}x{H})')


if __name__ == '__main__':
    main()
