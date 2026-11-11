"""Part outlines -> two passes. Recognises the layouts seen so far:

  A  two features with the same outline: a pass-1 lap that does not go through (ROUGHING op, or an
     onion-skin OUTER op) + an outer cut that goes through            (I6-I9, I5)
  B  one feature: ramp -> lap at a pass-1 floor -> ramp -> through laps   (I2-I4)
  C  one feature: a single through lap, no pass 1                       (I1)
  anything else (e.g. a spiral that winds down with no separate laps) is left as is and reported.

For every part:
  pass 1 = the existing pass-1 lap with its Z rescaled to the new pass-1 depth (A, B), or for C a
           copy of the through lap at the pass-1 depth inserted before it (then the bit lifts to
           the plunge height and goes back to the original start);
  pass 2 = the finish lap through, unchanged.
  An extra through lap that runs off the finish path (it returns to its own ramp end before the
  finish lap starts) is removed when the finish lap after it is a full lap.
  Tabs keep the thickness the old program actually left: if the old pass 1 cut across the tabs
  (no lifts there) the tab tops go down to the old pass-1 floor.
"""
import math
import re
from gcode import move_pts, move_len, ZWORD, set_z

THRU_MAX = 0.3          # a floor at or below this Z goes through the sheet


def _xy(m):
    return abs(m[5] - m[2]) > 1e-6 or abs(m[6] - m[3]) > 1e-6


def _desc_ramp(m):
    return _xy(m) and m[7] < m[4] - 1e-6


def _pass_floors(moves, top):
    """flat levels below the top with real cutting length (>= 25 % of the longest level)"""
    L = {}
    for m in moves:
        if abs(m[7] - m[4]) < 1e-9 and m[7] < top - 0.01:
            z = round(m[7], 3)
            L[z] = L.get(z, 0.0) + move_len(m)
    if not L:
        return [], {}
    big = max(L.values())
    return sorted((z for z, v in L.items() if v >= 0.25 * big), reverse=True), L


def _iou(p, q):
    ix = max(0, min(p[2], q[2]) - max(p[0], q[0])); iy = max(0, min(p[3], q[3]) - max(p[1], q[1]))
    inter = ix * iy; ar = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    return inter / (ar(p) + ar(q) - inter + 1e-9)


class _Path:
    """fast 'is this point on that path' test"""
    def __init__(self, moves, step=0.25):
        self.cells = {}
        for m in moves:
            pp = move_pts(m)
            for a0, a1 in zip(pp, pp[1:]):
                n = max(1, int(math.dist(a0, a1) / step))
                for t in range(n + 1):
                    q = (a0[0] + (a1[0] - a0[0]) * t / n, a0[1] + (a1[1] - a0[1]) * t / n)
                    self.cells.setdefault((round(q[0] / 0.5), round(q[1] / 0.5)), []).append(q)

    def near(self, x, y, tol=0.15):
        cx, cy = round(x / 0.5), round(y / 0.5)
        return any(math.dist((x, y), q) < tol for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   for q in self.cells.get((cx + dx, cy + dy), ()))


def _seg_t(p, a, b):
    """(distance from p to segment ab, position 0..1 of the closest point)"""
    ax, ay = b[0] - a[0], b[1] - a[1]
    L2 = ax * ax + ay * ay
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L2))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay)), t


def _lap_close(moves, s, P0, z):
    """walk from moves[s] (a lap at depth z that starts at P0) to where the path comes back to P0.
    Returns (j, mid): moves[j] reaches P0; mid = it passes P0 part-way (straight moves only).
    None if the lap leaves depth z first, or closes part-way along an arc."""
    run = 0.0
    for j in range(s, len(moves)):
        m = moves[j]
        if abs(m[4] - z) > 1e-6 or abs(m[7] - z) > 1e-6:
            return None
        a, b = (m[2], m[3]), (m[5], m[6])
        if run > 20.0:
            if math.dist(b, P0) < 0.002:
                return j, False
            if m[1] == 1:
                d, t = _seg_t(P0, a, b)
                if d < 0.002 and 0 < t < 1:
                    return j, True
            elif m[1] in (2, 3) and any(math.dist(q, P0) < 0.05 for q in move_pts(m)[1:-1]):
                return None
        run += move_len(m)
    return None


def _set_xy(line, x, y):
    """the same move, ending at x, y"""
    t = re.sub(r'[XY]-?\d+\.?\d*', '', line)
    m = re.search(r'G[0-3](?!\d)', t) or re.match(r'N\d+', t)
    k = m.end() if m else 0
    return t[:k] + f'X{x:.3f}Y{y:.3f}' + t[k:]


def _on_lap(rest, lap, tol=0.01):
    """every point of `rest` lies on `lap` at the same Z (so cutting `rest` again removes nothing new).
    Flat moves are sampled every 1 mm; straight up/down moves must match one in the lap."""
    flat = [(m, move_pts(m)) for m in lap if abs(m[7] - m[4]) < 1e-9 and _xy(m)]
    vert = [m for m in lap if not _xy(m)]
    for m in rest:
        if not _xy(m):
            if not any(math.dist((v[5], v[6]), (m[5], m[6])) < tol and abs(v[4] - m[4]) < 1e-6
                       and abs(v[7] - m[7]) < 1e-6 for v in vert):
                return False
            continue
        if abs(m[7] - m[4]) > 1e-9:
            return False                       # a ramp: not a plain repeat
        P = move_pts(m)
        samples = []
        for a, b in zip(P, P[1:]):
            n = max(1, int(math.dist(a, b)))
            samples += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]
        for q in samples:
            if not any(abs(fm[7] - m[7]) < 1e-6 and
                       any(_seg_t(q, c, d)[0] < tol for c, d in zip(fp, fp[1:])) for fm, fp in flat):
                return False
    return True


def _fmt_move(m, z, fword):
    g = 'G%d' % m[1]
    s = f'{g}X{m[5]:.3f}Y{m[6]:.3f}Z{z:.3f}'
    if m[1] in (2, 3):
        s += f'I{m[8]:.3f}J{m[9]:.3f}'
    return s + (f'F{fword}' if fword else '')


def convert_parts(feats, lines, ptop, real_top, pass1, programmed_tabs, edits, drop, inserts, log):
    """Fills edits {line: text}, drop {line}, inserts {line: [texts after it]}. Returns report rows."""
    rows = []
    cand = [f for f in feats if f['op'] and f['op'].upper().startswith(('OUTER', 'ROUGH'))]
    used = set()
    clusters = []
    for f in cand:
        if f['id'] in used:
            continue
        group = [f] + [g for g in cand if g['id'] != f['id'] and g['id'] not in used and _iou(f['bbox'], g['bbox']) > 0.9]
        for g in group:
            used.add(g['id'])
        clusters.append(sorted(group, key=lambda g: g['start']))

    def get(ln):
        return edits.get(ln, lines[ln])

    def remap(moves, A, old, new):
        k = (A - new) / (A - old)
        for m in moves:
            mz = ZWORD.search(get(m[0]))
            if mz and float(mz.group(1)) < A - 1e-9:
                edits[m[0]] = set_z(get(m[0]), A - (A - float(mz.group(1))) * k)

    for cl in clusters:
        ids = [g['id'] for g in cl]
        thr = [g for g in cl if g['cut'] and min(_pass_floors(g['cut'], ptop)[0] or [99]) <= THRU_MAX]
        if len(cl) > 2 or len(thr) != 1:
            log(f'part {ids}: layout not recognised (features {len(cl)}, through {len(thr)}) - left as is')
            continue
        O = thr[0]
        mv = O['cut']
        floorsO, lens = _pass_floors(mv, ptop)
        T = min(floorsO)
        zp1 = round(real_top - (real_top - T) / 2, 3) if pass1 == 'half' else round(real_top - float(pass1) * 25.4, 3)
        p1_moves, outer, kind, A1, F1 = [], mv, None, None, None
        F1deep, p1_extra = None, ''

        if len(cl) == 2:                                             # layout A
            P = cl[0] if cl[1] is O else cl[1]
            fl, _ = _pass_floors(P['cut'], ptop)
            if not fl or P['start'] > O['start']:
                log(f'part {ids}: pass-1 feature has no floor or comes after the through cut - left as is'); continue
            kind, p1_moves, A1, F1 = 'A', P['cut'], P['plunge'], fl[0]
            if len(fl) > 1:
                # the pass-1 feature steps down more than once (Jack Drain: 2 laps at Z11.43, a ramp,
                # 2 laps at Z3.81): pass 1 = one lap at its first level; the rest goes
                pc = P['cut']
                s0 = next((k for k, m in enumerate(pc) if abs(m[4] - fl[0]) < 1e-6 and abs(m[7] - fl[0]) < 1e-6 and _xy(m)), None)
                cl0 = _lap_close(pc, s0, (pc[s0][2], pc[s0][3]), fl[0]) if s0 is not None else None
                if cl0 is None:
                    log(f'part {ids}: pass-1 feature has levels {fl} and its first lap does not close - left as is'); continue
                j0, mid0 = cl0
                if mid0:
                    edits[pc[j0][0]] = _set_xy(get(pc[j0][0]), pc[s0][2], pc[s0][3])
                for ln in range(pc[j0][0] + 1, P['end'] + 1):
                    drop.add(ln)
                p1_moves = pc[:j0 + 1]
                F1deep = min(fl)
                p1_extra = f'; pass-1 levels {fl} -> one lap'
        else:
            upper = [z for z in floorsO if z > T + THRU_MAX]
            # the ramp that goes down to the through depth
            # (it may stop a little above the through depth where it meets a tab)
            r2 = next((i for i, m in enumerate(mv) if _desc_ramp(m) and upper and m[7] < min(upper) - 0.01), None)
            if r2 is not None and upper:
                # walk back over the ramp run and any straight drop right before it
                s = r2
                while s > 0 and _desc_ramp(mv[s - 1]):
                    s -= 1
                while s > 0 and not _xy(mv[s - 1]) and mv[s - 1][7] < mv[s - 1][4]:
                    s -= 1
                pf, _ = _pass_floors(mv[:s], ptop)
                if not pf:
                    log(f'part {ids}: could not find the pass-1 lap - left as is'); continue
                kind, p1_moves, outer, A1, F1 = 'B', mv[:s], mv[s:], O['plunge'], pf[0]
            elif not upper and len(floorsO) == 1:
                kind = 'C'
            else:
                log(f'part {ids}: floors {floorsO} - spiral or unusual cut, left as is'); continue

        if A1 is not None and A1 < real_top + 0.5:
            log(f'part {ids}: plunge height Z{A1} is not above the wood - left as is'); continue

        # ---- extra through lap off the finish path
        # Candidates for "where the extra lap starts (E) and ends (k2)", tried in order; the first one
        # that passes the checks is used:
        #   1. the end of the first ramp, if the lap comes back to exactly that point   (I9)
        #   2. the point where the cut first reaches the through depth, same test       (I3)
        #   3. the extra lap's point closest to 2., with one lap's length left after it;
        #      joined by a short connector at the through depth                         (I8)
        removed = 0
        keep = outer
        flatT = lambda ms: sum(move_len(m) for m in ms if abs(m[7] - T) < 1e-6 and abs(m[4] - T) < 1e-6)
        def back_to(i, E):
            return next((j for j in range(i + 2, len(outer)) if abs(outer[j][5] - E[0]) < 0.01
                         and abs(outer[j][6] - E[1]) < 0.01 and outer[j][7] <= T + 0.01), None)
        cands = []
        i1 = next((k for k, m in enumerate(outer) if _desc_ramp(m)), None)
        if i1 is not None:
            while i1 + 1 < len(outer) and _desc_ramp(outer[i1 + 1]):
                i1 += 1
            if outer[i1][7] < real_top - 1.0:                       # the ramp really ended in the wood
                E1 = (outer[i1][5], outer[i1][6]); cands.append((i1, E1, back_to(i1, E1), None))
        e = next((k for k, m in enumerate(outer) if m[7] <= T + 0.01 and _xy(m)), None)
        if e is not None:
            E2 = (outer[e][5], outer[e][6]); cands.append((e, E2, back_to(e, E2), None))
            half = flatT(outer[e + 1:]) / 2
            best = None
            for j in range(e + 2, len(outer)):
                if outer[j][7] > T + 0.01:
                    continue
                rest = flatT(outer[j + 1:])
                if 0.8 * half <= rest <= 1.2 * half:
                    d = math.dist((outer[j][5], outer[j][6]), E2)
                    if best is None or d < best[0]:
                        best = (d, j)
            if best and best[0] <= 1.5:
                cands.append((e, E2, best[1], (outer[best[1]][5], outer[best[1]][6]) if best[0] > 0.01 else None))
        for i, E, k2, connector in cands:
            if k2 is None:
                continue
            lapA, lapB = outer[i + 1:k2 + 1], outer[k2 + 1:]
            pB = _Path(lapB)
            # the lap's last move comes back to where the finish lap starts: don't count it
            ptsA = [m for m in lapA if _xy(m) and math.dist((m[5], m[6]), E) > 0.05]
            on = sum(pB.near(m[5], m[6]) for m in ptsA) / max(1, len(ptsA))
            lenA, lenB = flatT(lapA), flatT(lapB)
            # an offset lap shares only the stretch near its start/tab with the finish lap (I9: up to
            # ~15 %); the finish lap itself would be ~100 % on path. verify.py checks the result.
            # and the finish lap must be the same loop, not one with extra detail (notches) that the
            # outer lap skips: removing the outer lap would then leave slivers in those notches (I4 #123)
            if on < 0.5 and 0.8 * lenA <= lenB <= 1.2 * lenA and lenA > 0:
                for m in lapA:
                    drop.add(m[0])
                removed = len(lapA)
                keep = outer[:i + 1] + lapB
                if connector:
                    inserts.setdefault(outer[i][0], []).append(f'G1X{connector[0]:.3f}Y{connector[1]:.3f}')
                break

        # ---- the through lap cut twice on the same path at the same depth (Jack Drain): drop the repeat
        repeat = 0
        e = next((k for k, m in enumerate(keep) if abs(m[7] - T) < 1e-6 and (m[4] > T + 1e-6 or _xy(m))), None)
        if e is not None:
            E = (keep[e][5], keep[e][6])
            s1 = e + 1 if keep[e][4] > T + 1e-6 else e
            # walk the lap; tab lifts leave depth T, so follow the whole path, not one level
            run, close = 0.0, None
            for j in range(s1, len(keep)):
                m = keep[j]
                if run > 20.0 and abs(m[4] - T) < 1e-6 and abs(m[7] - T) < 1e-6:
                    if math.dist((m[5], m[6]), E) < 0.002:
                        close = (j, False); break
                    if m[1] == 1:
                        d, t = _seg_t(E, (m[2], m[3]), (m[5], m[6]))
                        if d < 0.002 and 0 < t < 1:
                            close = (j, True); break
                run += move_len(m)
            if close:
                j, mid = close
                m = keep[j]
                lap1 = keep[s1:j] + [(m[0], m[1], m[2], m[3], m[4], E[0], E[1], m[7], m[8], m[9])]
                rest = ([(m[0], m[1], E[0], E[1], m[4], m[5], m[6], m[7], m[8], m[9])] if mid else []) + keep[j + 1:]
                lenL = sum(move_len(x) for x in lap1)
                if rest and sum(move_len(x) for x in rest) <= lenL + 0.1 and _on_lap(rest, lap1):
                    if mid:
                        edits[m[0]] = _set_xy(get(m[0]), E[0], E[1])
                    for ln in range(m[0] + 1, O['end'] + 1):
                        drop.add(ln)
                    repeat = len(keep) - j - 1 + (1 if mid else 0)
                    keep = keep[:j + 1]

        # ---- pass 1
        if kind in ('A', 'B'):
            remap(p1_moves, A1, F1, zp1)
            p1_note = f'pass 1 Z{F1} -> Z{zp1}{p1_extra}'
        else:
            pl = next((k for k, m in enumerate(mv) if not _xy(m) and m[7] < m[4]), None)
            A = mv[pl][7] if pl is not None else None
            if pl is None or A < real_top + 0.5 or pl + 1 >= len(mv):
                log(f'part {ids}: single through lap without a plunge above the wood - left as is'); continue
            k = (A - zp1) / (A - T)
            new = []
            for m in mv[pl + 1:]:
                fw = None
                f = re.search(r'F(-?\d+\.?\d*)', lines[m[0]])
                if f:
                    fw = f.group(1)
                z = m[7] if m[7] >= A else A - (A - m[7]) * k
                new.append(_fmt_move(m, z, fw))
            S = (mv[pl][5], mv[pl][6])
            new += [f'G1Z{A:.3f}', f'G0X{S[0]:.3f}Y{S[1]:.3f}']
            inserts.setdefault(mv[pl][0], []).extend(new)
            # the original cut resumes after a G0: make sure its first line is G1 with a feed
            nxt = mv[pl + 1][0]
            t = get(nxt)
            if not re.search(r'G[0-3](?!\d)', t):
                t = re.sub(r'^(N\d+)', r'\1G1', t) if t.startswith('N') else 'G1' + t
            if not re.search(r'F-?\d', t):
                fw = next((re.search(r'F(-?\d+\.?\d*)', lines[m[0]]).group(1) for m in mv[pl + 1:]
                           if re.search(r'F(-?\d+\.?\d*)', lines[m[0]]) and _xy(m)), None)
                if fw:
                    t += f'F{fw}'
            edits[nxt] = t
            p1_note = f'pass 1 added at Z{zp1} (was a single through lap)'

        # ---- tabs
        # tab top = the lift height with the most travel (short odd levels are transitions, not tabs)
        tabs = sorted((z for z, v in lens.items() if T + 0.01 < z < ptop and z not in floorsO and v >= 5.0),
                      key=lambda z: -lens[z])
        tab_note = 'no tabs'
        if tabs:
            tz = tabs[0]
            lifted = any(abs(m[7] - m[4]) < 1e-9 and tz - 1e-6 <= m[7] < ptop and move_len(m) >= 1.0 for m in p1_moves) or kind == 'C'
            Fd = F1deep if F1deep is not None else F1     # deepest level the old pass 1 reached
            if not programmed_tabs and kind in ('A', 'B') and not lifted and Fd < tz:
                for m in keep:
                    mz = ZWORD.search(get(m[0]))
                    if mz and abs(float(mz.group(1)) - tz) < 1e-6:
                        edits[m[0]] = set_z(get(m[0]), Fd)
                tab_note = f'tabs Z{tz} -> Z{Fd} (thickness the old pass 1 left)'
            else:
                tab_note = f'tabs Z{tz} kept'
        rows.append({'ids': ids, 'pass1': [g['id'] for g in cl if g is not O] or [O['id']], 'outer': O['id'],
                     'layout': kind, 'pass1_z': zp1, 'through_z': T, 'extra_lap_moves_removed': removed,
                     'repeat_lap_moves_removed': repeat, 'tabs': tab_note})
        log(f'part {ids} layout {kind}: {p1_note}, pass 2 through Z{T}; extra lap removed: {removed} moves; '
            f'repeat through lap removed: {repeat} moves; {tab_note}')
    return rows
