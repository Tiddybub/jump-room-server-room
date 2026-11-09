---
name: mmg-clean-cut
description: Fix fuzzy edges on CNC router programs (.MMG / G-code) cut with a compression bit. Cuts every engraved label (including the sheet ID badge like I9, B2) in one pass at 0.165 in, cuts every part outline in two balanced passes, plunges straight down to depth instead of ramping, and proves with a cut simulation that no part or label changes shape. Use when the user hands over an .MMG file and mentions fuzz, label depth, compression bit, passes, plunging, or "do the same as I9".
---

# MMG clean cut

Rework a CNC program so a **compression bit** leaves clean edges, without changing the shape of
anything. Cutting paths keep their X/Y; Z values change, ramps become straight plunges, and an
extra lap outside each part is removed.

## Shop defaults (confirm if the user says otherwise)

| Setting | Default | Flag |
|---|---|---|
| Real stock thickness | 0.71 in Baltic birch (Z top = 18.034 mm) | `--stock-in` |
| Label depth, one pass | 0.165 in (Z13.843 in 0.71 stock) | `--label-depth-in` |
| Part pass 1 depth | halfway through, so pass 2 isn't too heavy | `--part-pass1 half` or inches |
| Bit | 6 mm compression | `verify.py --tool-mm` |
| Entry | straight plunge to full cutting depth, then move | `--keep-ramps` to keep ramps |
| Plunge feed | the program's own plunge feed (F5080 = 200 ipm in I9) | `--plunge-feed` mm/min |

Programs are metric, Z0 = spoilboard / bottom of stock. The CAM file often assumes 0.75 in stock
(clearance Z24.130); the real sheet is 0.71 in, which is why shallow labels came out fuzzy.

## What it changes

- **Labels**: one pass at the label depth. A label is
  - any shallow engraving in a POCKET op (text, arrows, marks on the parts), and
  - the **sheet ID badge**: the number engraved on the sheet scrap in the bottom-right corner
    (I9, I8, I7, I1, B1, B2, B8 ... and its ring). Anything engraved outside every part counts.
  If a label was cut in several step-downs, only the first step's path is kept.
- **Parts** (ROUGHING + OUTER CUTS pairs): pass 1 = the roughing lap at the pass-1 depth (it runs on
  the finish path); pass 2 = the finish lap through, unchanged. An extra outer-cut lap that runs
  *outside* the part is removed, but only when it is fully off the finish path and a full finish lap
  follows. Otherwise the outer cut is left as is.
- **Straight plunges** in everything converted: the bit never moves X/Y while Z is changing in the
  wood. A ramp-in becomes a rapid above the wood to where the ramp ended, then a straight plunge to
  the cutting depth; the cut then continues exactly as before. A ramp-out becomes a straight lift.
- **Tabs** keep the thickness the old program actually produced: when the old roughing floor was
  below the programmed tab top, tab tops are set to the old roughing floor. `--programmed-tabs`
  keeps the CAM tab height instead.
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
   python3 -I scripts/convert.py IN.MMG OUT.MMG --stock-in 0.71
   ```
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
   - operation summary: only ROUGHING, label POCKETs and OUTER CUTS changed
   If it fails, find out why (look at the per-part line, render the area) and fix the script.
   Do not tune a threshold to make it pass.

4. **Deliver**: save to `cnc-renders/<job>/` with the map picture, commit and push, send the
   program to the user. Report in a short table: labels changed (count, depth), parts (pass 1 Z,
   pass 2 Z, extra laps removed), the tab decision, and anything left alone and why.

## Watch-outs to tell the user

- Pass 2 cuts about half the sheet thickness in one go; suggest watching the first part.
- Line numbers (N…) have gaps where moves were removed; nearly every controller ignores that.
- Slots and holes spiral down gradually and are not changed. Offer to rework them if they fuzz.
- Straight plunges use the program's plunge feed (200 ipm in I9) for the full depth: about 4 mm
  for labels, about 9 mm for each part pass. If the bit struggles, rerun with a lower
  `--plunge-feed` (for example 1270 = 50 ipm).

## Reference job

I9 (`cnc-renders/i9/`): 42 labels + the I9 sheet badge, 9 parts in two passes (Z8.890 then
Z-0.254), tabs kept at Z3.81, straight plunges everywhere converted. Made with:
`python3 -I scripts/convert.py I9-75in.MMG out.MMG` and it passes verify.
