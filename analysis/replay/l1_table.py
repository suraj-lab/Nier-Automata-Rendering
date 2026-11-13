#!/usr/bin/env python3
"""L1 table: for each runtime/replay/l1-* run of 30632051, the section 3b row plus fps and the keys the conf added."""
import json
import subprocess
import sys
from pathlib import Path

A = Path(__file__).resolve().parent.parent
R = A / 'runtime' / 'replay'
capture = '30632051'
labels = sorted(p.name for p in R.glob('l1*'))
for label in labels:
    run = R / label
    shot = run / 'shot-2499.png'
    summary = run / 'summary.json'
    if not shot.exists() or not summary.exists():
        print(f'{label}: incomplete')
        continue
    s = json.loads(summary.read_text())
    stats = subprocess.run([sys.executable, str(A / 'replay' / 'frame_tools.py'), 'stats', str(shot)],
                           capture_output=True, text=True).stdout.strip().split(':', 1)[-1].strip()
    extra = [k for k in s.get('conf', '').splitlines() if k.strip() and not k.startswith('#')
             and k.split('=')[0].strip() not in ('rtx.dlssPreset', 'rtx.upscalerType', 'rtx.xess.preset',
                                                 'rtx.enableRayReconstruction', 'rtx.dlfg.enable',
                                                 'rtx.automation.disableBlockingDialogBoxes',
                                                 'rtx.useNewGuiInputMethod', 'rtx.minPrimsInDynamicBLAS')]
    print(f'{label:24s} fps={s["steady_fps_median"]:5.1f} {stats}  {" ".join(extra)} {s.get("extra_env")}')
