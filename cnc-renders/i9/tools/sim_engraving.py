"""Labels + I9 badge: outline at the wood surface old vs new, and area not cut to full depth."""
import math, sys
sys.path.insert(0, sys.argv[3])
from groups import parse_groups, move_pts
from PIL import Image, ImageChops, ImageDraw
IN = 25.4; TOP = 0.71 * IN; ZF = TOP - 0.165 * IN; D = 6.0; RES = 0.05
_, ga = parse_groups(sys.argv[1]); _, gb = parse_groups(sys.argv[2])
def is_eng(g):
    if not (g['op'] and g['op'].startswith('POCKET')) or g['zmin'] >= 24: return False
    return 16 < g['zmin'] < 19 or g['bbox'][3] < 300
def is_eng_new(g):
    return g['op'] and g['op'].startswith('POCKET') and g['zmin'] < 24 and (abs(g['zmin'] - ZF) < 0.002)
la = [g for g in ga if is_eng(g)]; lb = [g for g in gb if is_eng_new(g)]
print('engraved features old/new:', len(la), len(lb))
def raster(g, box, zlimit, im=None):
    x0, y0 = box[0], box[3]
    W = int((box[2] - box[0]) / RES) + 1; H = int((box[3] - box[1]) / RES) + 1
    im = im or Image.new('L', (W, H), 0); d = ImageDraw.Draw(im); r = D / 2 / RES
    for m in g['moves']:
        if m[1] == 0: continue
        pts = move_pts(m); L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) or 1e-9
        run, acc = [], 0.0
        def flush(run):
            if len(run) > 1: d.line(run, fill=255, width=int(2 * r))
            for q in run[::20] + run[-1:]: d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=255)
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1]); k = max(1, int(seg / 0.1))
            for s in range(k + 1):
                t = s / k; z = m[4] + (m[7] - m[4]) * (acc + seg * t) / L
                p = ((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t - x0) / RES, (y0 - (pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)) / RES)
                if z < zlimit: run.append(p)
                elif run: flush(run); run = []
            acc += seg
        if run: flush(run)
    return im
assert len(la) == len(lb)
tot = dict(old=0, new=0, extra=0, lost=0, shallow=0, deeper=0)
px2 = RES * RES
for a, b in zip(la, lb):
    bx = a['bbox']; box = (bx[0] - 6, bx[1] - 6, bx[2] + 6, bx[3] + 6)
    ot, nt, nf = raster(a, box, TOP), raster(b, box, TOP), raster(b, box, ZF + 0.01)
    nd = raster(b, box, ZF - 0.01)
    tot['old'] += ot.histogram()[255] * px2; tot['new'] += nt.histogram()[255] * px2
    tot['extra'] += ImageChops.subtract(nt, ot).histogram()[255] * px2
    tot['lost'] += ImageChops.subtract(ot, nt).histogram()[255] * px2
    tot['shallow'] += ImageChops.subtract(nt, nf).histogram()[255] * px2
    tot['deeper'] += nd.histogram()[255] * px2
print('outline area at surface old %.1f / new %.1f mm2; new outside old %.2f mm2; old missing %.2f mm2' % (tot['old'], tot['new'], tot['extra'], tot['lost']))
print('cut at surface but not to 0.165: %.2f mm2;  cut deeper than 0.165: %.2f mm2' % (tot['shallow'], tot['deeper']))
