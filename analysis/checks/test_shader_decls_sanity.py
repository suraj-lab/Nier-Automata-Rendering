#!/usr/bin/env python3
"""The parser gate must reject empty/early-exiting candidates with failure JSON."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent

if __name__ == '__main__':
    try:
        root = HERE.parent / 'runtime/a0-parser-gate-sanity'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            candidate = Path(tmp) / 'empty.py'
            for source in ['pass\n', 'import sys\nsys.exit(0)\n']:
                candidate.write_text(source)
                p = subprocess.run([sys.executable, str(HERE / 'test_shader_decls.py'), str(candidate)], capture_output=True, text=True)
                assert p.returncode != 0 and json.loads(p.stdout)['passed'] is False, 'empty candidate escaped gate'
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
