---
name: mmg-clean-cut
description: Fix fuzzy edges on CNC router programs (.MMG / G-code) cut with a compression bit. Cuts every engraved label (including the sheet ID badge like I9, B2) in one pass at 0.165 in, cuts every part outline in two balanced passes, plunges straight down to depth instead of ramping, and proves with a cut simulation that no part or label changes shape. Use when the user hands over an .MMG file and mentions fuzz, label depth, compression bit, passes, plunging, or "do the same as I9".
---

# MMG clean cut

> Run `cnc-sheet-standard` first (48 x 96 sheet, zero bottom-left, tabs, preview picture).

Rework a CNC program so a **compression bit** leaves clean edges, without changing the shape of
anything. Cutting paths keep their X/Y; Z values change, ramps become straight plunges, and an
extra lap outside each part is removed.

## Shop defaults (confirm if the user says otherwise)

| Setting | Default | Flag |
|---|---|---|
| Real stock thickness | 3/4 in sheets (`*-75in`): 0.71 in (18 mm). 1/2 in sheets (`*-5in`): 0.5 in (user confirmed) | `--stock-in` |
| Label depth, one pass | 0.165 in (Z13.843 in 0.71 stock) | `--label-depth-in` |
| Part pass 1 depth | halfway through, so pass 2 isn't too heavy | `--part-pass1 half` or inches |
| Bit | 6 mm compression | `verify.py --tool-mm` |
| Entry | straight plunge to full cutting depth, then move | `--keep-ramps` to keep ramps |
| Plunge feed | the program's own plunge feed (F5080 = 200 ipm in I9) | `--plunge-feed` mm/min |

Programs are metric, Z0 = spoilboard / bottom of stock. The CAM assumes nominal stock (0.75 in:
clearance Z24.130; 0.5 in: clearance Z17.780); real Baltic birch is metric (18 mm / 12 mm), which is
why shallow labels came out fuzzy. Pick `--stock-in` from the file name / the top analyze reports.
**Entry**: straight plunges (user confirmed for I9 and again for I1-I8). `--keep-ramps` only if asked.

## What it changes

- **Labels**: one pass at the label depth. A label is
  - any shallow engraving in a POCKET op (text, arrows, marks on the parts), and
  - the **sheet ID badge**: the number engraved on the sheet scrap in the bottom-right corner
    (I9, I8, I7, I1, B1, B2, B8 ... and its ring on 3/4 sheets): engraving outside every part and
    within 300 mm of the sheet's bottom-right corner.
  If a label was cut in several step-downs, only the first step's path is kept.
- **Parts**: every outline ends up as pass 1 at half depth + pass 2 = the finish lap through
  (unchanged). Layouts recognised (`scripts/parts.py`):
  - **A** pass-1 lap and through cut are separate features with the same outline: ROUGHING +
    OUTER CUTS (I6-I9), or an onion-skin OUTER op + a through OUTER op (I5). Pass-1 Z rescaled.
  - **B** one feature: ramp, lap at a pass-1 floor, ramp, through laps (I2-I4). Same result.
  - **C** one feature with a single through lap (I1): a copy of it at the pass-1 depth is inserted
    first, then the bit lifts to its plunge height, goes back to the start and runs the original.
  - anything else (e.g. a spiral that winds down with no laps, I2 feature 201) is left as is.
  An extra through lap that runs *outside* the part is removed when a full finish lap follows it
  and it runs off the finish path. Its end is found by, in order: it returns to its ramp end (I9);
  it returns to where the cut first reaches through depth (I3); its point closest to that, with one
  lap left after it, joined by a short (< 1.5 mm) connector (I4, I8). verify proves it was waste.
- **Label ramps**: stretched from the plunge height (gentle) unless that would push a stretch of
  ramp that ran through air (CAM assumed thicker stock) into real wood outside the label's old
  outline; then only the in-wood part of the ramp is deepened (I1).
- **Straight plunges** in everything converted: the bit never moves X/Y while Z is changing in the
  wood. A ramp-in that starts above the wood becomes a rapid to where the ramp ended + a straight
  plunge. A ramp-in that starts inside the wood (pass 2 from the pass-1 floor, tab exits): in labels,
  or where the lap cuts that stretch again later, plunge at the ramp start and follow its path at
  depth; otherwise lift out, rapid to the ramp end, plunge there. A ramp-out becomes a straight lift.
- **Tabs** keep the thickness the old program actually produced: if the old pass 1 cut straight
  across the tabs (no lifts), tab tops go down to the old pass-1 floor; if it lifted over them,
  tabs stay. `--programmed-tabs` keeps the CAM tab height instead.
- **Line numbers** are renumbered N10, N20 ... (no gaps; inserted lines get numbers).
- **Untouched**: holes, slots, deep pockets, feeds, everything else.

## Workflow

Scripts are in `scripts/` next to this file. Run them with `python3 -I` (needs Pillow and numpy).

1. **Map the program**
   ```
   python3 -I scripts/analyze.py IN.MMG OUT_DIR --stock-in 0.71
   ```
   Prints the assumed stock top, operations and features, and writes `OUT_DIR/<name>_map.png`:
   red = labels (the sheet ID badge is listed as `sheet-id`), blue = part outlines. Show the map.
   - Use `--extra-labels` / `--not-labels` with feature ids only if the user says something is or
     isn't a label.
   - If the stock top it reports looks wrong, stop and check before converting.

2. **Convert**
   ```
   python3 -I scripts/convert.py IN.MMG OUT.MMG --stock-in 0.71 [--keep-ramps]
   ```
   Read every `left as is` line and tell the user about those parts.
   Also writes `OUT.MMG.json`, which records what was changed and is needed by verify.

3. **Verify. Never deliver a program that fails.**
   ```
   python3 -I scripts/verify.py IN.MMG OUT.MMG --tool-mm 6
   ```
   Must end with `ALL CHECKS PASSED`:
   - labels: outline at the real wood surface unchanged, cut to label depth, nothing deeper
   - parts: outline identical (under 0.4 mm drawing noise), no new cuts, anything no longer cut is
     on the waste side
   - straight plunges: no move changes Z while moving X/Y in the wood
   - operation summary (compared without line numbers): only part ops and label POCKETs changed
   If it fails, find out why (look at the per-part line, render the area) and fix the script.
   Do not tune a threshold to make it pass.

4. **Deliver**: save to `cnc-renders/<job>/` with the map picture, commit and push, send the
   program to the user. Name delivered programs `<original name>-Depthchange.MMG`
   (e.g. `I1-5in-Depthchange.MMG`); send several together in one message, never zipped. Report in a short table: labels changed (count, depth), parts (pass 1 Z,
   pass 2 Z, extra laps removed), the tab decision, and anything left alone and why.

## Machine: RichAuto controller

- Files must be `.MMG` (it refused `.nc`/`.tap`). Keep names short (the I-sheet names, ~23
  characters, work; a 55-character name was refused).
- Keep the I-sheet layout: first line `N10M03`, no header comments, no G21/G90/G17/G94, no `S` word,
  short op comments like `(POCKET 68)`, `%` as the last line. Programs from other sources (e.g. the
  Joey window frame) need `cnc-renders/joey/richauto_format.py` to match it; motion lines stay as is.

## Watch-outs to tell the user

- Pass 2 cuts about half the sheet thickness in one go; suggest watching the first part.
- Holes and slots stay as the CAM wrote them (spiral / ramped): the user decided to keep them.
  Don't convert them or offer to; deep pockets are also left unchanged.
- Straight plunges use the program's plunge feed (200 ipm in I9) for the full depth: about 4 mm
  for labels, about 9 mm for each part pass. If the bit struggles, rerun with a lower
  `--plunge-feed` (for example 1270 = 50 ipm).

## Reference job

I9 (`cnc-renders/i9/`): 42 labels + the I9 sheet badge, 9 parts in two passes (Z8.890 then
Z-0.254), tabs kept at Z3.81, straight plunges everywhere converted. Made with:
`python3 -I scripts/convert.py I9-75in.MMG out.MMG` and it passes verify.

I1-I8 (`cnc-renders/i1-i8/`): straight plunges, 0.5 in stock for I1-I5, 0.71 in for I6-I8.
Layouts: I1 = C, I2-I4 = B, I5-I8 = A. Left as is: I2 feature 201 (spiral), extra lap of I4 part 123.
