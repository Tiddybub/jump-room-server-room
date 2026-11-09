#!/usr/bin/env python3
"""Rewrite a program in the same layout as the I-sheet .MMG files that run on the RichAuto:
first line M03, no header comments, no G21/G90/G17/G94, no S word, short op comments, '%' at the end,
lines renumbered N10, N20 ... Every motion line is kept as is.

Usage: python3 richauto_format.py IN.MMG OUT.MMG
"""
import re, sys
sys.path.insert(0, '/home/user/jump-room-server-room/.claude/skills/mmg-clean-cut/scripts')
from gcode import read_lines, write_lines

src, dst = sys.argv[1], sys.argv[2]
lines = [l for l in read_lines(src) if l.strip() and l.strip() != '%']
out = ['M03']
seen_motion = False
for l in lines:
    body = re.sub(r'^N\d+', '', l).strip()
    if body.startswith('('):
        if not seen_motion:
            continue                                  # header comments: dropped
        m = re.match(r'\((END POCKET \d+|END POCKETS|PART \d+ PASS \d+)', body)
        if m:
            out.append('(' + m.group(1) + ')')        # short comment, like '(POCKET 68)'
        continue
    if re.fullmatch(r'G(21|90|17|94)', body):
        continue                                      # modal setup the I-sheets don't use
    if re.fullmatch(r'M0?3(S\d+(\.\d*)?)?', body):
        continue                                      # spindle already on from the first line
    seen_motion = True
    out.append(body)
out.append('%')
n = 0
for i, l in enumerate(out):
    if not l.startswith('(') and l != '%':
        n += 10
        out[i] = f'N{n}{l}'
write_lines(dst, out + [''])
print(f'wrote {dst}: {len(out)} lines')
