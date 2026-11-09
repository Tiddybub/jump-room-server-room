#!/usr/bin/env python3
"""Check the end-pocket program against the original. Usage: python3 check_end_pockets.py ORIG.MMG NEW.MMG"""
import sys, math, re, os
sys.path.insert(0, '/home/user/jump-room-server-room/.claude/skills/mmg-clean-cut/scripts')
import numpy as np
from PIL import Image, ImageDraw
from gcode import read_lines, parse, move_pts
SRC, NEW = sys.argv[1], sys.argv[2]
ok_all = True
sa = [re.sub(r'^N\d+', '', l) for l in read_lines(SRC)]
sb = [re.sub(r'^N\d+', '', l) for l in read_lines(NEW)]
k = next(i for i, l in enumerate(sa) if l.startswith('(PART 1 - '))
same = sa[:k] == sb[:k] and sa[k:] == sb[len(sb) - (len(sa) - k):]
block = sb[k:len(sb) - (len(sa) - k)]
x = y = 0.0; z = 30.0; bad = 0; zs = set()
for l in block:
    w = {kk: float(v) for kk, v in re.findall(r'([XYZ])(-?\d+\.?\d*)', l)}
    if not w: continue
    nx, ny, nz = w.get('X', x), w.get('Y', y), w.get('Z', z)
    if (nx, ny) != (x, y) and nz != z: bad += 1
    if l.startswith('G1') and (nx, ny) != (x, y): zs.add(round(nz, 3))
    x, y, z = nx, ny, nz
print(f'original program unchanged: {same} | pocket lines added: {len(block)} | moves changing Z while moving: {bad} | cut depths: {sorted(zs)}')
ok_all &= same and bad == 0 and len(zs) == 1
g = {}
here = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(here, 'add_end_pockets.py')).read().split('block = [')[0]
     .replace('SRC, DST = sys.argv[1], sys.argv[2]', f'SRC, DST = {SRC!r}, None'), g)
ends, R, LENGTH, Z_FLOOR, feats = g['ends'], g['R'], g['LENGTH'], g['Z_FLOOR'], g['feats']
fnew, _ = parse(read_lines(NEW), retract_z=29.0)
pm = [m for f in fnew for m in f['cut'] if abs(m[7] - Z_FLOOR) < 1e-6 and abs(m[4] - Z_FLOOR) < 1e-6]
p1 = {f['op'].split(' PASS')[0]: f for f in feats if 'PASS 1' in f['op']}
TOL = 0.01   # mm; the program's coordinates have 3 decimals
for kq, e in enumerate(ends, 1):
    def loc(px, py):
        dx, dy = px - e['m'][0], py - e['m'][1]
        return dx * e['n'][0] + dy * e['n'][1], dx * e['b'][0] + dy * e['b'][1]
    segs = [(loc(m[2], m[3]), loc(m[5], m[6])) for m in pm]
    segs = [(a, b) for a, b in segs if -10 < a[0] < R + LENGTH + 10 and e['vmin'] - 15 < a[1] < e['vmax'] + 15]
    # exact: every point of the pocket area within R of the bit path (bit sweeps a 6 mm band)
    us = np.arange(R, R + LENGTH + 1e-9, 0.1); vs = np.arange(e['vmin'], e['vmax'] + 1e-9, 0.1)
    UU, VV = np.meshgrid(us, vs); dmin = np.full(UU.shape, 1e9)
    for (ax, ay), (bx, by) in segs:
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy or 1e-12
        t = np.clip(((UU - ax) * dx + (VV - ay) * dy) / L2, 0, 1)
        dmin = np.minimum(dmin, np.hypot(UU - ax - t * dx, VV - ay - t * dy))
    gap = max(0.0, float(dmin.max()) - R)
    # exact reach of the bit edge: past the shoulder, past the part end, past the sides
    us_ = [p[0] for s_ in segs for p in s_]; vs_ = [p[1] for s_ in segs for p in s_]
    past_sh = max(us_) + R - (R + LENGTH)
    past_end = R - (min(us_) - R)                  # bit edge beyond the part end (part end is at u = R; allowed up to R)
    past_sd = max(e['vmin'] - (min(vs_) - R), (max(vs_) + R) - e['vmax'])   # allowed up to R
    dev = 0.0
    for m in p1[e['part']]['cut']:
        pp = move_pts(m)
        for a0, a1 in zip(pp, pp[1:]):
            n = max(1, int(math.dist(a0, a1) / 0.5))
            for t in range(n + 1):
                u, v = loc(a0[0] + (a1[0] - a0[0]) * t / n, a0[1] + (a1[1] - a0[1]) * t / n)
                if R + 1 <= u <= R + LENGTH and abs(v - (e['vmin'] + e['vmax']) / 2) < 30:
                    dev = max(dev, min(abs(v - (e['vmin'] - R)), abs(v - (e['vmax'] + R))))
    ok = gap <= TOL and past_sh <= TOL and past_end <= R + TOL and past_sd <= R + TOL and dev < 0.05
    ok_all &= ok
    print(f"pocket {kq} ({e['part']}): uncut gap {gap:.4f} mm, bit edge past shoulder {past_sh:+.3f} mm, "
          f"past part end {past_end:.3f} mm, past part side {past_sd:.3f} mm (max {R:.0f}), arm straight (dev {dev:.3f}) -> {'OK' if ok else 'FAIL'}")
print('ALL CHECKS PASSED' if ok_all else 'CHECKS FAILED')
sys.exit(0 if ok_all else 1)
