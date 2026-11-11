#!/usr/bin/env python3
"""Make a single-part program from a two-part sheet program: keep only the features whose cuts lie
in the chosen X range. Every kept move is copied unchanged. Each operation section starts at the safe
height (like the original), ends at the safe height, and the file keeps the original layout
(N10M03 first, short op comments, M05/M30, % last), renumbered N10, N20 ...

Usage: python3 extract_part.py IN.MMG OUT.MMG XMIN XMAX
"""
import re, sys
sys.path.insert(0, '/home/user/jump-room-server-room/.claude/skills/mmg-clean-cut/scripts')
from gcode import read_lines, write_lines

src, dst, xmin, xmax = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
lines = [re.sub(r'^N\d+', '', l) for l in read_lines(src)]
SAFE, CLEAR = 'Z34.290', 'G0Z24.130'

# split into operations, then into blocks that start at a rapid X/Y positioning move
ops, cur = [], None
for l in lines:
    if l.startswith('('):
        cur = {'name': l, 'blocks': []}; ops.append(cur); continue
    if cur is None or l in ('', '%') or re.fullmatch(r'M0?3|M0?5|M30', l):
        continue
    if re.match(r'G0(?!\d).*[XY]', l) or not cur['blocks']:
        cur['blocks'].append([])
    cur['blocks'][-1].append(l)

def xs_of(block):
    """X values of the cutting moves in a block (positioning moves excluded)"""
    out, modal = [], None
    for l in block:
        g = re.match(r'G(\d)', l)
        if g: modal = g.group(1)
        m = re.search(r'X(-?\d+\.?\d*)', l)
        if m and modal in ('1', '2', '3'):
            out.append(float(m.group(1)))
    return out

out, kept_report = ['M03'], []
for op in ops:
    keep = []
    for b in op['blocks']:
        xs = xs_of(b) or [float(re.search(r'X(-?\d+\.?\d*)', b[0]).group(1))]
        inside = all(xmin <= x <= xmax for x in xs)
        if inside != any(xmin <= x <= xmax for x in xs):
            sys.exit(f'block in {op["name"]} straddles the X range - stop')
        if inside:
            keep.append(b)
    if not keep:
        continue
    out.append(op['name'])
    for k, b in enumerate(keep):
        b = list(b)
        if k == 0:
            first = b[0]
            if 'X' not in first or 'Y' not in first:
                sys.exit(f'first kept block of {op["name"]} has no full X/Y position - stop')
            pos = re.sub(r'Z-?\d+\.?\d*', '', first) + SAFE      # rapid to X/Y at the safe height
            rest = b[1:]
            approach = [] if rest and re.fullmatch(r'G0Z-?\d+\.?\d*', rest[0]) else [CLEAR]
            b = [pos] + approach + rest
        out.extend(b)
    if not re.fullmatch(r'G0' + SAFE, out[-1]):
        out.append('G0' + SAFE)
    kept_report.append((op['name'], len(keep), len(op['blocks'])))
out += ['M05', 'M30', '%']
n = 0
for i, l in enumerate(out):
    if not l.startswith('(') and l != '%':
        n += 10; out[i] = f'N{n}{l}'
write_lines(dst, out + [''])
for name, k, t in kept_report:
    print(f'{name}: kept {k} of {t} features')
print(f'wrote {dst}: {len(out)} lines')
