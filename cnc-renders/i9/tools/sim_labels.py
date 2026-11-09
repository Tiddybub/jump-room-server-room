import math, sys
sys.path.insert(0, sys.argv[3])
from groups import parse_groups, move_pts
from PIL import Image, ImageChops, ImageDraw

IN = 25.4; TOP = 0.71 * IN; ZF = TOP - 0.165 * IN; D = 6.0; RES = 0.05
_, ga = parse_groups(sys.argv[1]); _, gb = parse_groups(sys.argv[2])
pick = lambda gs: [g for g in gs if g['op'] and g['op'].startswith('POCKET') and 16 < g['zmin'] < 19]
la = pick(ga); lb = [g for g in gb if g['start'] in {x['start'] for x in la}]
assert len(la) == len(lb) == 42

def raster(g, box, zlimit):
    x0, y0 = box[0], box[3]
    W = int((box[2] - box[0]) / RES) + 1; H = int((box[3] - box[1]) / RES) + 1
    im = Image.new('L', (W, H), 0); d = ImageDraw.Draw(im); r = D / 2 / RES
    for m in g['moves']:
        if m[1] == 0: continue
        pts = move_pts(m); n = len(pts) - 1
        # interpolate Z along the move, keep pieces below zlimit
        L = sum(math.dist(pts[i], pts[i + 1]) for i in range(n)) or 1e-9
        dense, acc = [], 0.0
        for i in range(n):
            seg = math.dist(pts[i], pts[i + 1]); k = max(1, int(seg / 0.1))
            for s in range(k + (1 if i == n - 1 else 0)):
                t = s / k; px = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t; py = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
                z = m[4] + (m[7] - m[4]) * (acc + seg * t) / L
                dense.append((px, py, z))
            acc += seg
        run = []
        for (px, py, z) in dense + [(0, 0, 1e9)]:
            if z < zlimit:
                run.append(((px - x0) / RES, (y0 - py) / RES))
            else:
                if run:
                    if len(run) > 1: d.line(run, fill=255, width=int(2 * r))
                    for (qx, qy) in (run[0], run[-1]):
                        d.ellipse([qx - r, qy - r, qx + r, qy + r], fill=255)
                    for (qx, qy) in run[::20]:
                        d.ellipse([qx - r, qy - r, qx + r, qy + r], fill=255)
                run = []
    return im

tot = {'old': 0, 'new': 0, 'extra': 0, 'lost': 0, 'shallow': 0}
worst = []
for a, b in zip(la, lb):
    bx = a['bbox']; box = (bx[0] - 6, bx[1] - 6, bx[2] + 6, bx[3] + 6)
    old_top = raster(a, box, TOP); new_top = raster(b, box, TOP); new_full = raster(b, box, ZF + 0.01)
    px2 = RES * RES
    o = old_top.histogram()[255]; n = new_top.histogram()[255]
    extra = ImageChops.subtract(new_top, old_top).histogram()[255]
    lost = ImageChops.subtract(old_top, new_top).histogram()[255]
    shallow = ImageChops.subtract(new_top, new_full).histogram()[255]
    for k, v in (('old', o), ('new', n), ('extra', extra), ('lost', lost), ('shallow', shallow)): tot[k] += v * px2
    worst.append((extra * px2, shallow * px2, a['start'] + 1, round(a['zmin'], 3)))
print('label outline area at the wood surface: old %.1f mm2, new %.1f mm2' % (tot['old'], tot['new']))
print('  new area outside old outline: %.2f mm2   old area missing in new: %.2f mm2' % (tot['extra'], tot['lost']))
print('  area cut at the surface but not at full 0.165 depth (fuzz risk): %.2f mm2' % tot['shallow'])
worst.sort(reverse=True)
print('worst features (extra mm2, shallow mm2, start line, old floor):', worst[:5])
