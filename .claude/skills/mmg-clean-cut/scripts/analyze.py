#!/usr/bin/env python3
"""Map an MMG program: operations, part outlines, labels, and features that might be labels.

Usage: python3 analyze.py PROGRAM.MMG OUT_DIR [--stock-in 0.71]
Writes OUT_DIR/<name>_map.png (numbered features) and prints a feature table.
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gcode import read_lines, parse, floors, program_top, move_pts
from PIL import Image, ImageDraw, ImageFont

IN = 25.4
LABEL_MAX_DEPTH = 3.2      # mm below the program's assumed top: shallower first floor = label
LABEL_MAX_SIZE = 45.0      # mm: bigger shallow pockets are recesses (channels, plates), not text


CORNER = 300.0            # mm: the sheet ID badge sits within this distance of the sheet's bottom-right


def classify(feats, top):
    parts = [f for f in feats if f['op'] and f['op'].upper().startswith(('OUTER', 'ROUGH'))]
    def inside_part(f):
        x0, y0, x1, y1 = f['bbox']
        return any(p['bbox'][0] <= x0 and p['bbox'][1] <= y0 and x1 <= p['bbox'][2] and y1 <= p['bbox'][3] for p in parts)
    sheet_maxx = max(f['bbox'][2] for f in feats)
    sheet_miny = min(f['bbox'][1] for f in feats)
    def in_corner(f):
        x0, y0, x1, y1 = f['bbox']
        return x0 >= sheet_maxx - CORNER and y1 <= sheet_miny + CORNER
    for f in feats:
        op = (f['op'] or '').upper()
        fl = floors(f, top) or [round(f['zmin'], 3)]
        f['first_floor'] = max(fl)
        if op.startswith('ROUGH'):
            f['kind'] = 'part-rough'
        elif op.startswith('OUTER'):
            f['kind'] = 'part-outer'
        elif (op.startswith('POCKET') and f['first_floor'] >= top - LABEL_MAX_DEPTH
              and max(f['bbox'][2] - f['bbox'][0], f['bbox'][3] - f['bbox'][1]) <= LABEL_MAX_SIZE):
            f['kind'] = 'label'           # shallow and letter-sized: text, arrows, marks
        elif op.startswith('POCKET') and not inside_part(f) and in_corner(f):
            f['kind'] = 'label'           # sheet ID badge (I9, B2 ...): bottom-right corner, outside the parts
            f['sheet_id'] = True
        elif op.startswith('POCKET'):
            f['kind'] = 'pocket'
        elif op.startswith('SLOT'):
            f['kind'] = 'slot'
        elif op.startswith('HOLE'):
            f['kind'] = 'hole'
        else:
            f['kind'] = 'other'
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('program'); ap.add_argument('out_dir')
    ap.add_argument('--stock-in', type=float, default=0.71)
    a = ap.parse_args()
    lines = read_lines(a.program)
    feats, rz = parse(lines)
    top = program_top(lines)
    classify(feats, top)
    real_top = a.stock_in * IN
    print(f'program assumes stock top Z{top:.3f} ({top / IN:.3f} in); real stock {a.stock_in} in = Z{real_top:.3f}')
    ops = []
    for f in feats:
        if f['op'] not in ops: ops.append(f['op'])
    for o in ops:
        fs = [f for f in feats if f['op'] == o]
        print(f'  {o:22s} {len(fs):4d} features')
    print('\n id  kind        op                  floors (Z)                         bbox mm')
    for f in feats:
        if f['kind'] in ('hole', 'slot', 'pocket') and '--all' not in sys.argv:
            continue
        x0, y0, x1, y1 = f['bbox']
        print(f"{f['id']:3d}  {('sheet-id' if f.get('sheet_id') else f['kind']):10s}  {f['op'][:18]:18s}  {str(floors(f, top)[:4]):34s} "
              f"{x0:7.1f},{y0:7.1f} {x1 - x0:6.1f}x{y1 - y0:6.1f}")
    counts = {}
    for f in feats: counts[f['kind']] = counts.get(f['kind'], 0) + 1
    print('\nsummary:', counts)

    # map picture
    xs = [v for f in feats for v in (f['bbox'][0], f['bbox'][2])]
    ys = [v for f in feats for v in (f['bbox'][1], f['bbox'][3])]
    minx, maxx, miny, maxy = min(xs) - 20, max(xs) + 20, min(ys) - 20, max(ys) + 20
    S = min(1.6, 3000 / max(maxx - minx, maxy - miny))
    W, H = int((maxx - minx) * S), int((maxy - miny) * S) + 150
    img = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(img)
    P = lambda x, y: ((x - minx) * S, (maxy - y) * S + 150)
    col = {'label': (220, 30, 30), 'part-outer': (30, 100, 220), 'part-rough': (30, 100, 220)}
    for f in feats:
        c = col.get(f['kind'], (190, 190, 190))
        for m in f['cut']:
            if min(m[4], m[7]) < top:
                d.line([P(*p) for p in move_pts(m)], fill=c, width=2 if f['kind'] in col else 1)
    fnt = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 16)
    for f in feats:
        if f['kind'] in ('label', 'part-outer'):
            x0, y0, x1, y1 = f['bbox']
            d.text(P(x0, y1 + 6 / S), str(f['id']), fill=(0, 0, 0), font=fnt)
    f1 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
    f2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    name = os.path.splitext(os.path.basename(a.program))[0]
    d.text((20, 12), f'{name}  -  feature map', fill=(30, 30, 35), font=f1)
    d.text((20, 52), 'red = labels (incl. the sheet ID badge, e.g. I9 / B2, bottom right)   blue = part outlines   grey = holes/slots/pockets', fill=(30, 30, 35), font=f2)
    d.text((20, 80), 'numbers = feature ids for --extra-labels / --not-labels', fill=(30, 30, 35), font=f2)
    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, f'{name}_map.png')
    img.save(out, optimize=True)
    print('map:', out)


if __name__ == '__main__':
    main()
