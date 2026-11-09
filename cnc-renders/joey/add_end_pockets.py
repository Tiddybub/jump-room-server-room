#!/usr/bin/env python3
"""Add a half-lap pocket at every part end of the Joey slant window frame program.

Pocket: from the part's end edge 3 in (76.2 mm) along the arm, full part width, 9 mm deep from the
top face. Cut first (sheet still solid), one pass, straight plunge, zig-zag along the arm, then one
finishing pass along the shoulder. The bit
centre runs from the end edge to 3 mm short of the shoulder and across the full width, so the bit
edge reaches the shoulder line exactly and goes at most 3 mm past the part's end/sides (into the
outline's own kerf). Every original line is kept; lines are renumbered N10, N20 ...

Usage: python3 add_end_pockets.py IN.MMG OUT.MMG
"""
import math, re, sys
sys.path.insert(0, '/home/user/jump-room-server-room/.claude/skills/mmg-clean-cut/scripts')
from gcode import read_lines, write_lines, parse

SRC, DST = sys.argv[1], sys.argv[2]
TOP = 18.415                 # stock in the program header
DEPTH = 9.0
LENGTH = 3 * 25.4            # 76.2 mm
R = 3.0                      # 6 mm bit; toolpaths in the file are already offset by R
Z_FLOOR = TOP - DEPTH        # 9.415
Z_SAFE, Z_APPROACH = 30.0, 20.415
F_PLUNGE, F_CUT = 1270.0, 7620.0

lines = read_lines(SRC)
feats, _ = parse(lines, retract_z=29.0)


def edges_of(f):
    mv = [m for m in f['cut'] if (m[2], m[3]) != (m[5], m[6]) and abs(m[7] - m[4]) < 1e-6]
    out = []
    for m in mv:
        ang = math.atan2(m[6] - m[3], m[5] - m[2])
        if out and abs(((ang - out[-1][4]) + math.pi) % (2 * math.pi) - math.pi) < math.radians(0.5):
            out[-1][2], out[-1][3] = m[5], m[6]
        else:
            out.append([m[2], m[3], m[5], m[6], ang])
    pts = [(m[5], m[6]) for m in mv]
    return out, pts


def inside(poly, x, y):
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


ends = []
for f in feats:
    if 'PASS 1' not in (f['op'] or ''):
        continue
    part = f['op'].split(' PASS')[0]
    edges, pts = edges_of(f)
    for e in edges:
        L = math.dist(e[:2], e[2:4])
        if not 30 <= L <= 40:                       # end edge between the two corner arcs
            continue
        mx, my = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2
        tx, ty = (e[2] - e[0]) / L, (e[3] - e[1]) / L
        n = (-ty, tx)
        if not inside(pts, mx + n[0] * 20, my + n[1] * 20):
            n = (ty, -tx)
        b = (-n[1], n[0])
        # arm width from the toolpath's long edges 10-60 mm in from the end
        vs = [(px - mx) * b[0] + (py - my) * b[1] for px, py in pts
              if 10 <= (px - mx) * n[0] + (py - my) * n[1] <= 60 and abs((px - mx) * b[0] + (py - my) * b[1]) < 40]
        vmin, vmax = min(vs) + R, max(vs) - R          # part edges (toolpath is R outside the part)
        ends.append(dict(part=part, m=(mx, my), n=n, b=b, vmin=vmin, vmax=vmax))

assert len(ends) == 8, f'expected 8 part ends, found {len(ends)}'

def P(e, u, v):
    """point u mm in from the toolpath end line, v across; part end edge is at u = R"""
    return (e['m'][0] + e['n'][0] * u + e['b'][0] * v, e['m'][1] + e['n'][1] * u + e['b'][1] * v)

block = ['(END POCKETS: 8 PART ENDS, 76.2 MM (3 IN) LONG, FULL WIDTH, 9.0 MM DEEP TO Z%.3f)' % Z_FLOOR,
         '(CUT FIRST, ONE PASS, STRAIGHT PLUNGE F%.0f, CUT F%.0f)' % (F_PLUNGE, F_CUT)]
report = []
for k, e in enumerate(ends, 1):
    u0, u1 = R, R + LENGTH - R                         # bit centre: part end .. shoulder - R
    nlines = max(2, math.ceil((e['vmax'] - e['vmin']) / (2 * R * 0.5)) + 1)   # 50 % stepover
    vs = [e['vmin'] + (e['vmax'] - e['vmin']) * i / (nlines - 1) for i in range(nlines)]
    path = []
    for i, v in enumerate(vs):
        a, c = (u0, u1) if i % 2 == 0 else (u1, u0)
        path += [P(e, a, v), P(e, c, v)]
    # finishing pass along the shoulder (the zig-zag only joins every other pair of lines there,
    # which would leave scallops on the shoulder wall)
    if len(vs) % 2 == 0:
        path.append(P(e, u1, vs[-1]))
    path.append(P(e, u1, vs[0]))
    block.append(f"(END POCKET {k} - {e['part']} - WIDTH {e['vmax'] - e['vmin']:.1f} MM)")
    block += ['G0Z%.3f' % Z_SAFE, 'G0X%.3fY%.3f' % path[0], 'G0Z%.3f' % Z_APPROACH,
              'G1Z%.3fF%.1f' % (Z_FLOOR, F_PLUNGE)]
    block.append('G1X%.3fY%.3fF%.1f' % (path[1][0], path[1][1], F_CUT))
    block += ['G1X%.3fY%.3f' % p for p in path[2:]]
    block.append('G0Z%.3f' % Z_SAFE)
    report.append((k, e['part'], P(e, R, (e['vmin'] + e['vmax']) / 2), e['vmax'] - e['vmin'],
                   math.degrees(math.atan2(e['n'][1], e['n'][0]))))

# insert before the first part (after spindle start), renumber everything
first = next(i for i, l in enumerate(lines) if l.startswith('(PART 1 - '))
out = lines[:first] + block + lines[first:]
n = 0
for i, l in enumerate(out):
    if l and not l.startswith('(') and l != '%':
        n += 10
        out[i] = f'N{n}' + re.sub(r'^N\d+', '', l)
write_lines(DST, out)
for k, part, (x, y), w, ang in report:
    print(f'pocket {k}: {part:7s} end at ({x:7.1f},{y:7.1f}), width {w:.1f} mm, arm runs {ang:6.1f} deg from the end')
print(f'wrote {DST}: {len(block)} lines added before PART 1')
