#!/usr/bin/env python3
"""Check a program against the shop sheet standard.

usage: python3 sheet_check.py FILE.MMG [--tool-mm 6]

Reports: fits on the 48 x 96 in sheet, how far the cuts start from the X0 Y0 (bottom-left)
corner, and how many tabs hold each part. Exit code 1 if something is off.
"""
import argparse
import sys

from sheet import (IN, SHEET_W, SHEET_L, LABEL_DEPTH, PART_PASSES, load, in_wood, edge_bounds,
                   through_features, inch, real_stock_mm, labels, part_passes)

MAX_CORNER_GAP_IN = 3.0   # cuts should start within this of the zero corner (CAM nest margins are ~1-3 in)
TABS_MIN, TABS_MAX = 2, 6


def check(path, tool_mm=6.0, quiet=False, stock_in=None):
    lines, feats, top = load(path)
    moves = in_wood(feats, top)
    x0, y0, x1, y1 = edge_bounds(moves, tool_mm)
    th = through_features(feats, top)
    problems = []
    say = (lambda *a: None) if quiet else print

    say(f'{path}')
    real, why = real_stock_mm(top, stock_in)
    say(f'  stock: programmed {inch(top):.3f} in (top Z{top:.3f}), real {inch(real):.3f} in ({why})')
    if why.startswith('unknown'):
        problems.append('stock thickness unknown - confirm it')
    say(f'  cut area (outside of bit): X {x0:.1f}..{x1:.1f}  Y {y0:.1f}..{y1:.1f} mm'
        f'  = {inch(x1 - x0):.2f} x {inch(y1 - y0):.2f} in')
    fits = x0 >= -0.01 and y0 >= -0.01 and x1 <= SHEET_W + 0.01 and y1 <= SHEET_L + 0.01
    say(f'  fits 48 x 96 sheet: {"YES" if fits else "NO"}')
    if not fits:
        problems.append('does not fit on the 48 x 96 sheet')
    say(f'  gap from zero corner (bottom-left): left {inch(x0):.2f} in, bottom {inch(y0):.2f} in')
    if inch(x0) > MAX_CORNER_GAP_IN or inch(y0) > MAX_CORNER_GAP_IN:
        problems.append('cuts do not start at the bottom-left corner')
    # labels: 0.165 in below the real top, one pass. Shallow = the programmer's error: TELL THE USER
    lab = labels(feats, top, real)
    shallow = [f for f in lab if real - f['zmin'] < LABEL_DEPTH - 0.05]
    deep = [f for f in lab if real - f['zmin'] > LABEL_DEPTH + 0.05]
    multi = [f for f in lab if len([z for z in f['flat'] if z < real - 0.01 and f['flat'][z] > 5]) > 1]
    if lab:
        ds = sorted({round(inch(real - f['zmin']), 3) for f in lab})
        say(f'  labels: {len(lab)}, depth below real top: {", ".join(f"{d:.3f}" for d in ds)} in'
            f' (must be {inch(LABEL_DEPTH):.3f})')
    if shallow:
        problems.append(f'{len(shallow)} labels SHALLOW ({min(inch(real - f["zmin"]) for f in shallow):.3f} in) '
                        f'- programmer error, tell the user')
    if deep:
        say(f'  note: {len(deep)} labels deeper than 0.165 in')
    if multi:
        problems.append(f'{len(multi)} labels cut in more than one pass')
    for t in th:
        bx0, by0, bx1, by1 = t['bbox']
        n = len(t['tabs'])
        hz = ', '.join(sorted({f'Z{r["z"]:.3f}' for r in t['tabs']})) or '-'
        tag = ''
        if t['kind'] == 'part' and n < TABS_MIN:
            tag = '  <-- needs tabs'
            problems.append(f'part at X{bx0:.0f} Y{by0:.0f} has {n} tabs')
        elif t['kind'] == 'part' and n > TABS_MAX:
            tag = '  <-- a lot of tabs'
        if t['kind'] == 'part':
            pz = part_passes(feats, t, real)
            if len(pz) != PART_PASSES:
                tag += f'  <-- {len(pz)} passes, must be {PART_PASSES}'
                problems.append(f'part at X{bx0:.0f} Y{by0:.0f} cut in {len(pz)} passes')
            tag = f'  passes: {len(pz)} ({", ".join(f"Z{z:.3f}" for z in pz)})' + tag
        say(f'  {t["kind"]:6s} {t["f"]["op"]:<16s} {inch(bx1 - bx0):5.1f} x {inch(by1 - by0):5.1f} in'
            f'  tabs: {n} ({hz}){tag}')
    parts = [t for t in th if t['kind'] == 'part']
    say(f'  parts: {len(parts)}, tabs total: {sum(len(t["tabs"]) for t in parts)}')
    say('  RESULT: ' + ('OK' if not problems else 'FIX -> ' + '; '.join(problems)))
    return problems


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--tool-mm', type=float, default=6.0)
    ap.add_argument('--stock-in', type=float, help='real thickness; default from the CAM top: '
                    '1/2 in -> 0.5, 3/4 in -> 0.71 (18 mm)')
    a = ap.parse_args()
    sys.exit(1 if check(a.file, a.tool_mm, stock_in=a.stock_in) else 0)
