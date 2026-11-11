#!/usr/bin/env python3
"""Check a program against the shop sheet standard.

usage: python3 sheet_check.py FILE.MMG [--tool-mm 6]

Reports: fits on the 48 x 96 in sheet, how far the cuts start from the X0 Y0 (bottom-left)
corner, and how many tabs hold each part. Exit code 1 if something is off.
"""
import argparse
import sys

from sheet import (SHEET_W, SHEET_L, load, in_wood, edge_bounds, through_features, inch)

MAX_CORNER_GAP_IN = 3.0   # cuts should start within this of the zero corner (CAM nest margins are ~1-3 in)
TABS_MIN, TABS_MAX = 2, 6


def check(path, tool_mm=6.0, quiet=False):
    lines, feats, top = load(path)
    moves = in_wood(feats, top)
    x0, y0, x1, y1 = edge_bounds(moves, tool_mm)
    th = through_features(feats, top)
    problems = []
    say = (lambda *a: None) if quiet else print

    say(f'{path}')
    say(f'  stock top Z{top:.3f}  ({inch(top):.3f} in as programmed)')
    say(f'  cut area (outside of bit): X {x0:.1f}..{x1:.1f}  Y {y0:.1f}..{y1:.1f} mm'
        f'  = {inch(x1 - x0):.2f} x {inch(y1 - y0):.2f} in')
    fits = x0 >= -0.01 and y0 >= -0.01 and x1 <= SHEET_W + 0.01 and y1 <= SHEET_L + 0.01
    say(f'  fits 48 x 96 sheet: {"YES" if fits else "NO"}')
    if not fits:
        problems.append('does not fit on the 48 x 96 sheet')
    say(f'  gap from zero corner (bottom-left): left {inch(x0):.2f} in, bottom {inch(y0):.2f} in')
    if inch(x0) > MAX_CORNER_GAP_IN or inch(y0) > MAX_CORNER_GAP_IN:
        problems.append('cuts do not start at the bottom-left corner')
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
    a = ap.parse_args()
    sys.exit(1 if check(a.file, a.tool_mm) else 0)
