---
name: cnc-sheet-standard
description: Shop standard for EVERY CNC cut - run this FIRST every time we create, edit, fix, convert, extract, split, re-place or preview cut parts, a sheet, a CNC file, .MMG or G-code, before anything else. 48 x 96 in sheet, zero X0 Y0 bottom-left, jobs start at the bottom-left, never rotate parts, a couple of tabs per part, labels exactly 0.165 in deep (shallower = programmer error, tell the user), every part in 2 passes, depths set for the REAL thickness (1/2 in or 18 mm), RichAuto .MMG only, files sent one by one in chat, and always a preview picture of the 48 x 96 board with the cut on it.
---

# CNC sheet standard (run first, every cut file)

One command runs the whole standard. It uses `mmg-clean-cut` for depths, passes and plunges.

```bash
python3 .claude/skills/cnc-sheet-standard/scripts/standard.py IN.MMG cnc-renders/<job>/ \
    --name SHORT [--file-name "User's Name.MMG"] [--stock-in 0.5|0.71] [--title "Job name"]
```

It writes `SHORT-Depthchange.MMG` and `SHORT-Depthchange.png`. If any step fails it stops, and
nothing gets delivered. The steps:

1. **Check the file as the programmer sent it.** It prints `*** TELL THE USER ***` when labels
   are shallow. Say so first in the reply: it's the programmer's error and we fix it here.
2. **Move the job to the X0 Y0 corner** if its cuts start more than 3 in away, or if the bit runs
   off the sheet's left or bottom edge (COC came in flush with the corner, with the bit 1/4 in off
   the sheet). It only shifts the job sideways, never rotates it, and proves every line changed by
   exactly the shift.
3. **Fix depths and passes** with `mmg-clean-cut` for the real thickness: labels 0.165 in in one
   pass, parts in 2 passes, straight plunges.
4. **Verify the shapes are unchanged.** Must say `ALL CHECKS PASSED`.
5. **Check the result against the standard.** Must say `RESULT: OK`.
6. **Make the preview**: the 48 x 96 board with the cut on it.

## The machine

| | |
|---|---|
| Sheet / spoilboard | **48 x 96 in** (1219.2 x 2438.4 mm). X = 48 in width, Y = 96 in length |
| Zero | **X0 Y0 = bottom-left corner of the plywood** (machine view). Z0 = spoilboard (bottom of stock) |
| Controller | RichAuto DSP on a Laguna router. Files are **.MMG only**. Never .nc, .tap or .gcode |
| Bit | 6 mm compression |
| Wood | **1/2 in sheets = 0.5 in. 3/4 in sheets = 18 mm (0.71 in)**, whether Baltic birch or bamboo |

The CAM programs nominal stock: top Z12.700 for 1/2 in, Z19.050 for 3/4 in. Every depth has to be
set for the real thickness. `standard.py` reads the sheet from the CAM top. If the top is anything
else, it stops: ask the user the thickness and pass `--stock-in`.

The user's CAM screen shows the sheet turned 180 degrees, with zero at the top-right of the screen.
The preview uses the machine view: zero is bottom-left and the sheet ID badge (I9, B2 ...) sits
bottom-right.

## Rules for every job

1. **Fits the 48 x 96 sheet.**
2. **Starts at the bottom-left.**
   - A job that doesn't fill the sheet goes to the zero corner, 1/4 in from the left and bottom
     edges to the outside of the bit.
   - Full CAM nests with 1-3 in margins stay where they are.
   - Keep the CAM's own op order (labels, holes, slots, then outlines).
3. **Never change rotation (or mirror).** The programmer rotates parts for a reason. Only move the
   whole job sideways.
4. **Labels are exactly 0.165 in deep** below the real top, in one pass. That includes the sheet
   ID badge.
   - **If a file comes in with labels shallower than 0.165 in, tell the user.** It's the
     programmer's error and we fix it here.
5. **Every part is cut in 2 passes**, on both 1/2 in and 18 mm wood: half depth, then through.
   - One lap per pass. Extra depth levels and repeated laps the CAM added come out.
   - The tabs stay.
6. **Tabs on every part.**
   - Every part that cuts through needs tabs so it can't slide.
   - Use **just a couple**: 2 on small parts, about 4 on big panels. Never a lot.
   - If a part has fewer than 2, tell the user and add them on the through lap: lift to about
     0.11 in (2.8 mm) for about 1/2 in. There is no script for this yet. Build one and prove the
     outline is unchanged.
   - Don't strip tabs from files that already cut fine unless asked.
7. **Straight plunges.** Plunge to depth, then move.
8. **Holes and slots stay as the CAM wrote them.**
9. **Don't change what already came out good.** If something looks off in a file that cut fine,
   tell the user and ask before changing it.
10. **Always show the preview** with the file.

## RichAuto file rules

- If the user names the file, use their name exactly but keep the `.MMG` extension (proven on the
  controller). Otherwise use `<name>-Depthchange.MMG`.
- `.MMG` with a short name: 23 characters or fewer including `-Depthchange.MMG`, no spaces.
  A 55-character name was refused.
- Use the same layout as the I-sheets:
  - First line `N10M03`.
  - Op comments like `(POCKET 68)`.
  - No G21/G90/G17/G94 and no S word.
  - Ends with `M05`, `M30`, `%`.
  - CRLF line endings, ASCII only, no nested parentheses in comments.

## Delivering

- Send each .MMG **individually in chat**, with the preview picture. Zip only if asked.
- Keep the reply short (the user has ADHD): any programmer errors first, then what changed, the
  check result, and the files.
- Commit and push to the working branch. No PRs unless asked.

## Scripts (`scripts/`, use the parser in `../mmg-clean-cut/scripts/gcode.py`)

- `standard.py`: runs everything above, in order.
- `sheet_check.py FILE [--stock-in]`: the report. Exits 1 if something is off. It covers:
  - fits on the sheet;
  - gap from the zero corner;
  - label depth below the real top, and labels cut in more than one pass;
  - passes per part: levels that go most of the way round, ignoring tab lifts;
  - tabs per part.
- `place_on_sheet.py`: shifts every X/Y word by the same amount.
  - Refuses G91, G92 and G53-G59.
  - Checks every arc is I/J-relative.
  - Proves line by line that only X/Y moved.
- `sheet_preview.py`: PNG of the board. Shows:
  - parts in brown, left-over sheet pale, labels orange, through cuts dark;
  - tabs in red, with rings;
  - the zero corner in blue;
  - a close-up when the job is small.
- `sheet.py`: shared helpers:
  - sheet size and real thickness;
  - tab finder (a repeated lap counts each tab once);
  - sorting through cuts into parts, cutouts and slots;
  - label finder and pass counter.

## Reference jobs

- **Jack Drain DFS (2026-11)**, `cnc-renders/jack-drain/DFS NO SINK SINGLE.MMG` (user's name):
  - The whole DFS was cut out of `Jack Drain 75bam.MMG`, which also holds a DFS with the sink cut out.
  - It was moved X -592.17 mm to the zero corner.
  - The labels came in at 0.060 in in real 18 mm stock, a programmer error. Now 0.165 in.
  - The outline came in as 3 depths with 2 laps each. Now 2 passes (Z8.890, then through Z-0.254).
  - It keeps its 4 tabs.
- **COC (2026-11)**, `cnc-renders/coc/Coc.MMG` (user's name), from Drive `COC-5in.MMG`:
  - One part, 38.8 x 28.2 in.
  - The CAM was set for 0.47 in stock. It was run as 0.5 in (the shop's 1/2 in).
  - The labels came in at 0.130 in, a programmer error. Now 0.165 in.
  - Moved +12.35 mm in X and Y so the bit stays on the sheet.
  - It already had 2 passes. It keeps its 8 tabs.
  - verify reports label 0 as 16 mm2 "no longer cut". That's a clean-up path inside the O; over
    the whole word the letters are identical. Check the whole word before worrying about one feature.
- **I1-I9 and Joey**: full CAM nests that already cut well. Leave them as they are. One note:
  I2 has a small 3 x 3 in part with only 1 tab, and it cut fine.
