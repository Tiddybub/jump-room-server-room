---
name: mmg-clean-cut
description: Fix fuzzy edges on CNC router programs (.MMG / G-code) cut with a compression bit. Cuts every engraved label in one pass at 0.165 in, cuts every part outline in two balanced passes, and proves with a cut simulation that no part or label changes shape. Use when the user hands over an .MMG file and mentions fuzz, label depth, compression bit, passes, or "do the same as I9".
---

# MMG clean cut

Rework a CNC program so a **compression bit** leaves clean edges, without changing the shape of
anything. Only Z values change, plus removal of an extra outside lap. X/Y of every kept move stays
byte-identical.

## Shop defaults (confirm if the user says otherwise)

| Setting | Default | Flag |
|---|---|---|
| Real stock thickness | 0.71 in Baltic birch (Z top = 18.034 mm) | `--stock-in` |
| Label depth, one pass | 0.165 in (Z13.843 in 0.71 stock) | `--label-depth-in` |
| Part pass 1 depth | halfway through, so pass 2 isn't too heavy | `--part-pass1 half` or inches |
| Bit | 6 mm compression | `verify.py --tool-mm` |

Programs are metric, Z0 = spoilboard / bottom of stock. The CAM file often assumes 0.75 in stock
(clearance Z24.130); the real sheet is 0.71 in, which is why shallow labels came out fuzzy.

## What it changes

- **Labels** (shallow engravings in POCKET ops, plus any the user names): one pass at the label
  depth. Each label keeps its ramp-in path; the ramp's Z is rescaled from its plunge height. If a
  label was cut in several step-downs, only the first step's path is kept.
- **Parts** (ROUGHING + OUTER CUTS pairs): pass 1 = the roughing lap at the pass-1 depth (it runs on
  the finish path); pass 2 = the finish lap through, unchanged. An extra outer-cut lap that runs
  *outside* the part is removed, but only when it is fully off the finish path and a full finish lap
  follows. Otherwise the outer cut is left as is.
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
   red = labels found automatically, orange = `label?` (engraved on sheet scrap, cut deep, such as
   the I9 sheet badge), blue = part outlines. Show the map to the user.
   - Treat `label?` features as labels by default: the user confirmed the I9 badge is a label.
     Say which ids you are including.
   - If the stock top it reports looks wrong, stop and check before converting.

2. **Convert**
   ```
   python3 -I scripts/convert.py IN.MMG OUT.MMG --stock-in 0.71 --extra-labels <label? ids>
   ```
   Also writes `OUT.MMG.json`, which records what was changed and is needed by verify.

3. **Verify. Never deliver a program that fails.**
   ```
   python3 -I scripts/verify.py IN.MMG OUT.MMG --tool-mm 6
   ```
   Must end with `ALL CHECKS PASSED`:
   - labels: outline at the real wood surface unchanged, cut to label depth, nothing deeper
   - parts: outline pixel-identical, no new cuts, anything no longer cut is on the waste side
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
- Steeper label ramps: a ramp keeps its path but has to reach a deeper floor. If the bit
  complains on entries, lengthening ramps is a separate change.

## Reference job

I9 (`cnc-renders/i9/`): 42 labels + I9 badge (`--extra-labels 103,104,105`), 9 parts in two passes
(Z8.890 then Z-0.254), tabs kept at Z3.81. The scripts reproduce that program and it passes verify.
