#!/usr/bin/env python3
"""P1 native ImGui bounds/input gate: panel_test.cpp covers the optional upscaler row at 2 viewports x 3 scales.
The existing preview build runs the ASan/UBSan CPU assertions, then cross-compiles the same panel for Windows.
"""
import json
import subprocess
import sys
from pathlib import Path

A = Path(__file__).resolve().parent.parent
OUT = A / 'runtime' / 'menu-preview'

if __name__ == '__main__':
    try:
        r = subprocess.run([sys.executable, str(A / 'menu-preview/build.py')], capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, (r.stdout + r.stderr)[-1800:]
        assert '"layouts":96' in r.stdout, r.stdout[-600:]
        print(json.dumps({'passed': True, 'limits': 'ImGui CPU layout/input + Windows cross-build, not a game measurement'}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
