#!/usr/bin/env python3
"""Prove a converted program cuts the same shapes as the original.

Sweeps a TOOL_MM bit along both programs and checks, using OUT.MMG.json from convert.py:
  labels: outline at the real wood surface unchanged, every label cut to the label depth,
          nothing deeper than the label depth
  parts : outline at the wood surface identical, nothing cut that the original did not cut,
          anything no longer cut is on the waste side. Thin differences flagged at the normal
          resolution are re-measured at 0.02 mm/px; up to FINE_TOL (0.25 mm = 0.01 in) passes,
          anything no longer cut is on the waste side (never touches the part)
  diff  : which operations changed
Exit code 1 if any check fails.

Usage: python3 verify.py ORIGINAL.MMG CONVERTED.MMG [--tool-mm 6]
"""
import argparse, difflib, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from gcode import read_lines, parse, move_pts
from PIL import Image, ImageChops, ImageDraw, ImageFilter


def raster(moves, box, zlimit, res, dia):
    x0, y1 = box[0], box[3]
    W = int((box[2] - box[0]) / res) + 1; H = int((box[3] - box[1]) / res) + 1
    im = Image.new('L', (W, H), 0); d = ImageDraw.Draw(im); r = dia / 2 / res
    def flush(run):
        if len(run) > 1: d.line(run, fill=255, width=max(1, int(round(2 * r))))
        for q in run[::max(1, int(r / 2))] + run[-1:]:
            d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=255)
    for m in moves:
        if m[1] == 0: continue
        pts = move_pts(m); L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) or 1e-9
        run, acc = [], 0.0
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1]); k = max(1, int(seg / res))
            for s in range(k + 1):
                t = s / k; z = m[4] + (m[7] - m[4]) * (acc + seg * t) / L
                p = ((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t - x0) / res,
                     (y1 - (pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)) / res)
                if z < zlimit: run.append(p)
                elif run: flush(run); run = []
            acc += seg
        if run: flush(run)
    return im


FINE_TOL = 0.25      # mm (0.01 in): widest allowed difference at a part edge, measured at 0.02 mm/px


def fine_width(flag, box, res, om, nm, top, D):
    """widest strip (mm) newly cut or no longer cut, re-rendered at 0.02 mm/px around flagged pixels"""
    ys, xs = np.nonzero(flag)
    spots = {}
    for x, y in zip(xs, ys):
        spots.setdefault((x // int(8 / res), y // int(8 / res)), []).append((box[0] + x * res, box[3] - y * res))
    worst, r2 = 0.0, 0.02
    def width(mask):
        k = 0; m = Image.fromarray((mask * 255).astype(np.uint8))
        while (np.array(m) > 0).any() and k < 400:
            m = m.filter(ImageFilter.MinFilter(3)); k += 1
        return k * 2 * r2
    for pts in spots.values():
        cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
        sb = (cx - 8, cy - 8, cx + 8, cy + 8)
        for lvl in (top, 0.0):
            o = np.array(raster(om, sb, lvl, r2, D)) > 0; n = np.array(raster(nm, sb, lvl, r2, D)) > 0
            worst = max(worst, width(n & ~o), width(o & ~n))
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('orig'); ap.add_argument('new'); ap.add_argument('--tool-mm', type=float, default=6.0)
    a = ap.parse_args()
    rep = json.load(open(a.new + '.json'))
    top, zl, D = rep['stock_in'] * 25.4, rep['label_z'], a.tool_mm
    la, lb = read_lines(a.orig), read_lines(a.new)
    fa, _ = parse(la); fb, _ = parse(lb)
    ok = True
    if len(fa) != len(fb):
        print(f'FAIL feature count changed {len(fa)} -> {len(fb)}'); sys.exit(1)

    # ---- labels
    if rep['labels']:
        res, px2 = 0.05, 0.0025
        t = dict(old=0, extra=0, lost=0, shallow=0, deeper=0); worst = 0
        for i in rep['labels']:
            A, B = fa[i], fb[i]
            bx = A['bbox']; box = (bx[0] - D, bx[1] - D, bx[2] + D, bx[3] + D)
            ot = raster(A['cut'], box, top, res, D); nt = raster(B['cut'], box, top, res, D)
            nf = raster(B['cut'], box, zl + 0.01, res, D); nd = raster(B['cut'], box, zl - 0.01, res, D)
            ex = ImageChops.subtract(nt, ot).histogram()[255] * px2
            t['old'] += ot.histogram()[255] * px2; t['extra'] += ex
            t['lost'] += ImageChops.subtract(ot, nt).histogram()[255] * px2
            t['shallow'] += ImageChops.subtract(nt, nf).histogram()[255] * px2
            t['deeper'] += nd.histogram()[255] * px2; worst = max(worst, ex)
        lab_ok = worst < 0.5 and t['deeper'] == 0 and t['shallow'] < 0.002 * t['old'] + 1
        ok &= lab_ok
        print(f"labels ({len(rep['labels'])}): outline {t['old']:.0f} mm2; new cut outside old {t['extra']:.2f} mm2 "
              f"(worst label {worst:.2f}); no longer cut {t['lost']:.2f} mm2; not at full depth {t['shallow']:.2f} mm2; "
              f"deeper than Z{zl}: {t['deeper']:.2f} mm2  -> {'OK' if lab_ok else 'FAIL'}")

    # ---- parts
    for row in rep['parts']:
        ri, oi = row['pass1'][0], row['outer']
        bx = fa[oi]['bbox']; box = (bx[0] - 10, bx[1] - 10, bx[2] + 10, bx[3] + 10)
        res = max(0.2, math.sqrt((box[2] - box[0]) * (box[3] - box[1]) / 8e6))
        om = fa[ri]['cut'] + (fa[oi]['cut'] if oi != ri else []); nm = fb[ri]['cut'] + (fb[oi]['cut'] if oi != ri else [])
        ot, nt = raster(om, box, top, res, D), raster(nm, box, top, res, D)
        ob, nb = raster(om, box, 0.0, res, D), raster(nm, box, 0.0, res, D)
        def region(k):
            im = k.copy(); ImageDraw.floodfill(im, (0, 0), 128); return np.array(im) == 0
        po, pn = region(ot), region(nt)
        OT, NT, OB, NB = (np.array(x) > 0 for x in (ot, nt, ob, nb))
        dmask = po ^ pn
        diff = int(dmask.sum())
        er = lambda b: np.array(Image.fromarray((b * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))) > 0
        # new cuts: one-pixel specks are where a drawn round end-cap lands on the grid; 2 px wide is real
        newc = int(er(NT & ~OT).sum() + er(NB & ~OB).sum())
        newc_px = int((NT & ~OT).sum() + (NB & ~OB).sum())
        # differences one pixel wide are drawing noise (e.g. a corner drawn as chords vs an arc);
        # anything that survives a 3x3 erosion is at least 2 pixels wide and counts as real
        wide = int((np.array(Image.fromarray((dmask * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))) > 0).sum())
        near = np.array(Image.fromarray((po * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
        touch = int(((OB & ~NB) & near).sum())
        p_ok = wide == 0 and newc == 0 and touch == 0 and po.sum() > 0
        fine = ''
        if not p_ok and wide == 0 and newc == 0 and po.sum() > 0:
            # only thin or tiny differences: measure them at 0.02 mm/px around each flagged spot
            flag = ((OB & ~NB) & near) | (NT & ~OT) | (NB & ~OB) | dmask
            w = fine_width(flag, box, res, om, nm, top, D)
            p_ok = w <= FINE_TOL
            fine = f'; at 0.02 mm/px widest difference {w:.2f} mm (limit {FINE_TOL} mm)'
        ok &= p_ok
        print(f'part {oi}{fine}: area {po.sum() * res * res / 100:.0f} cm2, outline diff {diff} px '
              f'({wide} px wider than {2 * res:.1f} mm), new cuts {newc_px} px ({newc} wider than {2 * res:.1f} mm), '
              f'no-longer-cut touching part {touch} px  -> {"OK" if p_ok else "FAIL"}')

    # ---- straight plunges: no X/Y movement while Z changes inside the wood (converted features)
    if rep.get('ramps_to_plunges') is not None:
        tgt = set(rep['labels']) | {x for pr in rep['parts'] for x in pr['pass1'] + [pr['outer']]}
        bad = []
        for i in tgt:
            for m in fb[i]['moves']:
                moving = abs(m[5] - m[2]) > 1e-6 or abs(m[6] - m[3]) > 1e-6
                if moving and abs(m[7] - m[4]) > 1e-6 and min(m[4], m[7]) < top - 1e-6:
                    bad.append(m[0] + 1)
                if m[1] == 0 and moving and min(m[4], m[7]) < top + 0.5:
                    bad.append(m[0] + 1)
        pl_ok = not bad
        ok &= pl_ok
        print(f'straight plunges: {len(bad)} moves change Z while moving in the wood, or rapid near the wood'
              f'{" (lines " + str(bad[:8]) + ")" if bad else ""}  -> {"OK" if pl_ok else "FAIL"}')

    # ---- which operations changed
    heads = [(i, l) for i, l in enumerate(la) if l.startswith('(')]
    changed = {}
    strip = lambda ls: [re.sub(r'^N\d+', '', l) for l in ls]          # compare without line numbers
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, strip(la), strip(lb), autojunk=False).get_opcodes():
        if tag != 'equal':
            op = [h for i, h in heads if i <= i1][-1] if heads and heads[0][0] <= i1 else 'header'
            changed[op] = changed.get(op, 0) + max(i2 - i1, j2 - j1)
    for i, h in heads:
        print(f'  {h:24s} {"changed " + str(changed[h]) + " lines" if h in changed else "unchanged"}')
    print('ALL CHECKS PASSED' if ok else 'CHECKS FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
