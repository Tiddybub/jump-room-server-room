#!/usr/bin/env python3
"""Turn a whole job 90 / -90 / 180 degrees on the sheet. ONLY when the user asks for it:
the programmer's rotation is kept otherwise.

usage: python3 rotate_job.py IN.MMG OUT.MMG --deg 90|-90|180
        90 = counter-clockwise (seen from above at the machine), -90 = clockwise

A rotation (never a mirror) keeps the part's shape, G2/G3 directions (climb/conventional),
and label text the right way round. Every X/Y word and every I/J arc offset is turned; Z,
feeds and everything else stay byte-for-byte. The result sits around the origin: run
place_on_sheet.py (or standard.py) after it. Proves every position, line by line.
"""
import argparse
import math
import re
import sys

import sheet  # noqa: F401  (puts the mmg-clean-cut parser on the path)
from gcode import read_lines, write_lines
from place_on_sheet import arcs_are_relative

TOK = re.compile(r'([A-Z])(-?\d+\.?\d*)')
ROT = {90: lambda x, y: (-y, x), -90: lambda x, y: (y, -x), 180: lambda x, y: (-x, -y)}


def fmt(v):
    v = 0.0 if abs(v) < 5e-4 else v
    return f'{v:.3f}'


def rotate_line(line, deg, pos):
    """pos = absolute X/Y before this line (old frame). Returns new line text."""
    if '(' in line or not TOK.search(line):
        return line
    toks = TOK.findall(line)
    w = {k: float(v) for k, v in toks}
    has_xy, has_ij = ('X' in w or 'Y' in w), ('I' in w or 'J' in w)
    nx, ny = ROT[deg](w.get('X', pos[0]), w.get('Y', pos[1]))
    ni, nj = ROT[deg](w.get('I', 0.0), w.get('J', 0.0))
    out, done_xy, done_ij = [], False, False
    for k, v in toks:
        if k in 'XY':
            if not done_xy:
                out.append(f'X{fmt(nx)}Y{fmt(ny)}')   # always both: the turned move changes both axes' meaning
                done_xy = True
        elif k in 'IJ':
            if not done_ij:
                out.append(f'I{fmt(ni)}J{fmt(nj)}')
                done_ij = True
        else:
            out.append(k + v)
    if has_xy:
        pos[0], pos[1] = w.get('X', pos[0]), w.get('Y', pos[1])
    return ''.join(out)


def prove(a, b, deg):
    """replay both programs: every absolute position and arc centre of the new one = the old one turned"""
    pa, pb = [0.0, 0.0], [0.0, 0.0]
    assert len(a) == len(b), 'line count changed'
    for la, lb in zip(a, b):
        if '(' in la or not TOK.search(la):
            assert la == lb, f'line changed: {la!r}'
            continue
        wa, wb = dict(TOK.findall(la)), dict(TOK.findall(lb))
        for k in set(wa) | set(wb):
            if k not in 'XYIJ':
                assert wa.get(k) == wb.get(k), f'{k} changed: {la!r} -> {lb!r}'
        s0 = tuple(pa)
        pa[0], pa[1] = float(wa.get('X', pa[0])), float(wa.get('Y', pa[1]))
        pb[0], pb[1] = float(wb.get('X', pb[0])), float(wb.get('Y', pb[1]))
        ex = ROT[deg](*pa)
        assert math.dist(ex, pb) < 1e-3, f'position off: {la!r} -> {lb!r}'
        if 'I' in wa or 'J' in wa:
            ca = ROT[deg](s0[0] + float(wa.get('I', 0)), s0[1] + float(wa.get('J', 0)))
            sb = ROT[deg](*s0)
            cb = (sb[0] + float(wb.get('I', 0)), sb[1] + float(wb.get('J', 0)))
            assert math.dist(ca, cb) < 1e-3, f'arc centre off: {la!r} -> {lb!r}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--deg', type=int, choices=(90, -90, 180), required=True)
    a = ap.parse_args()
    lines = read_lines(a.src)
    if any(re.search(r'G9[12]|G5[3-9]', l) for l in lines if '(' not in l):
        sys.exit('program uses G91/G92/G53-G59 - not rotating it blindly')
    ok, n = arcs_are_relative(lines)
    if not ok:
        sys.exit('arcs are not I/J-relative - stop')
    pos = [0.0, 0.0]
    out = [rotate_line(l, a.deg, pos) for l in lines]
    prove(lines, out, a.deg)
    write_lines(a.dst, out)
    print(f'turned {a.deg} deg ({"counter-clockwise" if a.deg == 90 else "clockwise" if a.deg == -90 else "half turn"}); '
          f'{n} arcs checked; proof: every position and arc centre turned exactly - OK')


if __name__ == '__main__':
    main()
