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
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import math
from gcode import read_lines, write_lines, parse, floors, program_top, set_z, ZWORD, move_pts, move_len
from analyze import classify
import noramp
import parts
import verify
from PIL import ImageChops

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

    def remap_fn(moves, fn):
        for m in moves:
            line = edits.get(m[0], lines[m[0]])
            mz = ZWORD.search(line)
            if mz:
                z = float(mz.group(1)); z2 = fn(z)
                if abs(z2 - z) > 1e-9:
                    edits[m[0]] = set_z(line, z2)

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
            keepm = mv[:cut]
            # Preferred: stretch the ramp from its plunge height (gentle). That can push a stretch of
            # ramp that ran through air (the CAM assumed thicker stock) into the real wood. If that would
            # cut anything outside the label's old outline, stretch only what was already in the wood.
            kA = (A - z_label) / (A - first)
            fA = lambda z: z if z >= A - 1e-9 else A - (A - z) * kA
            mode = 'ramp from plunge height'
            if A > top:
                kT = (top - z_label) / (top - first)
                fT = lambda z: z if z >= top - 1e-9 else top - (top - z) * kT
                newA = [m[:4] + (fA(m[4]),) + m[5:7] + (fA(m[7]),) + m[8:] for m in keepm]
                bx = f['bbox']; box = (bx[0] - 6, bx[1] - 6, bx[2] + 6, bx[3] + 6)
                old_s = verify.raster(mv, box, top, 0.05, 6.0)
                new_s = verify.raster(newA, box, top, 0.05, 6.0)
                extra = ImageChops.subtract(new_s, old_s).histogram()[255] * 0.0025
                if extra > 0.05:
                    remap_fn(keepm, fT)
                    mode = f'in-wood part of the ramp only ({extra:.2f} mm2 would have been new)'
                else:
                    remap_fn(keepm, fA)
            else:
                remap(keepm, A, first, z_label)
            report['labels'].append(f['id'])
            print(f'label {f["id"]:3d}: floor Z{first} -> Z{z_label}'
                  + (f', removed {len(mv) - cut} deeper step-down moves' if cut < len(mv) else '')
                  + ('' if mode == 'ramp from plunge height' else f'; {mode}'))

    # ---------------- parts
    inserts = {}
    if not a.no_parts:
        report['parts'] = parts.convert_parts(feats, lines, ptop, top, a.part_pass1, a.programmed_tabs,
                                              edits, drop, inserts, print)

    out = []
    for i, l in enumerate(lines):
        if i not in drop:
            out.append(edits.get(i, l))
        out.extend(inserts.get(i, []))

    # ---------------- straight plunges: no X/Y movement while Z changes in the converted features
    if not a.keep_ramps:
        targets = sorted(set(report['labels']) | {x for p in report['parts'] for x in p['pass1'] + [p['outer']]})
        out, n_in, n_out, warns = noramp.apply(out, targets, top, a.plunge_feed)
        for w in warns:
            print('  note:', w)
        report['ramps_to_plunges'] = n_in; report['ramp_outs_to_lifts'] = n_out
        report['plunge_feed'] = a.plunge_feed or 'program plunge feed'
        print(f'straight plunges: {n_in} ramp-ins replaced, {n_out} ramp-outs replaced')
    # ---------------- renumber N10, N20 ... (inserted lines need numbers; removes gaps)
    n = 0
    for k, l in enumerate(out):
        if l and not l.startswith('(') and l != '%':
            n += 10
            out[k] = f'N{n}' + re.sub(r'^N\d+', '', l)
    write_lines(a.dst, out)
    report['lines_removed'] = len(drop); report['lines_edited'] = len(edits)
    report['lines_inserted'] = sum(len(v) for v in inserts.values())
    json.dump(report, open(a.dst + '.json', 'w'), indent=1)
    print(f'wrote {a.dst}: {len(report["labels"])} labels, {len(report["parts"])} parts, '
          f'{len(edits)} lines edited, {len(drop)} lines removed, {report["lines_inserted"]} lines inserted')


if __name__ == '__main__':
    main()
