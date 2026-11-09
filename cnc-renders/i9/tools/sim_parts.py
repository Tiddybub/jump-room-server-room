import math, sys
sys.path.insert(0, sys.argv[3])
import numpy as np
from groups import parse_groups, move_pts
from PIL import Image, ImageDraw, ImageFilter

TOP = 0.71 * 25.4; D = 6.0; RES = 0.2
def parts(path):
    _, gs = parse_groups(path)
    r = [g for g in gs if g['op'] == 'ROUGHING 83' and g['zmin'] < 24]
    o = [g for g in gs if g['op'] == 'OUTER CUTS 2 96' and g['zmin'] < 24]
    return r, o
ro, oo = parts(sys.argv[1]); rn, on = parts(sys.argv[2])

def raster(moves, box, zlimit):
    x0, y1 = box[0], box[3]
    W = int((box[2] - box[0]) / RES) + 1; H = int((box[3] - box[1]) / RES) + 1
    im = Image.new('L', (W, H), 0); d = ImageDraw.Draw(im); r = D / 2 / RES
    def flush(run):
        if len(run) > 1: d.line(run, fill=255, width=int(round(2 * r)))
        for q in run[::8] + run[-1:]:
            d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=255)
    for m in moves:
        if m[1] == 0: continue
        pts = move_pts(m); L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) or 1e-9
        run, acc = [], 0.0
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1]); k = max(1, int(seg / 0.2))
            for s in range(k + 1):
                t = s / k; z = m[4] + (m[7] - m[4]) * (acc + seg * t) / L
                p = ((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t - x0) / RES, (y1 - (pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)) / RES)
                if z < zlimit: run.append(p)
                elif run: flush(run); run = []
            acc += seg
        if run: flush(run)
    return im

def part_region(kerf):
    im = kerf.copy(); ImageDraw.floodfill(im, (0, 0), 128)
    return np.array(im) == 0          # not kerf, not reached from outside

allok = True
for i, (a1, a2, b1, b2) in enumerate(zip(ro, oo, rn, on)):
    bx = a2['bbox']; box = (bx[0] - 10, bx[1] - 10, bx[2] + 10, bx[3] + 10)
    old_m = a1['moves'] + a2['moves']; new_m = b1['moves'] + b2['moves']
    ot, nt = raster(old_m, box, TOP), raster(new_m, box, TOP)
    ob, nb = raster(old_m, box, 0.0), raster(new_m, box, 0.0)
    po, pn = part_region(ot), part_region(nt)
    OT, NT, OB, NB = (np.array(x) > 0 for x in (ot, nt, ob, nb))
    part_diff = int((po ^ pn).sum())
    new_cut_top = int((NT & ~OT).sum()); new_cut_bot = int((NB & ~OB).sum())
    removed = OB & ~NB
    near = np.array(Image.fromarray((po * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    touch = int((removed & near).sum())
    ok = part_diff == 0 and new_cut_top == 0 and new_cut_bot == 0 and touch == 0
    allok &= ok
    print(f'part {i}: part area {po.sum() * RES * RES / 100:7.0f} cm2  top-outline diff {part_diff} px  '
          f'new cuts top/bottom {new_cut_top}/{new_cut_bot} px  no-longer-cut strip {removed.sum() * RES * RES:6.0f} mm2, '
          f'touching part {touch} px  {"OK" if ok else "CHECK"}')
print('ALL OK' if allok else 'SOME CHECKS FAILED')
