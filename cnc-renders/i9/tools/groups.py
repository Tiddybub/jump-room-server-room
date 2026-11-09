"""Parse a G-code file into cutting groups (between full retracts). Shared by the I9 scripts."""
import math, re

def parse_groups(path, retract_z=24.0):
    cur = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
    modal = 0
    op = None
    groups, g = [], None
    lines = open(path, errors='replace').read().replace('\r', '').split('\n')
    for ln, line in enumerate(lines):
        m = re.search(r'\((.*?)\)', line)
        if m:
            op = m.group(1); g = None; continue
        w = {}
        for k, v in re.findall(r'([A-Z])(-?\d+\.?\d*)', line):
            w.setdefault(k, float(v))
        if 'G' in w: modal = int(w['G'])
        if not any(k in w for k in 'XYZ'): continue
        p0 = dict(cur); cur.update({k: w[k] for k in 'XYZ' if k in w})
        if modal == 0 and 'Z' in w and cur['Z'] >= retract_z:
            g = None; continue
        if g is None:
            g = {'op': op, 'start': ln, 'moves': []}; groups.append(g)
        g['end'] = ln
        g['moves'].append((ln, modal, p0['X'], p0['Y'], p0['Z'], cur['X'], cur['Y'], cur['Z'], w.get('I', 0.0), w.get('J', 0.0)))
    for g in groups:
        zs = [m[7] for m in g['moves']] + [m[4] for m in g['moves']]
        g['zmin'] = min(zs)
        xs = [m[5] for m in g['moves']]; ys = [m[6] for m in g['moves']]
        g['bbox'] = (min(xs), min(ys), max(xs), max(ys))
    return lines, groups

def arc_pts(x0, y0, x1, y1, i, j, cw, step=0.2):
    cx, cy = x0 + i, y0 + j; r = math.hypot(i, j)
    a0 = math.atan2(y0 - cy, x0 - cx); a1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        while a1 >= a0 - 1e-9: a1 -= 2 * math.pi
    else:
        while a1 <= a0 + 1e-9: a1 += 2 * math.pi
    n = max(2, int(abs(a1 - a0) * r / step))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]

def move_pts(m):
    ln, g, x0, y0, z0, x1, y1, z1, i, j = m
    if g in (2, 3): return arc_pts(x0, y0, x1, y1, i, j, g == 2)
    return [(x0, y0), (x1, y1)]
