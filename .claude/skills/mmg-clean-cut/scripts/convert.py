#!/usr/bin/env python3
"""Clean-cut conversion for a compression bit.

  labels : one pass at --label-depth-in (default 0.165 in) below the real stock top. X/Y untouched.
           Each label keeps its ramp-in path (Z rescaled from its plunge height); if a label was
           cut in several step-downs, only the first step's path is kept.
  parts  : outline in two passes. Pass 1 = the roughing lap (same path as the finish lap) at
           --part-pass1 (default: halfway through). Pass 2 = the finish lap through, unchanged.
           An extra outer-cut lap that runs outside the part (returns to the ramp-end point
           before the finish lap) is removed. Tabs keep the thickness the old program really
           left (old roughing floor) unless --programmed-tabs.
  plunges: in every converted feature the bit plunges straight down to cutting depth, then moves
           (ramp-ins become a rapid above the wood + straight plunge; ramp-outs become straight lifts).

Usage: python3 convert.py IN.MMG OUT.MMG [--stock-in 0.71] [--label-depth-in 0.165]
           [--extra-labels 103,104] [--not-labels 7,8] [--part-pass1 half|<in>]
           [--no-labels] [--no-parts] [--programmed-tabs] [--keep-ramps] [--plunge-feed 5080]
Writes OUT.MMG and OUT.MMG.json (what was changed; used by verify.py).
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import math
from gcode import read_lines, write_lines, parse, floors, program_top, set_z, ZWORD, move_pts, move_len
from analyze import classify
import noramp

IN = 25.4


def ids(s):
    return {int(x) for x in s.split(',') if x.strip()} if s else set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--stock-in', type=float, default=0.71)
    ap.add_argument('--label-depth-in', type=float, default=0.165)
    ap.add_argument('--extra-labels', default='')
    ap.add_argument('--not-labels', default='')
    ap.add_argument('--part-pass1', default='half')
    ap.add_argument('--no-labels', action='store_true')
    ap.add_argument('--no-parts', action='store_true')
    ap.add_argument('--programmed-tabs', action='store_true')
    ap.add_argument('--keep-ramps', action='store_true', help='keep ramp entries instead of straight plunges')
    ap.add_argument('--plunge-feed', default=None, help='feed (mm/min) for straight plunges; default = the program plunge feed')
    a = ap.parse_args()

    lines = read_lines(a.src)
    feats, _ = parse(lines)
    ptop = program_top(lines)
    classify(feats, ptop)
    top = a.stock_in * IN
    z_label = round(top - a.label_depth_in * IN, 3)
    edits, drop = {}, set()
    report = {'stock_in': a.stock_in, 'label_z': z_label, 'program_top': ptop, 'labels': [], 'parts': []}

    def remap(moves, A, old, new):
        k = (A - new) / (A - old)
        for m in moves:
            line = edits.get(m[0], lines[m[0]])
            mz = ZWORD.search(line)
            if not mz:
                continue
            z = float(mz.group(1))
            if z < A - 1e-9:
                edits[m[0]] = set_z(line, A - (A - z) * k)

    # ---------------- labels
    if not a.no_labels:
        chosen = [f for f in feats if (f['kind'] == 'label' or f['id'] in ids(a.extra_labels))
                  and f['id'] not in ids(a.not_labels)]
        for f in chosen:
            fl = floors(f, ptop)
            if not fl:
                print(f'label {f["id"]}: no cutting depth found, skipped'); continue
            first, A = fl[0], f['plunge']
            if A <= first:
                print(f'label {f["id"]}: plunge height {A} not above floor {first}, skipped'); continue
            mv = f['cut']
            cut = next((i for i, m in enumerate(mv) if min(m[4], m[7]) < first - 1e-6), len(mv))
            for m in mv[cut:]:
                drop.add(m[0])
            remap(mv[:cut], A, first, z_label)
            report['labels'].append(f['id'])
            print(f'label {f["id"]:3d}: floor Z{first} -> Z{z_label}'
                  + (f', removed {len(mv) - cut} deeper step-down moves' if cut < len(mv) else ''))

    # ---------------- parts
    if not a.no_parts:
        rough = [f for f in feats if f['kind'] == 'part-rough']
        outer = [f for f in feats if f['kind'] == 'part-outer']
        def iou(p, q):
            ix = max(0, min(p[2], q[2]) - max(p[0], q[0])); iy = max(0, min(p[3], q[3]) - max(p[1], q[1]))
            inter = ix * iy; ar = lambda b: (b[2] - b[0]) * (b[3] - b[1])
            return inter / (ar(p) + ar(q) - inter + 1e-9)
        for o in outer:
            r = max(rough, key=lambda q: iou(q['bbox'], o['bbox']), default=None)
            if r is None or iou(r['bbox'], o['bbox']) < 0.9:
                print(f'part {o["id"]}: no matching roughing lap, skipped'); continue
            of = floors(o, ptop); rf = floors(r, ptop)
            thru, old_rough = min(of), rf[0]
            z_p1 = round(top - (top - thru) / 2, 3) if a.part_pass1 == 'half' else round(top - float(a.part_pass1) * IN, 3)
            remap(r['cut'], r['plunge'], old_rough, z_p1)
            # outer: ramp -> lap A (outside) -> back at ramp end -> finish lap
            mv = o['cut']
            i = next(k for k, m in enumerate(mv) if m[7] < m[4] - 1e-9 and m[4] <= o['plunge'] + 1e-6)
            while i + 1 < len(mv) and mv[i + 1][7] < mv[i + 1][4] - 1e-9:
                i += 1
            P = (mv[i][5], mv[i][6])
            k2 = next((j for j in range(i + 2, len(mv)) if abs(mv[j][5] - P[0]) < 0.01
                       and abs(mv[j][6] - P[1]) < 0.01 and mv[j][7] <= thru + 0.01), None)
            removed = 0
            keep = mv
            if k2 is not None:
                # only an extra lap that runs OFF the finish path, followed by a full finish lap
                cells = {}
                for m in r['cut']:
                    pp = move_pts(m)
                    for a0, a1 in zip(pp, pp[1:]):
                        n = max(1, int(math.dist(a0, a1) / 0.25))
                        for t in range(n + 1):
                            q = (a0[0] + (a1[0] - a0[0]) * t / n, a0[1] + (a1[1] - a0[1]) * t / n)
                            cells.setdefault((round(q[0] / 0.5), round(q[1] / 0.5)), []).append(q)
                def on_path(x, y):
                    cx, cy = round(x / 0.5), round(y / 0.5)
                    return any(math.dist((x, y), q) < 0.15 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                               for q in cells.get((cx + dx, cy + dy), ()))
                lap_a = [m for m in mv[i + 1:k2 + 1] if (m[2], m[3]) != (m[5], m[6])]
                frac_on = sum(on_path(m[5], m[6]) for m in lap_a) / max(1, len(lap_a))
                rough_len = sum(move_len(m) for m in r['cut'] if abs(m[7] - m[4]) < 1e-9)
                after_on = sum(move_len(m) for m in mv[k2 + 1:] if on_path(m[5], m[6]) and on_path(m[2], m[3]))
                if frac_on > 0.1 or after_on < 0.8 * rough_len:
                    print(f'part {o["id"]}: no separate outside lap (lap on finish path {frac_on:.0%}, '
                          f'finish lap after it {after_on:.0f}/{rough_len:.0f} mm) - outer cut left as is')
                    k2 = None
            if k2 is not None:
                for m in mv[i + 1:k2 + 1]:
                    drop.add(m[0])
                removed = k2 - i
                keep = mv[k2 + 1:] + mv[:i + 1]
            tabs = [z for z in of if z > thru + 0.01]
            tab_note = 'no tabs'
            for tz in tabs:
                if not a.programmed_tabs and old_rough < tz:
                    for m in keep:
                        line = edits.get(m[0], lines[m[0]]); mz = ZWORD.search(line)
                        if mz and abs(float(mz.group(1)) - tz) < 1e-6:
                            edits[m[0]] = set_z(line, old_rough)
                    tab_note = f'tabs Z{tz} -> Z{old_rough} (thickness the old roughing pass left)'
                else:
                    tab_note = f'tabs Z{tz} kept'
            report['parts'].append([r['id'], o['id']])
            print(f'part {o["id"]:3d}: pass 1 Z{old_rough} -> Z{z_p1}, pass 2 through Z{thru}; '
                  f'removed extra lap: {removed} moves; {tab_note}')

    out = [edits.get(i, l) for i, l in enumerate(lines) if i not in drop]

    # ---------------- straight plunges: no X/Y movement while Z changes in the converted features
    if not a.keep_ramps:
        targets = sorted(set(report['labels']) | {x for p in report['parts'] for x in p})
        out, n_in, n_out, warns = noramp.apply(out, targets, top, a.plunge_feed)
        for w in warns:
            print('  note:', w)
        report['ramps_to_plunges'] = n_in; report['ramp_outs_to_lifts'] = n_out
        report['plunge_feed'] = a.plunge_feed or 'program plunge feed'
        print(f'straight plunges: {n_in} ramp-ins replaced, {n_out} ramp-outs replaced')
    write_lines(a.dst, out)
    report['lines_removed'] = len(drop); report['lines_edited'] = len(edits)
    json.dump(report, open(a.dst + '.json', 'w'), indent=1)
    print(f'wrote {a.dst}: {len(report["labels"])} labels, {len(report["parts"])} parts, '
          f'{len(edits)} lines edited, {len(drop)} lines removed')


if __name__ == '__main__':
    main()
