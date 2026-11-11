#!/usr/bin/env python3
"""Move a job to the bottom-left (X0 Y0) corner of the 48 x 96 in sheet.

usage: python3 place_on_sheet.py IN.MMG OUT.MMG [--margin-in 0.25] [--tool-mm 6]
                                 [--dx MM --dy MM]

Shifts every X and Y word by the same amount, so the outside of the bit ends up --margin-in
from the left and bottom sheet edges. An axis already within 1 mm of that is left alone.
Arcs use I/J relative to the start point (checked), so they move with the path unchanged.
Z, feeds, order and everything else stay byte-for-byte the same. Proves it line by line.
"""
import argparse
import math
import re
import sys

from sheet import IN, SHEET_W, SHEET_L, load, in_wood, edge_bounds
from gcode import write_lines

XY = re.compile(r'([XY])(-?\d+\.?\d*)')
WORD = re.compile(r'([A-Z])(-?\d+\.?\d*)')


def arcs_are_relative(lines):
    """I/J relative to the arc start (incremental) -> start and end are the same distance
    from the centre. Checks every arc; returns (ok, arcs checked)."""
    cur = {'X': 0.0, 'Y': 0.0}
    modal, n, bad = 0, 0, 0
    for line in lines:
        if '(' in line:
            continue
        w = {k: float(v) for k, v in WORD.findall(line)}
        if 'G' in w:
            modal = int(w['G'])
        p0 = dict(cur)
        cur.update({k: w[k] for k in 'XY' if k in w})
        if modal in (2, 3) and ('I' in w or 'J' in w):
            cx, cy = p0['X'] + w.get('I', 0.0), p0['Y'] + w.get('J', 0.0)
            r0, r1 = math.dist((cx, cy), (p0['X'], p0['Y'])), math.dist((cx, cy), (cur['X'], cur['Y']))
            n += 1
            bad += abs(r0 - r1) > 0.01 + 1e-4 * r0
    return bad == 0, n


def shift_line(line, dx, dy):
    if '(' in line:
        return line
    return XY.sub(lambda m: f'{m.group(1)}{float(m.group(2)) + (dx if m.group(1) == "X" else dy):.3f}', line)


def prove(a, b, dx, dy):
    """same lines, same words in the same order; only X/Y values differ, by exactly dx/dy"""
    assert len(a) == len(b), 'line count changed'
    for la, lb in zip(a, b):
        if '(' in la or not WORD.search(la):
            assert la == lb, f'line changed: {la!r} -> {lb!r}'
            continue
        wa, wb = WORD.findall(la), WORD.findall(lb)
        assert [k for k, _ in wa] == [k for k, _ in wb], f'words changed: {la!r} -> {lb!r}'
        for (k, va), (_, vb) in zip(wa, wb):
            if k in 'XY':
                d = dx if k == 'X' else dy
                assert abs(float(vb) - float(va) - d) < 6e-4, f'{k} off: {la!r} -> {lb!r}'
            else:
                assert va == vb, f'{k} changed: {la!r} -> {lb!r}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--margin-in', type=float, default=0.25)
    ap.add_argument('--tool-mm', type=float, default=6.0)
    ap.add_argument('--dx', type=float)
    ap.add_argument('--dy', type=float)
    a = ap.parse_args()

    lines, feats, top = load(a.src)
    if any(re.search(r'G9[12]|G5[3-9]', l) for l in lines if '(' not in l):
        sys.exit('program uses G91/G92/G53-G59 - not shifting it blindly')
    ok, narcs = arcs_are_relative(lines)
    if not ok:
        sys.exit('arcs are not I/J-relative - stop')
    x0, y0, x1, y1 = edge_bounds(in_wood(feats, top), a.tool_mm)
    want = a.margin_in * IN
    dx = a.dx if a.dx is not None else (0.0 if abs(x0 - want) < 1.0 else round(want - x0, 3))
    dy = a.dy if a.dy is not None else (0.0 if abs(y0 - want) < 1.0 else round(want - y0, 3))

    out = [shift_line(l, dx, dy) for l in lines]
    prove(lines, out, dx, dy)
    write_lines(a.dst, out)

    _, feats2, top2 = load(a.dst)
    nx0, ny0, nx1, ny1 = edge_bounds(in_wood(feats2, top2), a.tool_mm)
    fits = nx0 >= 0 and ny0 >= 0 and nx1 <= SHEET_W and ny1 <= SHEET_L
    print(f'shift X {dx:+.3f} mm ({dx / IN:+.3f} in), Y {dy:+.3f} mm ({dy / IN:+.3f} in); {narcs} arcs checked relative')
    print(f'cuts now X {nx0:.1f}..{nx1:.1f}  Y {ny0:.1f}..{ny1:.1f} mm'
          f'  (left gap {nx0 / IN:.2f} in, bottom gap {ny0 / IN:.2f} in)  fits 48x96: {"YES" if fits else "NO"}')
    print('proof: every line identical except X/Y moved by exactly the shift - OK')
    if not fits:
        sys.exit(1)


if __name__ == '__main__':
    main()
