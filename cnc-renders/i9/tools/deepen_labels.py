"""Deepen the engraved labels in a program to a single full-depth pass. X/Y untouched.

Label = a POCKET cutting group whose deepest point is shallower than LABEL_MAX_DEPTH below the top.
Inside each label group every Z below the feed-plunge height A is remapped
    z' = A - (A - z) * (A - Z_NEW) / (A - z_old_floor)
so the flat floor lands on Z_NEW and the ramp-in / lead-out keep their X/Y path and shape.
"""
import math, re, sys
sys.path.insert(0, sys.argv[3])
from groups import parse_groups

SRC, DST = sys.argv[1], sys.argv[2]
IN = 25.4
STOCK_T = 0.71 * IN                 # real stock, 18.034
Z_NEW = STOCK_T - 0.165 * IN        # 13.843
A = 22.181                          # feed-plunge height every label starts from (above the wood)

lines, groups = parse_groups(SRC)
labels = [g for g in groups if g['op'] and g['op'].startswith('POCKET') and 16.0 < g['zmin'] < 19.0]
changed = 0
for g in labels:
    k = (A - Z_NEW) / (A - g['zmin'])
    for m in g['moves']:
        ln, modal = m[0], m[1]
        line = lines[ln]
        mz = re.search(r'Z(-?\d+\.?\d*)', line)
        if modal == 0 or not mz:
            continue
        z = float(mz.group(1))
        if z >= A - 1e-9:
            continue
        zn = A - (A - z) * k
        lines[ln] = line[:mz.start()] + f'Z{zn:.3f}' + line[mz.end():]
        changed += 1
# ---- the I9 badge on the sheet scrap: ring (one depth) and the I9 letters (two step-downs)
A_B = 21.590                         # feed-plunge height of the badge cuts
badge = [g for g in groups if g['op'] and g['op'].startswith('POCKET') and g['zmin'] < 24
         and g['bbox'][1] < 300 and g['bbox'][3] < 300]
drop = set()
for g in badge:
    mv = [m for m in g['moves'] if m[1] != 0]
    flat = {}
    for m in mv:
        if abs(m[7] - m[4]) < 1e-9 and m[7] < A_B - 1e-6:
            flat[round(m[7], 3)] = flat.get(round(m[7], 3), 0.0) + math.hypot(m[5] - m[2], m[6] - m[3]) \
                + (math.hypot(m[8], m[9]) if m[1] in (2, 3) else 0.0)
    floors = [z for z, L in flat.items() if L > 5.0]       # real cutting depths (ignore short hops between areas)
    first = max(floors)                                    # first step-down floor of this feature
    # keep moves until the program starts descending below the first floor; drop the rest of the feature
    cut = next((i for i, m in enumerate(mv) if min(m[4], m[7]) < first - 1e-6), None)
    if cut is not None:
        for m in mv[cut:]:
            drop.add(m[0])
    k = (A_B - Z_NEW) / (A_B - first)
    for m in mv[:cut] if cut is not None else mv:
        line = lines[m[0]]; mz = re.search(r'Z(-?\d+\.?\d*)', line)
        if not mz: continue
        z = float(mz.group(1))
        if z >= A_B - 1e-9: continue
        lines[m[0]] = line[:mz.start()] + f'Z{A_B - (A_B - z) * k:.3f}' + line[mz.end():]
        changed += 1
    print(f'badge feature lines {g["start"] + 1}-{g["end"] + 1}: floor {first} -> Z{Z_NEW:.3f}, '
          f'dropped {0 if cut is None else len(mv) - cut} deeper-step moves')
lines = [l for i, l in enumerate(lines) if i not in drop]
open(DST, 'w', newline='').write('\r\n'.join(lines))
print(f'{len(labels)} label features, {changed} Z values changed, floors ->',
      sorted({round(g["zmin"], 3) for g in labels}), '-> Z', round(Z_NEW, 3))
