#!/usr/bin/env python3
"""Run the whole shop standard on a cut file, in order:

  1. check the file as the programmer sent it (shallow labels = programmer error -> tell the user)
  2. move it to the X0 Y0 bottom-left corner if it isn't there (moves only, never rotates)
  3. mmg-clean-cut for the REAL thickness: labels 0.165 in in one pass, parts in 2 passes,
     straight plunges, holes and slots untouched
  4. mmg-clean-cut verify: shapes unchanged (must pass)
  5. check the result against the standard (must say RESULT: OK)
  6. preview picture of the 48 x 96 board with the cut on it

usage: python3 standard.py IN.MMG OUT_DIR --name SHORTNAME [--stock-in 0.71|0.5] [--title "..."]
writes OUT_DIR/SHORTNAME-Depthchange.MMG (+ .json report) and OUT_DIR/SHORTNAME-Depthchange.png
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLEAN = os.path.join(HERE, '..', '..', 'mmg-clean-cut', 'scripts')
sys.path.insert(0, HERE)
from sheet import IN, load, in_wood, edge_bounds, real_stock_mm   # noqa: E402
from sheet_check import check, MAX_CORNER_GAP_IN                    # noqa: E402


def run(cmd):
    print('$ ' + ' '.join(os.path.basename(c) if c.endswith('.py') else c for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('out_dir')
    ap.add_argument('--name', required=True, help='short (RichAuto: about 23 characters with -Depthchange.MMG)')
    ap.add_argument('--stock-in', type=float, help='real thickness; default from the CAM top (1/2 -> 0.5, 3/4 -> 0.71)')
    ap.add_argument('--title')
    ap.add_argument('--tool-mm', type=float, default=6.0)
    a = ap.parse_args()

    out = os.path.join(a.out_dir, f'{a.name}-Depthchange.MMG')
    if len(os.path.basename(out)) > 23:
        print(f'WARNING: {os.path.basename(out)} is {len(os.path.basename(out))} characters; RichAuto took 23. Use a shorter --name.')
    os.makedirs(a.out_dir, exist_ok=True)
    _, feats, top = load(a.src)
    real, why = real_stock_mm(top, a.stock_in)
    if why.startswith('unknown'):
        sys.exit(f'stock thickness unknown (CAM top Z{top:.3f}) - ask the user, then pass --stock-in')
    stock_in = round(real / IN, 3)

    print('== 1. as the programmer sent it')
    problems = check(a.src, a.tool_mm, stock_in=stock_in)
    shallow = [p for p in problems if 'SHALLOW' in p]
    if shallow:
        print('*** TELL THE USER: labels are cut shallower than 0.165 in - programmer error. Fixing it here. ***')

    work = tempfile.mkdtemp()
    try:
        src = a.src
        x0, y0, _, _ = edge_bounds(in_wood(feats, top), a.tool_mm)
        if x0 / IN > MAX_CORNER_GAP_IN or y0 / IN > MAX_CORNER_GAP_IN:
            print('== 2. move to the X0 Y0 corner (no rotation)')
            placed = os.path.join(work, 'placed.MMG')
            if run([sys.executable, os.path.join(HERE, 'place_on_sheet.py'), src, placed,
                    '--tool-mm', str(a.tool_mm)]).returncode:
                sys.exit('placing failed')
            src = placed
        else:
            print('== 2. already at the zero corner - not moved')

        print(f'== 3. mmg-clean-cut for {stock_in} in stock')
        if run([sys.executable, '-I', os.path.join(CLEAN, 'convert.py'), src, out,
                '--stock-in', str(stock_in)]).returncode:
            sys.exit('convert failed')
        print('== 4. verify shapes unchanged')
        r = run([sys.executable, '-I', os.path.join(CLEAN, 'verify.py'), src, out, '--tool-mm', str(a.tool_mm)])
        if r.returncode or 'ALL CHECKS PASSED' not in r.stdout:
            sys.exit('VERIFY FAILED - do not deliver')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print('== 5. result against the standard')
    if check(out, a.tool_mm, stock_in=stock_in):
        sys.exit('STANDARD CHECK FAILED - do not deliver')
    print('== 6. preview')
    run([sys.executable, os.path.join(HERE, 'sheet_preview.py'), out, out[:-4] + '.png',
         '--title', a.title or a.name, '--tool-mm', str(a.tool_mm)])
    print(f'DONE: {out}')


if __name__ == '__main__':
    main()
