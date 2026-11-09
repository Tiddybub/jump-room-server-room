"""Deepen the engraved labels in a program to a single full-depth pass. X/Y untouched.

Label = a POCKET cutting group whose deepest point is shallower than LABEL_MAX_DEPTH below the top.
Inside each label group every Z below the feed-plunge height A is remapped
    z' = A - (A - z) * (A - Z_NEW) / (A - z_old_floor)
so the flat floor lands on Z_NEW and the ramp-in / lead-out keep their X/Y path and shape.
"""
import re, sys
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
open(DST, 'w', newline='').write('\r\n'.join(lines))
print(f'{len(labels)} label features, {changed} Z values changed, floors ->',
      sorted({round(g["zmin"], 3) for g in labels}), '-> Z', round(Z_NEW, 3))
