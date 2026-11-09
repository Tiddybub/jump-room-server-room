"""Cut every part outline in two equal passes: pass 1 halfway through, pass 2 the finish lap through.

ROUGHING lap (same path as the finish lap): Z remapped so its floor is Z_P1 instead of 3.81;
  its ramp keeps its X/Y and is rescaled from the plunge height A_R.
OUTER CUTS: each part has  ramp -> lap A (0.6 mm outside the part) -> lap B (finish path).
  Lap A is removed from the ramp end until it returns to that same point; what follows (the tab
  where the ramp ends, then lap B) is kept unchanged.
Tabs: the old roughing floor (3.81) shaved the 4.826 tabs on the finish path down to 3.81, so tab
  tops are set to TAB_Z to keep the tabs the thickness the old program actually produced.
"""
import re, sys
sys.path.insert(0, sys.argv[3])
from groups import parse_groups

SRC, DST = sys.argv[1], sys.argv[2]
IN = 25.4
TOP = 0.71 * IN
Z_THRU = -0.254
Z_P1 = round(TOP - (TOP - Z_THRU) / 2, 3)   # pass 1 takes half the depth: 8.890
A_R = 21.590                        # feed-plunge height of the roughing ramps
OLD_RFLOOR = 3.810
TAB_OLD, TAB_Z = 4.826, 3.810

lines, groups = parse_groups(SRC)
drop = set()
edits = {}

def setz(ln, z):
    line = edits.get(ln, lines[ln])
    m = re.search(r'Z(-?\d+\.?\d*)', line)
    edits[ln] = line[:m.start()] + f'Z{z:.3f}' + line[m.end():]

rough = [g for g in groups if g['op'] == 'ROUGHING 83' and g['zmin'] < 24]
outer = [g for g in groups if g['op'] == 'OUTER CUTS 2 96' and g['zmin'] < 24]
k = (A_R - Z_P1) / (A_R - OLD_RFLOOR)
for g in rough:
    for m in g['moves']:
        mz = re.search(r'Z(-?\d+\.?\d*)', lines[m[0]])
        if m[1] == 0 or not mz: continue
        z = float(mz.group(1))
        if z < A_R - 1e-9:
            setz(m[0], A_R - (A_R - z) * k)

for gi, g in enumerate(outer):
    mv = [m for m in g['moves'] if m[1] != 0]
    # ramp = leading run of descending moves after the plunge to A_R
    i = 0
    while i < len(mv) and not (mv[i][7] < mv[i][4] - 1e-9 and mv[i][4] <= A_R + 1e-6):
        i += 1
    while i + 1 < len(mv) and mv[i + 1][7] < mv[i + 1][4] - 1e-9:
        i += 1
    r = i
    P = (mv[r][5], mv[r][6])
    k2 = next(j for j in range(r + 2, len(mv))
              if abs(mv[j][5] - P[0]) < 0.01 and abs(mv[j][6] - P[1]) < 0.01 and mv[j][7] < 0)
    removed = mv[r + 1:k2 + 1]
    for m in removed:
        drop.add(m[0])
    print(f'part {gi}: ramp ends line {mv[r][0] + 1} at ({P[0]:.3f},{P[1]:.3f}) Z{mv[r][7]:.3f}; '
          f'removed lines {removed[0][0] + 1}-{removed[-1][0] + 1} (lap A, {len(removed)} moves)')
    for m in mv[k2 + 1:] + mv[:r + 1]:
        mz = re.search(r'Z(-?\d+\.?\d*)', lines[m[0]])
        if mz and abs(float(mz.group(1)) - TAB_OLD) < 1e-6:
            setz(m[0], TAB_Z)

out = [edits.get(i, l) for i, l in enumerate(lines) if i not in drop]
open(DST, 'w', newline='').write('\r\n'.join(out))
print(f'{len(rough)} roughing laps -> floor Z{Z_P1:.3f}; {len(outer)} outer cuts: {len(drop)} lap-A lines removed; '
      f'{sum(1 for v in edits.values() if "Z3.810" in v)} tab tops set to Z{TAB_Z}')
