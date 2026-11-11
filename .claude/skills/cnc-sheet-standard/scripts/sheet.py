"""Shop sheet standard helpers: 48 x 96 in sheet, zero at bottom-left, parts held by tabs.

Machine coordinates (metric): X across the 48 in width, Y along the 96 in length,
X0 Y0 = bottom-left corner of the plywood, Z0 = spoilboard.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'mmg-clean-cut', 'scripts'))
from gcode import read_lines, parse, move_pts, program_top  # noqa: E402

IN = 25.4
SHEET_W = 48 * IN   # X, 1219.2 mm
SHEET_L = 96 * IN   # Y, 2438.4 mm
THROUGH_Z = 0.3     # a cut at or below this Z goes through the sheet
MIN_PART_MM = 50.0  # through cuts smaller than this are holes/slugs, not parts


def load(path):
    lines = read_lines(path)
    feats, _ = parse(lines)
    return lines, feats, program_top(lines)


def in_wood(feats, top):
    """cutting moves below the stock top"""
    return [m for f in feats for m in f['cut'] if min(m[4], m[7]) < top - 0.01]


def path_bounds(moves):
    xs, ys = [], []
    for m in moves:
        for x, y in move_pts(m):
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def edge_bounds(moves, tool_mm):
    """where the outside of the bit reaches"""
    x0, y0, x1, y1 = path_bounds(moves)
    r = tool_mm / 2
    return x0 - r, y0 - r, x1 + r, y1 + r


def final_lap(f):
    """XY points of one lap starting where the feature first reaches its lowest Z"""
    cut = f['cut']
    k = next(i for i, m in enumerate(cut) if min(m[4], m[7]) <= f['zmin'] + 1e-6)
    pts, run = [], 0.0
    for m in cut[k:]:
        p = move_pts(m)
        if not pts:
            pts.append(p[0])
        for a, b in zip(p, p[1:]):
            if run > 20 and seg_dist(pts[0], a, b) < 0.5:  # back at the start: one lap done
                return pts
            run += math.dist(a, b)
            pts.append(b)
    return pts


def seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L2 = ax * ax + ay * ay
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L2))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay))


def tabs(f, top):
    """tabs on a through cut: runs where the bit lifts off the through depth and comes back down.

    returns [{'z': tab height, 'pts': [(x, y), ...], 'len': mm}]"""
    out, run, down = [], None, False
    for m in f['cut']:
        z = min(m[4], m[7])
        if max(m[4], m[7]) <= THROUGH_Z:
            if run is not None:
                out.append(run)
            run, down = None, True
            continue
        if down and z < top - 0.01:
            if run is None:
                run = {'z': 0.0, 'pts': [], 'len': 0.0}
            if abs(m[7] - m[4]) < 1e-9:
                p = move_pts(m)
                run['pts'].extend(p)
                run['z'] = max(run['z'], m[7])
                run['len'] += sum(math.dist(a, b) for a, b in zip(p, p[1:]))
    # a run still open at the end is the final retract, not a tab; a run with no flat cutting
    # below the top is a lift over the wood, not a tab; a second through lap passes the same
    # tabs again, so count each tab location once
    uniq = []
    for r in out:
        if r['len'] <= 0.5:
            continue
        mid = r['pts'][len(r['pts']) // 2]
        if all(math.dist(mid, u['pts'][len(u['pts']) // 2]) > 3.0 for u in uniq):
            uniq.append(r)
    return uniq


def through_features(feats, top):
    """through cuts big enough to drop a piece, with nesting: level 0 = part outline,
    1 = cutout inside a part (sink hole, window), 2 = part inside a cutout, ..."""
    th = []
    for f in feats:
        if f['zmin'] > THROUGH_Z:
            continue
        x0, y0, x1, y1 = path_bounds(f['cut'])
        if max(x1 - x0, y1 - y0) < MIN_PART_MM:
            continue
        th.append({'f': f, 'bbox': (x0, y0, x1, y1), 'tabs': tabs(f, top)})

    def inside(a, b):
        return (a[0] > b[0] - 1 and a[1] > b[1] - 1 and a[2] < b[2] + 1 and a[3] < b[3] + 1
                and (b[2] - b[0]) * (b[3] - b[1]) > (a[2] - a[0]) * (a[3] - a[1]) * 1.01)
    for t in th:
        t['level'] = sum(inside(t['bbox'], o['bbox']) for o in th if o is not t)
        t['kind'] = 'part' if t['level'] % 2 == 0 else 'cutout'
    return th


def inch(mm):
    return mm / IN
