"""Shared G-code helpers: parse an MMG program into cutting features (one per plunge-and-retract)."""
import math
import re

WORD = re.compile(r'([A-Z])(-?\d+\.?\d*)')
ZWORD = re.compile(r'Z(-?\d+\.?\d*)')


def read_lines(path):
    """Program lines without line endings (files are CRLF)."""
    return open(path, errors='replace').read().replace('\r', '').split('\n')


def write_lines(path, lines):
    open(path, 'w', newline='').write('\r\n'.join(lines))


def parse(lines, retract_z=None):
    """Split into features. A feature ends at a G0 that goes up to the clearance height.

    move = (line_index, gcode, x0, y0, z0, x1, y1, z1, i, j)
    """
    if retract_z is None:
        retract_z = clearance(lines) - 0.01
    cur = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
    modal, op, feats, f = 0, None, [], None
    for ln, line in enumerate(lines):
        m = re.search(r'\((.*?)\)', line)
        if m:
            op, f = m.group(1).strip(), None
            continue
        w = {}
        for k, v in WORD.findall(line):
            w.setdefault(k, float(v))
        if 'G' in w:
            modal = int(w['G'])
        if not any(k in w for k in 'XYZ'):
            continue
        p0 = dict(cur)
        cur.update({k: w[k] for k in 'XYZ' if k in w})
        if modal == 0 and 'Z' in w and cur['Z'] >= retract_z:
            f = None
            continue
        if f is None:
            f = {'op': op, 'start': ln, 'moves': []}
            feats.append(f)
        f['end'] = ln
        f['moves'].append((ln, modal, p0['X'], p0['Y'], p0['Z'], cur['X'], cur['Y'], cur['Z'],
                           w.get('I', 0.0), w.get('J', 0.0)))
    out = []
    for f in feats:
        cut = [m for m in f['moves'] if m[1] != 0]
        if not cut:
            continue
        f['cut'] = cut
        f['zmin'] = min(min(m[4], m[7]) for m in cut)
        xs = [v for m in cut for v in (m[2], m[5])]
        ys = [v for m in cut for v in (m[3], m[6])]
        f['bbox'] = (min(xs), min(ys), max(xs), max(ys))
        f['flat'] = flat_lengths(cut)
        f['plunge'] = plunge_height(cut)
        out.append(f)
    for k, f in enumerate(out):
        f['id'] = k
    return out, retract_z


def arc_pts(x0, y0, x1, y1, i, j, cw, step=0.2):
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    if cw:
        while a1 >= a0 - 1e-9:
            a1 -= 2 * math.pi
    else:
        while a1 <= a0 + 1e-9:
            a1 += 2 * math.pi
    n = max(2, int(abs(a1 - a0) * r / step))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def move_pts(m):
    if m[1] in (2, 3):
        return arc_pts(m[2], m[3], m[5], m[6], m[8], m[9], m[1] == 2)
    return [(m[2], m[3]), (m[5], m[6])]


def move_len(m):
    p = move_pts(m)
    return sum(math.dist(p[i], p[i + 1]) for i in range(len(p) - 1))


def flat_lengths(cut):
    """mm of cutting at each constant Z level"""
    L = {}
    for m in cut:
        if abs(m[7] - m[4]) < 1e-9:
            z = round(m[7], 3)
            L[z] = L.get(z, 0.0) + move_len(m)
    return L


def plunge_height(cut):
    """Z of the first feed move straight down (G1 Z.. F..) - where the ramp starts."""
    for m in cut:
        if m[1] == 1 and (m[2], m[3]) == (m[5], m[6]) and m[7] < m[4]:
            return m[7]
    return cut[0][4]


def floors(f, top, min_len=5.0):
    """real cutting depths of a feature: below the stock top, with > min_len mm of cutting
    (ignores relinks above the wood and short hops between areas)"""
    return sorted((z for z, L in f['flat'].items() if L > min_len and z < top - 0.01), reverse=True)


def set_z(line, z):
    m = ZWORD.search(line)
    return line[:m.start()] + f'Z{z:.3f}' + line[m.end():]


def clearance(lines):
    """the rapid height used between features: the most common 'G0 Z..' with no X/Y"""
    cnt = {}
    for l in lines:
        if 'G0' in l and 'X' not in l and 'Y' not in l:
            m = ZWORD.search(l)
            if m:
                cnt[float(m.group(1))] = cnt.get(float(m.group(1)), 0) + 1
    return max(cnt, key=cnt.get)


def program_top(lines):
    """Stock top the CAM assumed: clearance is set 0.2 in above it."""
    return clearance(lines) - 0.2 * 25.4
