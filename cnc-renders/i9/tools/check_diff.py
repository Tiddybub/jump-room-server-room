import re, sys
sys.path.insert(0, sys.argv[3])
from groups import parse_groups
a = open(sys.argv[1]).read().replace('\r', '').split('\n')
b = open(sys.argv[2]).read().replace('\r', '').split('\n')
_, groups = parse_groups(sys.argv[1])
label_lines = set()
for g in groups:
    if g['op'] and g['op'].startswith('POCKET') and 16 < g['zmin'] < 19:
        label_lines.update(range(g['start'], g['end'] + 1))
assert len(a) == len(b), 'line count differs'
bad, nd, zs = 0, 0, []
for i, (x, y) in enumerate(zip(a, b)):
    if x == y: continue
    nd += 1
    strip = lambda s: re.sub(r'Z-?\d+\.?\d*', 'Z', s)
    if strip(x) != strip(y) or i not in label_lines:
        bad += 1; print('UNEXPECTED', i + 1, x, '|', y)
    zs.append(float(re.search(r'Z(-?\d+\.?\d*)', y).group(1)))
print(f'lines {len(a)}, changed {nd}, changed outside labels or non-Z: {bad}, new Z range {min(zs):.3f}..{max(zs):.3f}')
