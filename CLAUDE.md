# Shop notes for Claude

- **Any CNC cut work** (creating, editing, fixing, extracting or previewing cut parts, a sheet,
  .MMG or G-code): run the `cnc-sheet-standard` skill FIRST, every time
  (`scripts/standard.py`). It covers:
  - the 48 x 96 in sheet with zero at the bottom-left;
  - parts never rotated;
  - a couple of tabs per part;
  - labels exactly 0.165 in deep (shallow ones are a programmer error: tell the user);
  - 2 passes per part, set for the real thickness (1/2 in or 18 mm);
  - RichAuto .MMG only;
  - a preview picture with every file.
- Keep replies short and to the point.
