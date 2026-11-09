"""Straight plunges: in the given features, never move X/Y while Z is changing in the wood.

Ramp in  (descending while moving, starting above the wood):
    rapid above the wood to where the ramp ended, then plunge straight down to that Z,
    then continue exactly as before (every later move starts from the same point).
Ramp out (rising while moving):
    at the end of a feature: dropped (the following G0 retract goes straight up);
    mid-feature: rise straight up, then move across at that height (only if that height is above
    the wood; otherwise left as is and reported).
"""
import re
from gcode import parse, WORD

FW = re.compile(r'F(-?\d+\.?\d*)')
NW = re.compile(r'^N(\d+)')


def xy_moved(m):
    return abs(m[5] - m[2]) > 1e-6 or abs(m[6] - m[3]) > 1e-6


def tiny_flat(m):
    return abs(m[7] - m[4]) < 1e-6 and abs(m[5] - m[2]) + abs(m[6] - m[3]) < 0.05


def apply(lines, feat_ids, top, plunge_f=None):
    feats, _ = parse(lines)
    rep = {}          # line index -> replacement text (may contain '\n' for an inserted line)
    drop = set()
    need_f = {}       # line index -> feed to add if the line has none
    warnings = []
    n_in = n_out = 0

    def feed_at(idx):
        for k in range(idx, -1, -1):
            m = FW.search(lines[k])
            if m:
                return m.group(1)
        return None

    def nnum(idx):
        m = NW.match(lines[idx]); return int(m.group(1)) if m else None

    for fid in feat_ids:
        f = feats[fid]
        mv = [m for m in f['moves'] if m[1] != 0]
        i = 0
        while i < len(mv):
            m = mv[i]
            if xy_moved(m) and m[7] < m[4] - 1e-6:                          # ramp in
                j = i
                while True:
                    if j + 1 < len(mv) and xy_moved(mv[j + 1]) and mv[j + 1][7] < mv[j + 1][4] - 1e-6:
                        j += 1
                    elif (j + 2 < len(mv) and tiny_flat(mv[j + 1]) and xy_moved(mv[j + 2])
                          and mv[j + 2][7] < mv[j + 2][4] - 1e-6):
                        j += 2                     # a ramp interrupted by a near-zero move is one ramp
                    else:
                        break
                a, b = mv[i], mv[j]
                if a[4] < top + 0.5:
                    warnings.append(f'feature {fid} line {a[0] + 1}: ramp starts in the wood (Z{a[4]:.3f}), left as is')
                else:
                    cut_f = feed_at(b[0])
                    pf = plunge_f or feed_at(a[0] - 1)
                    na, nb = nnum(a[0]), nnum(b[0])
                    g0 = f'N{na}G0X{b[5]:.3f}Y{b[6]:.3f}'
                    plunge = f'N{nb if j > i else na + 5}G1Z{b[7]:.3f}F{pf}'
                    if j > i:
                        rep[a[0]] = g0; rep[b[0]] = plunge
                        for k in mv[i + 1:j]:
                            drop.add(k[0])
                    else:
                        rep[a[0]] = g0 + '\n' + plunge
                    if j + 1 < len(mv):
                        need_f[mv[j + 1][0]] = cut_f
                    n_in += 1
                i = j + 1
                continue
            if xy_moved(m) and m[7] > m[4] + 1e-6:                          # ramp out
                j = i
                while j + 1 < len(mv) and xy_moved(mv[j + 1]) and mv[j + 1][7] > mv[j + 1][4] + 1e-6:
                    j += 1
                a, b = mv[i], mv[j]
                nxt = mv[j + 1] if j + 1 < len(mv) else None
                if nxt is None or (not xy_moved(nxt) and nxt[7] > nxt[4]):   # end of feature, or a straight lift follows
                    for k in mv[i:j + 1]:
                        drop.add(k[0])
                    n_out += 1
                elif b[7] >= top + 0.5:
                    na, nb = nnum(a[0]), nnum(b[0])
                    up = f'N{na}G1Z{b[7]:.3f}'
                    across = f'N{nb if j > i else na + 5}G1X{b[5]:.3f}Y{b[6]:.3f}'
                    if j > i:
                        rep[a[0]] = up; rep[b[0]] = across
                        for k in mv[i + 1:j]:
                            drop.add(k[0])
                    else:
                        rep[a[0]] = up + '\n' + across
                    n_out += 1
                else:
                    warnings.append(f'feature {fid} line {a[0] + 1}: ramp out ends in the wood, left as is')
                i = j + 1
                continue
            i += 1

    out = []
    for k, l in enumerate(lines):
        if k in drop:
            continue
        l = rep.get(k, l)
        if k in need_f and need_f[k] and not FW.search(l):
            l = l + f'F{need_f[k]}'
        out.extend(l.split('\n'))
    return out, n_in, n_out, warnings
