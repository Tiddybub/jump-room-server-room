---
name: cnc-sheet-standard
description: Shop standard for EVERY CNC cut - run this FIRST whenever the user asks to create, edit, fix, convert, extract, split, re-place or preview a cut, sheet, part, CNC file, .MMG or G-code, before any other CNC skill (mmg-clean-cut etc). Sheet is 48 x 96 in on the spoilboard, zero X0 Y0 bottom-left, jobs start at the bottom-left corner, every part held by a couple of tabs, RichAuto .MMG only, files sent one by one in chat, and always a preview picture of the 48 x 96 board with the cut on it.
---

# CNC sheet standard (run first for any cut)

Every cut job follows these rules. Check them first, fix what's off, then use the other CNC
skills (e.g. `mmg-clean-cut` for depths, passes and plunges). End every job with the preview picture.

## The machine

| | |
|---|---|
| Sheet / spoilboard | **48 x 96 in** (1219.2 x 2438.4 mm). X = 48 in width, Y = 96 in length |
| Zero | **X0 Y0 = bottom-left corner of the plywood** (machine view). Z0 = spoilboard (bottom of stock) |
| Controller | RichAuto DSP on a Laguna router. Files are **.MMG only**. Never .nc, .tap or .gcode |
| Bit | 6 mm compression |
| Stock | Baltic birch 3/4 = 0.71 in (18 mm), 1/2 = 0.5 in. Bamboo (`bam` in the name) is 3/4 nominal. Confirm before changing depths |

The user's CAM screen shows the sheet turned 180 degrees, with zero at the top-right of the screen.
The preview uses the machine view: zero is bottom-left and the sheet ID badge (I9, B2 ...) sits
bottom-right.

## Rules for every job

1. **Fits the 48 x 96 sheet.**
2. **Starts at the bottom-left.**
   - A job that doesn't fill the sheet goes to the zero corner, 1/4 in from the left and bottom
     edges to the outside of the bit (`place_on_sheet.py`).
   - Keep the CAM's own op order (labels, holes, slots, then outlines). Don't reorder.
3. **Tabs on every part.**
   - Every part that cuts through needs tabs so it can't slide while cutting.
   - Use **just a couple**: 2 on small parts, about 4 on big panels. Never a lot.
   - If a part has fewer than 2, tell the user and add them on the final through lap: lift to
     about 0.11 in (2.8 mm) for about 1/2 in. There is no script for this yet. Build one and
     prove the outline is unchanged.
   - Don't strip tabs from files that already cut fine unless asked.
4. **Always show the preview.** Run `sheet_preview.py` on the final file and send the picture
   with the file: the 48 x 96 board with the part cut out on it.
5. **Straight plunges.** Plunge to depth, then move. `mmg-clean-cut` handles this.
6. **Depths and passes.**
   - Labels are 0.165 in deep in one pass.
   - Parts are cut in 2 passes.
   - Holes and slots stay as the CAM wrote them. `mmg-clean-cut` handles all of this.
7. **Don't change what already came out good.** If something looks off in a file that cut fine,
   tell the user and ask before changing it.

## RichAuto file rules

- `.MMG` with a short name: about 23 characters or fewer, no spaces. A 55-character name was refused.
- Use the same layout as the I-sheets:
  - First line `N10M03`.
  - Op comments like `(POCKET 68)`.
  - No G21/G90/G17/G94 and no S word.
  - Ends with `M05`, `M30`, `%`.
  - CRLF line endings, ASCII only, no nested parentheses in comments.
- Name depth-fix files `<name>-Depthchange.MMG`.

## Delivering

- Send each .MMG **individually in chat**, with the preview picture. Zip only if asked.
- Keep the reply short (the user has ADHD): what changed, the check result, then the files.
- Commit and push to the working branch. No PRs unless asked.

## Workflow

```bash
S=.claude/skills/cnc-sheet-standard/scripts
python3 $S/sheet_check.py JOB.MMG                    # fits? gap from zero corner? tabs per part
python3 $S/place_on_sheet.py JOB.MMG OUT.MMG          # only if the job isn't at the zero corner
python3 $S/sheet_check.py OUT.MMG                    # must end with RESULT: OK
#   ... other skills as needed (mmg-clean-cut) ...
python3 $S/sheet_preview.py OUT.MMG OUT.png --title "Job name"
```

`sheet_check.py` flags these:
- Cuts that leave the sheet.
- Cuts that start more than 3 in from the zero corner. CAM nest margins of 1-3 in are fine.
- Parts with fewer than 2 tabs.

## Scripts (`scripts/`, use the parser in `../mmg-clean-cut/scripts/gcode.py`)

- `sheet.py`: sheet size, cut bounds at the outside of the bit, and a tab finder. A second
  through lap passes the same tabs, so each tab location counts once. It also sorts through
  cuts into parts and cutouts (a sink hole is a cutout).
- `sheet_check.py`: the report. Exits 1 if something is off.
- `place_on_sheet.py`: shifts every X/Y word by the same amount.
  - Refuses G91, G92 and G53-G59.
  - Checks every arc is I/J-relative.
  - Proves line by line that only X/Y moved, by exactly the shift.
  - An axis already within 1 mm of the margin is left alone.
- `sheet_preview.py`: PNG of the board in machine view. Shows:
  - parts in brown, left-over sheet pale, labels orange, through cuts dark;
  - tabs in red, with rings so they show at board size;
  - the zero corner in blue, with the X/Y arrows;
  - a close-up when the job uses less than about half the sheet.
  It takes about 1 s even on a full sheet.

## Reference jobs

- **Jack Drain DFS (2026-11):**
  - The whole DFS was cut out of `Jack Drain 75bam.MMG`, which also holds a DFS with the sink cut out.
  - It was moved X -592.17 mm to the zero corner, so it now starts 0.25 in left and 0.26 in bottom.
  - It keeps its 4 tabs at Z2.794.
  - Files: `cnc-renders/jack-drain/JackDrain-DFS-48x96.MMG` and its `.png`.
- The I1-I9 sheets and Joey are full CAM nests that already cut well. Their tab counts are the
  CAM's and are left as they are.
